import ctypes
import errno
import hashlib
import os
import re
import secrets
import stat
import threading
from contextlib import contextmanager
from pathlib import PurePosixPath

from .repositories import FileJournal

# openat2 uses syscall 437 on the Linux x86-64 and arm64 targets.
LIBC = ctypes.CDLL(None, use_errno=True)
LIBC.syscall.restype = ctypes.c_long
LIBC.renameat2.argtypes = [
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_uint,
]
RESOLVE_NO_XDEV = 0x01
RESOLVE_NO_MAGICLINKS = 0x02
RESOLVE_NO_SYMLINKS = 0x04
RESOLVE_BENEATH = 0x08
DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
PATH_FLAGS = os.O_PATH | os.O_CLOEXEC
LANGUAGES = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".sh": "bash",
    ".bash": "bash",
    ".toml": "toml",
    ".md": "markdown",
    ".markdown": "markdown",
    ".sql": "sql",
    ".txt": "text",
    ".log": "text",
    ".ini": "text",
    ".cfg": "text",
    ".conf": "text",
    ".csv": "text",
    ".xml": "text",
    ".service": "text",
}
PLAIN_NAMES = {"dockerfile", "makefile", "procfile", "readme", "license", "changelog", "notice"}
BLOCKED_SUFFIXES = {
    ".pem",
    ".key",
    ".crt",
    ".p12",
    ".pfx",
    ".jks",
    ".kdbx",
    ".ppk",
    ".asc",
    ".gpg",
    ".age",
    ".env",
}
BLOCKED_NAMES = {
    "authorized_keys",
    "known_hosts",
    "shadow",
    "passwd",
    "netrc",
    "htpasswd",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "kubeconfig",
    "node_modules",
    "__pycache__",
    "venv",
}
SECRET_NAME = re.compile(
    r"(^|[. _-])(secrets?|credentials?|passwords?|tokens?|private[ _-]?keys?|env)([. _-]|$)", re.I
)
PRIVATE_KEY = re.compile(rb"-----BEGIN [A-Z0-9 ]*(PRIVATE|SECRET) KEY(?: BLOCK)?-----")
MAX_DIRECTORY_SCAN = 5000
MAX_SEARCH_SCAN = 4000
MAX_SEARCH_DIRS = 128
MAX_RESULTS = 300


