import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from ..auth import authenticated

router = APIRouter(prefix="/api")


@router.get("/overview", dependencies=[Depends(authenticated)])
def overview(request: Request):
    metrics = request.app.state.metrics
    return {
        "host": metrics.host,
        "sample": metrics.latest,
        "disk_path": str(metrics.settings.disk_path),
    }


@router.get("/history", dependencies=[Depends(authenticated)])
def history(request: Request, window: Literal["15m", "1h", "6h", "24h", "7d"] = "1h"):
    return {"samples": request.app.state.metrics.repo.history(window)}


@router.websocket("/live")
async def live(websocket: WebSocket):
    settings = websocket.app.state.settings
    auth = websocket.app.state.auth
    if websocket.headers.getlist("origin") != [settings.origin]:
        await websocket.close(code=4403)
        return
    metrics = websocket.app.state.metrics
    if not metrics.sockets.acquire(blocking=False):
        await websocket.close(code=4429)
        return
    tasks = set()
    try:
        identity = await run_in_threadpool(auth.identity, websocket.cookies.get(auth.cookie_name))
        if identity is None:
            await websocket.close(code=4401)
            return
        await websocket.accept()
        receive = asyncio.create_task(websocket.receive())
        update = asyncio.create_task(metrics.wait(-1))
        tasks.update((receive, update))
        while True:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED, timeout=8)
            if receive in done:
                message = receive.result()
                if message["type"] != "websocket.disconnect":
                    await websocket.close(code=1008)
                return
            if not await run_in_threadpool(auth.current, identity):
                await websocket.close(code=4401)
                return
            if update in done:
                version, sample = update.result()
                if sample is not None:
                    await asyncio.wait_for(websocket.send_json(sample), timeout=5)
                tasks.remove(update)
                update = asyncio.create_task(metrics.wait(version))
                tasks.add(update)
    except (WebSocketDisconnect, TimeoutError, OSError):
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        metrics.sockets.release()
