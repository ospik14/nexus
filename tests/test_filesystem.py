import os
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

BASE = "/api/files/project"


def read(client, path):
    return client.get(f"{BASE}/file", params={"path": path})


def save(client, headers, path, content, expected):
    return client.put(
        f"{BASE}/file",
        headers=headers,
        json={"path": path, "content": content, "expected": expected},
    )


def test_traversal_secrets_and_special_files(signed_in, installation):
    client, headers = signed_in
    _, workspace = installation
    outside = workspace.parent / "outside.txt"
    outside.write_text("outside")
    (workspace / "link.txt").symlink_to(outside)
    (workspace / "linked-dir").symlink_to(workspace.parent, target_is_directory=True)
    (workspace / ".env").write_text("PRIVATE=test")
    (workspace / "credentials.json").write_text("{}")
    (workspace / "copied.txt").write_text("-----BEGIN OPENSSH PRIVATE KEY-----")
    (workspace / "image.png").write_bytes(b"\x00")
    os.link(outside, workspace / "hardlink.txt")
    os.mkfifo(workspace / "pipe.txt")
    for path in (
        "../outside.txt",
        "/tmp/outside.txt",
        "linked-dir/outside.txt",
        "link.txt",
        ".env",
        "credentials.json",
        "hardlink.txt",
        "copied.txt",
        "pipe.txt",
    ):
        assert read(client, path).status_code == 403, path
    assert read(client, "image.png").status_code == 415
    seen = {row["name"] for row in client.get(f"{BASE}/tree").json()["entries"]}
    assert {"link.txt", ".env", "credentials.json", "hardlink.txt", "pipe.txt"}.isdisjoint(seen)
    escaped = client.post(f"{BASE}/entry", headers=headers, json={"path": "linked-dir/created.txt"})
    assert escaped.status_code == 403
    assert not (workspace.parent / "created.txt").exists()
    assert outside.read_text() == "outside"


def test_save_is_atomic_and_backed_up(signed_in, installation, monkeypatch):
    client, headers = signed_in
    _, workspace = installation
    file = workspace / "script.py"
    file.write_text("print(1)\n")
    file.chmod(0o751)
    before = read(client, "script.py").json()
    real_replace = os.replace

    def observed_replace(source, destination, *, src_dir_fd=None, dst_dir_fd=None):
        assert file.read_text() == "print(1)\n"
        revision = client.app.state.files.revisions("project", "script.py")[0]
        assert revision["digest"] == before["digest"]
        real_replace(source, destination, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr("nexus.filesystem.os.replace", observed_replace)
    result = save(client, headers, "script.py", "print(2)\n", before["digest"])
    assert result.status_code == 200
    assert file.read_text() == "print(2)\n"
    assert stat.S_IMODE(file.stat().st_mode) == 0o751
    assert not list(workspace.glob(".nexus-*"))
    monkeypatch.setattr("nexus.filesystem.os.replace", real_replace)
    revision = client.get(f"{BASE}/revisions", params={"path": "script.py"}).json()["revisions"][0]
    rollback = client.post(
        f"{BASE}/rollback",
        headers=headers,
        json={"path": "script.py", "revision": revision["id"], "expected": result.json()["digest"]},
    )
    assert rollback.status_code == 200
    assert file.read_text() == "print(1)\n"
    events = client.get(f"{BASE}/audit").json()["events"]
    assert [row["action"] for row in events] == ["rollback", "save"]
    assert all(row["result"] == "applied" for row in events)


def test_atomic_failure_preserves_file(signed_in, installation, monkeypatch):
    client, headers = signed_in
    _, workspace = installation
    file = workspace / "recovery.txt"
    file.write_text("original")
    before = read(client, "recovery.txt").json()["digest"]

    def fail(*_args, **_kwargs):
        raise OSError(28, "filesystem full")

    monkeypatch.setattr("nexus.filesystem.os.replace", fail)
    assert save(client, headers, "recovery.txt", "replacement", before).status_code == 507
    assert file.read_text() == "original"
    assert not list(workspace.glob(".nexus-*"))
    assert client.get(f"{BASE}/audit").json()["events"][0]["result"] == "uncertain"


def test_concurrent_saves_and_external_change(signed_in, installation):
    client, headers = signed_in
    _, workspace = installation
    file = workspace / "note.txt"
    file.write_text("original")
    expected = read(client, file.name).json()["digest"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(save, client, headers, file.name, "first", expected)
        second = pool.submit(save, client, headers, file.name, "second", expected)
        assert sorted([first.result().status_code, second.result().status_code]) == [200, 409]
    expected = read(client, file.name).json()["digest"]
    file.write_text("outside editor")
    assert save(client, headers, file.name, "third", expected).status_code == 409
    assert file.read_text() == "outside editor"


def test_create_rename_search_download_delete_and_restore(signed_in, installation):
    client, headers = signed_in
    _, workspace = installation
    for path, directory in (("src", True), ("src/app.py", False)):
        assert (
            client.post(
                f"{BASE}/entry", headers=headers, json={"path": path, "directory": directory}
            ).status_code
            == 204
        )
    original = read(client, "src/app.py").json()["digest"]
    updated = save(client, headers, "src/app.py", "# kept\n", original).json()
    moved = client.patch(f"{BASE}/entry", headers=headers, json={"path": "src", "name": "code"})
    assert moved.json() == {"path": "code"}
    assert (
        client.get(f"{BASE}/search", params={"q": "app"}).json()["entries"][0]["path"]
        == "code/app.py"
    )
    attachment = client.get(f"{BASE}/download", params={"path": "code/app.py"})
    assert attachment.content == b"# kept\n"
    assert "attachment" in attachment.headers["content-disposition"]
    assert (
        client.request(
            "DELETE", f"{BASE}/entry", headers=headers, json={"path": "code"}
        ).status_code
        == 409
    )
    assert (
        client.request(
            "DELETE",
            f"{BASE}/entry",
            headers=headers,
            json={"path": "code/app.py", "expected": updated["digest"]},
        ).status_code
        == 204
    )
    revisions = client.get(f"{BASE}/revisions", params={"path": "code/app.py"}).json()["revisions"]
    assert len(revisions) == 2
    payload = {"path": "code/app.py", "revision": revisions[0]["id"], "expected": None}
    assert client.post(f"{BASE}/rollback", headers=headers, json=payload).status_code == 200
    assert (workspace / "code/app.py").read_text() == "# kept\n"
    assert client.post(f"{BASE}/rollback", headers=headers, json=payload).status_code == 409


@pytest.mark.parametrize("path", ["huge.txt", "bad.txt", "encrypted.pem"])
def test_content_limit_and_type(signed_in, installation, path):
    client, _ = signed_in
    settings, workspace = installation
    (workspace / path).write_bytes(
        {
            "huge.txt": b"x" * (settings.max_file_bytes + 1),
            "bad.txt": b"abc\x00",
            "encrypted.pem": b"text",
        }[path]
    )
    assert (
        read(client, path).status_code
        == {"huge.txt": 413, "bad.txt": 415, "encrypted.pem": 403}[path]
    )