class FileProblem(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


class OpenHow(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("mode", ctypes.c_uint64), ("resolve", ctypes.c_uint64)]


def open_beneath(root: int, path: str, flags: int, *, allow_mounts=False) -> int:
    resolution = RESOLVE_NO_MAGICLINKS | RESOLVE_NO_SYMLINKS | RESOLVE_BENEATH
    if not allow_mounts:
        resolution |= RESOLVE_NO_XDEV
    how = OpenHow(flags, 0, resolution)
    fd = LIBC.syscall(
        ctypes.c_long(437),
        ctypes.c_int(root),
        ctypes.c_char_p(os.fsencode(path or ".")),
        ctypes.byref(how),
        ctypes.c_size_t(ctypes.sizeof(how)),
    )
    if fd < 0:
        code = ctypes.get_errno()
        if code in {errno.ENOSYS, errno.EINVAL, errno.E2BIG}:
            raise FileProblem(503, "Linux openat2 with path-resolution restrictions is required")
        raise OSError(code, os.strerror(code))
    return fd


def rename_exclusive(parent: int, source: str, name: str) -> None:
    if LIBC.renameat2(parent, os.fsencode(source), parent, os.fsencode(name), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


@contextmanager
def closing_fd(fd: int):
    try:
        yield fd
    finally:
        os.close(fd)


def language(name: str) -> str | None:
    name = name.casefold()
    return LANGUAGES.get(PurePosixPath(name).suffix) or ("text" if name in PLAIN_NAMES else None)


def allowed(name: str) -> bool:
    folded = name.casefold()
    return bool(
        name
        and len(name.encode("utf-8", errors="surrogatepass")) <= 255
        and not name.startswith(".")
        and name == name.strip()
        and not any(
            char in "/\\:"
            or ord(char) < 32
            or 127 <= ord(char) <= 159
            or 0xD800 <= ord(char) <= 0xDFFF
            or 0x202A <= ord(char) <= 0x202E
            or 0x2066 <= ord(char) <= 0x2069
            for char in name
        )
        and folded not in BLOCKED_NAMES
        and PurePosixPath(folded).suffix not in BLOCKED_SUFFIXES
        and not SECRET_NAME.search(folded)
        and not any(
            mark in folded
            for mark in (
                "id_rsa",
                "id_ed25519",
                "privatekey",
                "accesskey",
                "serviceaccount",
                "apikey",
            )
        )
    )


def parts(path: str, allow_root: bool = False) -> list[str]:
    if not path and allow_root:
        return []
    segments = path.split("/")
    if (
        len(path.encode("utf-8", errors="surrogatepass")) > 2048
        or len(segments) > 32
        or not all(map(allowed, segments))
    ):
        raise FileProblem(403, "This path is outside the allowed workspace policy")
    return segments


def validate_contents(contents: bytes) -> str:
    if b"\0" in contents:
        raise FileProblem(415, "Binary files cannot be opened")
    if PRIVATE_KEY.search(contents):
        raise FileProblem(403, "Private keys cannot be opened or stored")
    try:
        return contents.decode("utf-8")
    except UnicodeDecodeError:
        raise FileProblem(415, "Only UTF-8 text files are supported") from None


def hash_bytes(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def signature(info: os.stat_result):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


class Workspaces:
    def __init__(self, settings, sessions):
        self.settings = settings
        self.journal = FileJournal(settings, sessions)
        self.roots: dict[str, int] = {}
        self.lock = threading.Lock()
        try:
            with closing_fd(os.open("/", DIR)) as system_root:
                for name, path in settings.workspaces().items():
                    self.roots[name] = open_beneath(
                        system_root, path.relative_to("/").as_posix(), DIR, allow_mounts=True
                    )
        except BaseException:
            self.close()
            raise

    def close(self):
        for fd in self.roots.values():
            os.close(fd)
        self.roots.clear()

    def root(self, workspace: str) -> int:
        try:
            return self.roots[workspace]
        except KeyError:
            raise FileProblem(404, "Workspace not found") from None

    def _describe(self, root, info, name, path):
        if not allowed(name) or info.st_dev != os.fstat(root).st_dev:
            return None
        directory = stat.S_ISDIR(info.st_mode)
        syntax = language(name)
        if not directory and (not syntax or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            return None
        return {
            "name": name,
            "path": path,
            "directory": directory,
            "size": None if directory else info.st_size,
            "modified": int(info.st_mtime),
            "editable": not directory and info.st_size <= self.settings.max_file_bytes,
        }

    def listing(self, workspace: str, path: str):
        parts(path, allow_root=True)
        root = self.root(workspace)
        entries: list[dict] = []
        scanned = 0
        with (
            closing_fd(open_beneath(root, path, DIR)) as directory,
            os.scandir(directory) as stream,
        ):
            for entry in stream:
                if scanned >= MAX_DIRECTORY_SCAN:
                    break
                scanned += 1
                try:
                    name = entry.name
                    full = f"{path}/{name}" if path else name
                    row = self._describe(root, entry.stat(follow_symlinks=False), name, full)
                except FileNotFoundError:
                    continue
                if row:
                    entries.append(row)
        entries.sort(key=lambda row: (not row["directory"], row["name"].casefold(), row["name"]))
        return {
            "entries": entries[:MAX_RESULTS],
            "limited": scanned >= MAX_DIRECTORY_SCAN or len(entries) > MAX_RESULTS,
        }

    def search(self, workspace: str, term: str):
        root = self.root(workspace)
        found: list[dict] = []
        candidates = [""]
        scanned = visited = 0
        term = term.casefold()
        discarded = False
        while (
            candidates
            and visited < MAX_SEARCH_DIRS
            and scanned < MAX_SEARCH_SCAN
            and len(found) < MAX_RESULTS
        ):
            current = candidates.pop()
            visited += 1
            try:
                with closing_fd(open_beneath(root, current, DIR)) as fd, os.scandir(fd) as stream:
                    for entry in stream:
                        if scanned >= MAX_SEARCH_SCAN or len(found) >= MAX_RESULTS:
                            break
                        scanned += 1
                        path = f"{current}/{entry.name}" if current else entry.name
                        try:
                            row = self._describe(
                                root, entry.stat(follow_symlinks=False), entry.name, path
                            )
                        except FileNotFoundError:
                            continue
                        if not row or len(os.fsencode(path)) > 2048:
                            continue
                        if term in entry.name.casefold():
                            found.append(row)
                        if row["directory"] and path.count("/") < 31:
                            if len(candidates) < MAX_SEARCH_DIRS:
                                candidates.append(path)
                            else:
                                discarded = True
            except OSError as exc:
                if not current:
                    raise
                if exc.errno not in {
                    errno.ENOENT,
                    errno.ELOOP,
                    errno.EXDEV,
                    errno.EACCES,
                    errno.ENOTDIR,
                    errno.EAGAIN,
                }:
                    raise
        found.sort(key=lambda row: (not row["directory"], row["path"].casefold()))
        return {
            "entries": found,
            "limited": bool(
                candidates or discarded or scanned >= MAX_SEARCH_SCAN or len(found) >= MAX_RESULTS
            ),
        }

    def _read(self, root: int, path: str):
        if language(PurePosixPath(path).name) is None:
            raise FileProblem(415, "This file type is unsupported")
        with closing_fd(open_beneath(root, path, PATH_FLAGS)) as pinned:
            info = os.fstat(pinned)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise FileProblem(403, "Only regular, singly linked files are allowed")
            if info.st_size > self.settings.max_file_bytes:
                raise FileProblem(413, "File exceeds the configured size limit")
            with open(
                f"/proc/self/fd/{pinned}",
                "rb",
                opener=lambda parent, flags: os.open(parent, flags | os.O_NONBLOCK | os.O_CLOEXEC),
            ) as stream:
                data = stream.read(self.settings.max_file_bytes + 1)
                if len(data) > self.settings.max_file_bytes:
                    raise FileProblem(413, "File exceeds the configured size limit")
                if (
                    signature(info) != signature(os.fstat(stream.fileno()))
                    or len(data) != info.st_size
                ):
                    raise FileProblem(409, "The file changed while it was being read. Try again.")
                try:
                    acl = os.getxattr(stream.fileno(), "system.posix_acl_access")
                except OSError as exc:
                    if exc.errno not in {errno.ENODATA, errno.ENOTSUP}:
                        raise
                    acl = None
        validate_contents(data)
        return data, info, acl

    def read(self, workspace, path):
        parts(path)
        data, info, _ = self._read(self.root(workspace), path)
        return {
            "path": path,
            "content": data.decode(),
            "digest": hash_bytes(data),
            "size": len(data),
            "modified": int(info.st_mtime),
            "language": language(path.split("/")[-1]),
        }

    @contextmanager
    def _action(self, workspace, path, actor, action, target=None, prior=None, digest=None):
        event = self.journal.begin(workspace, path, actor, action, target, prior, digest)
        try:
            yield
        except Exception:
            self.journal.finish(event, workspace, path, None, "uncertain")
            raise
        else:
            self.journal.finish(
                event, workspace, path, target if action == "rename" else None, "applied"
            )

    def _same_parent(self, root, parent_path, parent):
        with closing_fd(open_beneath(root, parent_path, DIR)) as current:
            before, after = os.fstat(parent), os.fstat(current)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise FileProblem(409, "The containing directory changed")

    @contextmanager
    def _target(self, workspace, path):
        segments = parts(path)
        root = self.root(workspace)
        parent_path = "/".join(segments[:-1])
        if not self.lock.acquire(timeout=3):
            raise FileProblem(503, "Another file operation is in progress. Try again.")
        try:
            with closing_fd(open_beneath(root, parent_path, DIR)) as parent:
                yield root, parent_path, parent, segments[-1]
        finally:
            self.lock.release()

    @contextmanager
    def _stage(self, parent, data, previous=None, restore_mode=None):
        name = f".nexus-{secrets.token_hex(16)}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
        fd = os.open(name, flags, 0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                if previous:
                    info, acl = previous
                    new = os.fstat(stream.fileno())
                    if (info.st_uid, info.st_gid) != (new.st_uid, new.st_gid):
                        os.fchown(stream.fileno(), info.st_uid, info.st_gid)
                    if acl is not None:
                        os.setxattr(stream.fileno(), "system.posix_acl_access", acl)
                    else:
                        try:
                            os.removexattr(stream.fileno(), "system.posix_acl_access")
                        except OSError as exc:
                            if exc.errno not in {errno.ENODATA, errno.ENOTSUP}:
                                raise
                    os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode) & 0o777)
                if restore_mode is not None:
                    os.fchmod(stream.fileno(), restore_mode & 0o777)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            yield name
        finally:
            try:
                os.unlink(name, dir_fd=parent)
            except FileNotFoundError:
                pass

    def _expected(self, data, expected):
        if hash_bytes(data) != expected:
            raise FileProblem(409, "The file changed on disk. Reload it before continuing.")

    def create(self, workspace, path, directory, actor):
        with self._target(workspace, path) as (root, parent_path, parent, name):
            if not directory and not language(name):
                raise FileProblem(415, "Use a supported text file extension")
            with self._action(workspace, path, actor, "mkdir" if directory else "create"):
                self._same_parent(root, parent_path, parent)
                if directory:
                    os.mkdir(name, 0o750, dir_fd=parent)
                else:
                    fd = os.open(
                        name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                        0o640,
                        dir_fd=parent,
                    )
                    with closing_fd(fd):
                        os.fsync(fd)
                os.fsync(parent)

    def rename(self, workspace, path, new_name, actor):
        if not allowed(new_name):
            raise FileProblem(403, "The new name is outside the allowed workspace policy")
        with self._target(workspace, path) as (root, parent_path, parent, name):
            new_path = f"{parent_path}/{new_name}" if parent_path else new_name
            parts(new_path)
            if new_name == name:
                return {"path": path}
            with closing_fd(open_beneath(root, path, PATH_FLAGS)) as pinned:
                info = os.fstat(pinned)
                if not stat.S_ISDIR(info.st_mode):
                    _data, checked, _acl = self._read(root, path)
                    if signature(checked) != signature(info):
                        raise FileProblem(409, "The file changed on disk")
                    if not language(new_name):
                        raise FileProblem(415, "Use a supported text file extension")
            with self._action(workspace, path, actor, "rename", target=new_path):
                self._same_parent(root, parent_path, parent)
                self._verify_entry(parent, name, info)
                rename_exclusive(parent, name, new_name)
                os.fsync(parent)
            return {"path": new_path}

    def _verify_entry(self, parent, name, previous):
        if signature(os.stat(name, dir_fd=parent, follow_symlinks=False)) != signature(previous):
            raise FileProblem(409, "The entry changed on disk. Refresh the file browser.")

    def _replace(self, workspace, path, actor, action, expected, data, location):
        root, parent_path, parent, name = location
        previous, info, acl = self._read(root, path)
        self._expected(previous, expected)
        digest = hash_bytes(data)
        if data != previous:
            with self._stage(parent, data, (info, acl)) as temp:
                with self._action(
                    workspace, path, actor, action, prior=(previous, info), digest=digest
                ):
                    self._same_parent(root, parent_path, parent)
                    self._verify_entry(parent, name, info)
                    os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
                    os.fsync(parent)
        return {"digest": digest, "size": len(data)}

    def save(self, workspace, path, content, expected, actor):
        try:
            data = content.encode("utf-8")
        except UnicodeEncodeError:
            raise FileProblem(415, "Only UTF-8 text files are supported") from None
        if len(data) > self.settings.max_file_bytes:
            raise FileProblem(413, "File exceeds the configured size limit")
        validate_contents(data)
        with self._target(workspace, path) as location:
            return self._replace(workspace, path, actor, "save", expected, data, location)

    def remove(self, workspace, path, expected, actor):
        with self._target(workspace, path) as (root, parent_path, parent, name):
            with closing_fd(open_beneath(root, path, PATH_FLAGS)) as pinned:
                info = os.fstat(pinned)
            directory = stat.S_ISDIR(info.st_mode)
            prior = None
            if not directory:
                data, info, _ = self._read(root, path)
                self._expected(data, expected)
                prior = (data, info)
            with self._action(
                workspace, path, actor, "rmdir" if directory else "delete", prior=prior
            ):
                self._same_parent(root, parent_path, parent)
                self._verify_entry(parent, name, info)
                if directory:
                    os.rmdir(name, dir_fd=parent)
                else:
                    os.unlink(name, dir_fd=parent)
                os.fsync(parent)

    def revisions(self, workspace, path):
        self.root(workspace)
        parts(path)
        return self.journal.revisions(workspace, path)

    def rollback(self, workspace, path, revision, expected, actor):
        with self._target(workspace, path) as (root, parent_path, parent, name):
            item = self.journal.get_revision(workspace, path, revision)
            if item is None:
                raise FileProblem(404, "Revision not found")
            data, mode, digest = item
            if hash_bytes(data) != digest:
                raise FileProblem(409, "The retained revision failed its integrity check")
            if len(data) > self.settings.max_file_bytes or not language(name):
                raise FileProblem(415, "The revision does not match the current workspace policy")
            validate_contents(data)
            if expected is not None:
                return self._replace(
                    workspace,
                    path,
                    actor,
                    "rollback",
                    expected,
                    data,
                    (root, parent_path, parent, name),
                )
            # An explicitly absent target is restored without replacing a concurrently created entry.
            with (
                self._stage(parent, data, restore_mode=mode) as temp,
                self._action(workspace, path, actor, "restore", digest=hash_bytes(data)),
            ):
                self._same_parent(root, parent_path, parent)
                rename_exclusive(parent, temp, name)
                os.fsync(parent)
            return {"digest": hash_bytes(data), "size": len(data)}

    def audit(self, workspace, before):
        self.root(workspace)
        return self.journal.audit(workspace, before)
