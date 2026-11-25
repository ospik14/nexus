import errno
from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ..auth import authenticated
from ..filesystem import FileProblem
from ..schemas import CreateEntry, DeleteEntry, RenameEntry, RollbackEntry, SaveEntry

router = APIRouter(prefix="/api/files", dependencies=[Depends(authenticated)])


def operate(request: Request, operation: str, *args):
    try:
        return getattr(request.app.state.files, operation)(*args)
    except FileProblem as exc:
        raise HTTPException(exc.status, exc.detail) from None
    except OSError as exc:
        known_errors = {
            errno.ENOENT: (404, "Entry no longer exists"),
            errno.EEXIST: (
                409,
                "An entry at this path already exists or the directory is not empty",
            ),
            errno.ENOTEMPTY: (409, "Only empty directories can be deleted"),
            errno.ENOTDIR: (409, "A path component is no longer a directory"),
            errno.EISDIR: (409, "Expected a regular file"),
            errno.ELOOP: (403, "Symbolic links are not allowed"),
            errno.EXDEV: (403, "Workspace mount boundaries cannot be crossed"),
            errno.EACCES: (403, "The Nexus user does not have permission"),
            errno.EPERM: (
                403,
                "The Nexus user cannot perform this operation or preserve ownership",
            ),
            errno.EROFS: (403, "The workspace is read-only"),
            errno.EAGAIN: (409, "The path changed during resolution. Try again."),
            errno.EDQUOT: (507, "Workspace storage quota exceeded"),
            errno.ENOSPC: (507, "The filesystem is full"),
        }
        status, message = known_errors.get(exc.errno, (500, "The filesystem operation failed"))
        raise HTTPException(status, message) from None


@router.get("/workspaces")
def workspaces(request: Request):
    return {
        "workspaces": list(request.app.state.files.roots),
        "max_file_bytes": request.app.state.settings.max_file_bytes,
    }


@router.get("/{workspace}/tree")
def listing(request: Request, workspace: str, path: str = Query("", max_length=2048)):
    return operate(request, "listing", workspace, path)


@router.get("/{workspace}/search")
def search(request: Request, workspace: str, q: str = Query(min_length=1, max_length=100)):
    return operate(request, "search", workspace, q)


@router.get("/{workspace}/file")
def read(request: Request, workspace: str, path: str = Query(min_length=1, max_length=2048)):
    return operate(request, "read", workspace, path)


@router.get("/{workspace}/download")
def download(request: Request, workspace: str, path: str = Query(min_length=1, max_length=2048)):
    entry = operate(request, "read", workspace, path)
    filename = quote(PurePosixPath(path).name, safe="")
    return Response(
        entry["content"].encode(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.post("/{workspace}/entry", status_code=204)
def create(request: Request, workspace: str, entry: CreateEntry):
    operate(
        request,
        "create",
        workspace,
        entry.path,
        entry.directory,
        request.app.state.settings.admin_name,
    )


@router.patch("/{workspace}/entry")
def rename(request: Request, workspace: str, entry: RenameEntry):
    return operate(
        request, "rename", workspace, entry.path, entry.name, request.app.state.settings.admin_name
    )


@router.delete("/{workspace}/entry", status_code=204)
def remove(request: Request, workspace: str, entry: DeleteEntry):
    operate(
        request,
        "remove",
        workspace,
        entry.path,
        entry.expected,
        request.app.state.settings.admin_name,
    )


@router.put("/{workspace}/file")
def save(request: Request, workspace: str, entry: SaveEntry):
    return operate(
        request,
        "save",
        workspace,
        entry.path,
        entry.content,
        entry.expected,
        request.app.state.settings.admin_name,
    )


@router.get("/{workspace}/revisions")
def revisions(request: Request, workspace: str, path: str = Query(min_length=1, max_length=2048)):
    return {"revisions": operate(request, "revisions", workspace, path)}


@router.post("/{workspace}/rollback")
def rollback(request: Request, workspace: str, entry: RollbackEntry):
    return operate(
        request,
        "rollback",
        workspace,
        entry.path,
        entry.revision,
        entry.expected,
        request.app.state.settings.admin_name,
    )


@router.get("/{workspace}/audit")
def audit(request: Request, workspace: str, before: int | None = Query(None, gt=0)):
    return {"events": operate(request, "audit", workspace, before)}
