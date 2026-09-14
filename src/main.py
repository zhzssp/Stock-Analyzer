from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routes import router
from src.config import ROOT, settings
from src.db import Base, SessionLocal, engine
from src.models import AgentSession, Alert, Artifact, FieldPref, MonitorJob, Snapshot, User, WatchItem  # noqa: F401
from src.platform.channels import attach as attach_channels
from src.platform.seed import bootstrap


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        bootstrap(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    attach_channels()
    sched = None
    if "pytest" not in __import__("sys").modules:
        from src.platform.scheduler import start_scheduler

        sched = start_scheduler()
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

    uvicorn.run(
        "src.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
