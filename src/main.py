from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routes import router
from src.config import ROOT, settings
from src.db import SessionLocal, engine
from src.models import (  # noqa: F401
    AgentSession,
    Alert,
    Artifact,
    ConceptPref,
    FieldPref,
    MonitorJob,
    MonitorPref,
    Snapshot,
    User,
    UserRule,
    WatchItem,
)
from src.platform.channels import attach as attach_channels
from src.platform.migrate import migrate_schema
from src.platform.seed import bootstrap


def init_db() -> None:
    migrate_schema(engine)
    db = SessionLocal()
    try:
        bootstrap(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    from src.api.routes import ensure_market

    ensure_market()
    attach_channels()
    sched = None
    if "pytest" not in __import__("sys").modules:
        from src.market.clock_git import schedule_flush
        from src.platform.scheduler import start_scheduler
        from src.platform.storage import enforce_all

        db = SessionLocal()
        try:
            enforce_all(db)
        finally:
            db.close()
        sched = start_scheduler()
        schedule_flush()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="Stock-Analyzer", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://127.0.0.1:{settings.app_port}",
        f"http://localhost:{settings.app_port}",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")


web_dir = ROOT / "docs" / "frontend"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")


def run() -> None:
    import uvicorn

    from src.platform.tray import start_tray

    config = uvicorn.Config(
        "src.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )
    server = uvicorn.Server(config)
    url = f"http://{settings.app_host}:{settings.app_port}/"
    tray = start_tray(url, on_exit=lambda: setattr(server, "should_exit", True))
    try:
        server.run()
    finally:
        if tray:
            tray.stop()


if __name__ == "__main__":
    run()
