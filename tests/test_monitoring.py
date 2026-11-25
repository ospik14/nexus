import json
import time

from nexus.docker_gate import allowed_route, project


def test_processes_are_paginated_searchable_and_read_only(signed_in):
    client, headers = signed_in
    response = client.get("/api/processes", params={"sort": "memory", "limit": 3}).json()
    assert 0 < len(response["processes"]) <= 3
    memory = [item["memory"] for item in response["processes"]]
    assert sorted(memory, reverse=True) == memory
    assert client.get("/api/processes?q=x-no-such-process-x").json()["total"] == 0
    assert client.post("/api/processes", headers=headers, json={}).status_code == 405


def test_systemd_allowlist_and_permissions(signed_in, monkeypatch):
    client, _ = signed_in

    def run(arguments, **_kwargs):
        if arguments[0].endswith("systemctl"):
            return (
                "Id=nexus-test.service\nDescription=Test unit\nActiveState=active\nLoadState=loaded\n",
                0,
                False,
            )
        return "No journal files were opened due to insufficient permissions.", 1, False

    monkeypatch.setattr("nexus.monitoring.command", run)
    assert client.get("/api/services").json()["services"][0]["status"] == "active"
    assert client.get("/api/services/logs?unit=nexus-test.service").json()["available"] is False
    assert client.get("/api/services/logs?unit=other.service").status_code == 404

    def missing(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("nexus.monitoring.command", missing)
    assert not client.get("/api/services").json()["available"]


def test_docker_disabled_missing_stale_and_logs_separate(signed_in):
    client, _ = signed_in
    settings = client.app.state.settings
    assert client.get("/api/docker").json()["enabled"] is False
    settings.docker_enabled = True
    assert client.get("/api/docker").json()["available"] is False
    path = settings.docker_snapshot
    path.write_text(json.dumps({"timestamp": 0, "available": True}))
    assert "stale" in client.get("/api/docker").json()["detail"]
    path.write_text(
        json.dumps(
            {
                "timestamp": int(time.time()),
                "available": True,
                "containers": [
                    {
                        "id": "123456789abc",
                        "name": "test",
                        "logs": {"available": True, "text": "hello"},
                    }
                ],
            }
        )
    )
    assert "logs" not in client.get("/api/docker").json()["containers"][0]
    assert client.get("/api/docker/logs?container=123456789abc").json()["text"] == "hello"
    assert client.get("/api/docker/logs?container=aaaaaa789abc").status_code == 404


def test_docker_gate_keeps_only_required_routes_and_fields():
    identifier = "a" * 64
    assert allowed_route("/version") == ("version", None)
    assert allowed_route("/v1.52/containers/json?limit=32&all=1&size=0&trunc_cmd=0") == (
        "list",
        None,
    )
    assert allowed_route(f"/v1.52/containers/{identifier}/stats?stream=False&one-shot=True") == (
        "stats",
        identifier,
    )
    assert allowed_route(f"/v1.52/containers/{identifier}/stats?stream=True&one-shot=True") is None
    assert allowed_route(f"/v1.52/containers/{identifier}/archive?path=/") is None
    assert (
        allowed_route(f"/v1.52/containers/{identifier}/logs?stdout=1&stderr=1&follow=1&tail=30")
        is None
    )
    assert project(
        "json", {"Id": identifier, "Config": {"Env": ["secret"], "Tty": True}, "Mounts": ["/srv"]}
    ) == {
        "Id": identifier,
        "Name": "",
        "Config": {"Tty": True},
        "State": {"StartedAt": None},
    }


def test_docker_sdk_works_through_restricted_unix_socket(tmp_path, monkeypatch):
    import threading
    from contextlib import closing

    import docker

    from nexus.docker_collector import collect
    from nexus.docker_gate import DockerGate, UnixHTTPServer

    container_id = "a" * 64
    raw_log = b"started\n"
    payloads = {
        "/version": {"ApiVersion": "1.48"},
        "/v1.48/containers/json": [
            {
                "Id": container_id,
                "Names": ["/test"],
                "State": "running",
                "Image": "test:latest",
                "Env": ["secret"],
                "Ports": [
                    {"IP": "127.0.0.1", "PublicPort": 8080, "PrivatePort": 80, "Type": "tcp"}
                ],
            }
        ],
        f"/v1.48/containers/{container_id}/json": {
            "Id": container_id,
            "Name": "/test",
            "Config": {"Tty": False, "Env": ["secret"]},
            "State": {"StartedAt": "2025-01-01T00:00:00Z"},
        },
        f"/v1.48/containers/{container_id}/stats": {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 120},
                "system_cpu_usage": 1000,
                "online_cpus": 2,
            },
            "memory_stats": {"usage": 5000, "limit": 8000, "stats": {"inactive_file": 1000}},
        },
    }

    def engine_get(path, _limit):
        endpoint = path.split("?")[0]
        if endpoint.endswith("/logs"):
            return bytes([1, 0, 0, 0]) + len(raw_log).to_bytes(
                4, "big"
            ) + raw_log, "application/vnd.docker.raw-stream"
        return json.dumps(payloads[endpoint]).encode(), "application/json"

    monkeypatch.setattr("nexus.docker_gate.engine_get", engine_get)
    address = tmp_path / "docker.sock"
    with UnixHTTPServer("", DockerGate, bind_and_activate=False) as server:
        server.socket.bind(str(address))
        server.socket.listen()
        server.log_names = frozenset({"test"})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with closing(docker.DockerClient(base_url=f"unix://{address}", timeout=2)) as client:
                snapshot, _ = collect(client, {container_id: (100, 800)}, {"test"})
                row = snapshot["containers"][0]
                assert row["cpu"] == 20
                assert row["memory"] == 4000
                assert row["logs"]["text"] == "started\n"
                assert row["ports"] == ["127.0.0.1:8080 → 80/tcp"]
                assert "Env" not in client.api.inspect_container(container_id)["Config"]
        finally:
            server.shutdown()
            thread.join(timeout=2)
