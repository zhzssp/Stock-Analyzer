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


def _service_already_running(port: int) -> bool:
    """端口能连上，而且 /api/health 返回的是本软件，就说明已经有一个实例在跑。

    重复启动是资源占用翻倍的头号原因：每个实例都自带调度器（每 5 分钟各扫一轮），
    既吃 CPU 也吃授权额度。与其等 uvicorn 报 address in use，不如早一步说清楚。
    """
    import json
    import socket
    import urllib.request

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.8):
            pass
    except OSError:
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2.0) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("ok")) and isinstance(payload.get("market"), dict)


def run() -> None:
    import uvicorn

    from src.platform.tray import start_tray

    if _service_already_running(settings.app_port):
        print("")
        print("助手已经在运行了，不需要再启动一次。")
        print(f"请直接打开：http://{settings.app_host}:{settings.app_port}/")
        print("")
        print("重复启动会多出一个服务进程，每个都在定时扫描，既占资源也费额度。")
        print("要重启：先从右下角托盘选「退出助手」，或在原来那个窗口按 Ctrl+C，再双击 run.cmd。")
        print("")
        return

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
