from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..auth import authenticated
from ..monitoring import docker_snapshot, journal, system_services

router = APIRouter(prefix="/api", dependencies=[Depends(authenticated)])


@router.get("/processes")
def processes(
    request: Request,
    q: str = Query("", max_length=100),
    sort: Literal["cpu", "memory"] = "cpu",
    direction: Literal["asc", "desc"] = "desc",
    offset: int = Query(0, ge=0, le=8192),
    limit: int = Query(50, ge=1, le=100),
):
    snapshot = request.app.state.processes.list()
    term = q.strip().casefold()
    matched = [
        row
        for row in snapshot["processes"]
        if not term
        or any(term in str(row[key]).casefold() for key in ("pid", "name", "user", "status"))
    ]
    sign = -1 if direction == "desc" else 1
    matched.sort(key=lambda row: (row[sort] is None, sign * (row[sort] or 0), row["pid"]))
    return {
        "processes": matched[offset : offset + limit],
        "total": len(matched),
        "limited": snapshot["limited"],
    }


@router.get("/services")
def services(request: Request):
    return system_services(request.app.state.settings.services)


@router.get("/services/logs")
def service_logs(request: Request, unit: str = Query(max_length=128)):
    if unit not in request.app.state.settings.services:
        raise HTTPException(404, "Service is outside the configured allowlist")
    return journal(unit)


@router.get("/docker")
def containers(request: Request):
    snapshot = docker_snapshot(request.app.state.settings)
    snapshot["containers"] = [
        {key: value for key, value in item.items() if key != "logs"}
        for item in snapshot["containers"]
    ]
    return snapshot


@router.get("/docker/logs")
def container_logs(request: Request, container: str = Query(pattern=r"^[a-f0-9]{12}$")):
    snapshot = docker_snapshot(request.app.state.settings)
    if not snapshot["available"]:
        return {"available": False, "text": "", "detail": snapshot["detail"]}
    for item in snapshot["containers"]:
        if item["id"] == container:
            return item["logs"]
    raise HTTPException(404, "Container is outside the current snapshot")
