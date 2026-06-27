from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .collector import SnapshotCollector, snapshot_to_jsonable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def create_app(refresh_interval: float | None = None) -> FastAPI:
    interval = refresh_interval or float(os.environ.get("GPUTOP_REFRESH_SECONDS", "1.0"))
    process_interval = float(os.environ.get("GPUTOP_PROCESS_SECONDS", "3.0"))
    collector = SnapshotCollector(refresh_interval=interval, process_interval=process_interval)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await collector.start()
        app.state.collector = collector
        yield
        await collector.stop()

    app = FastAPI(
        title="GPU Top Online",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
    )

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        snapshot = collector.snapshot
        return {
            "ok": bool(snapshot and snapshot.ok),
            "seq": snapshot.seq if snapshot else 0,
            "source": snapshot.source if snapshot else "none",
            "gpu_count": len(snapshot.gpus) if snapshot else 0,
            "error": snapshot.error if snapshot else None,
        }

    @app.get("/api/snapshot")
    async def snapshot() -> dict[str, object]:
        return snapshot_to_jsonable(collector.snapshot)

    @app.websocket("/ws/gpu")
    async def gpu_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        last_seq = 0
        try:
            while True:
                current = await collector.wait_for_update(last_seq, timeout=30.0)
                payload = snapshot_to_jsonable(current)
                last_seq = int(payload.get("seq") or last_seq)
                await websocket.send_json(payload)
        except WebSocketDisconnect:
            return

    if FRONTEND_DIST.exists():
        assets_path = FRONTEND_DIST / "assets"
        if assets_path.exists():
            app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        @app.head("/{path:path}", include_in_schema=False)
        async def frontend(path: str):
            requested = FRONTEND_DIST / path
            if path and requested.exists() and requested.is_file():
                return FileResponse(requested)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
