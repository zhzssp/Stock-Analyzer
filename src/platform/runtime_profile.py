"""按本机内存选择运行档位。

轻量档暂停问答和自动盯盘，并缩小进程内行情缓存、降低查询并发。
传统查询、导出、证书和墙钟不受影响。

已经 import 进来的 Python 模块没法可靠卸掉。轻量档省的是扫描和缓存，
不是把问答代码从进程里摘出去。要让工作集真正落下来，切到轻量后退出再开一次。
"""

from __future__ import annotations

import ctypes
import gc
import json
import sys
from typing import Any

from src.config import settings
from src.platform.storage import atomic_write_text, human_bytes

# 物理内存 ≤ 8GB 时，「自动」走轻量。8GB 机器扣掉系统后余量经常不够同时开着盯盘。
LITE_RAM_BYTES = 8 * 1024**3
LITE_CACHE_MB = 16.0
LITE_WORKERS = 2

LITE_DETAIL = "当前是轻量模式：问答和自动盯盘已暂停，传统查询仍可用。到「本机数据」切回「完整」即可恢复。"

_MODES = ("auto", "full", "lite")

_base: dict[str, float | int] | None = None
_state: dict[str, Any] = {
    "request": "auto",
    "resolved": "full",
    "source": "default",
    "locked": False,
    "ram_bytes": None,
}


def profile_path():
    return settings.data_dir / "runtime_profile.json"


def agents_enabled() -> bool:
    return _state["resolved"] != "lite"


def physical_memory_bytes() -> int | None:
    """本机物理内存。读不到就返回 None，自动档退回完整，避免误关问答。"""
    try:
        return _physical_memory_bytes()
    except Exception:
        return None


def _physical_memory_bytes() -> int | None:
    if sys.platform == "win32":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            total = int(stat.ullTotalPhys)
            return total or None
        return None
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def process_rss_bytes() -> int | None:
    """当前进程工作集。界面上用来对照「切档之后占用有没有下来」。"""
    try:
        return _process_rss_bytes()
    except Exception:
        return None


def _process_rss_bytes() -> int | None:
    if sys.platform != "win32":
        try:
            with open("/proc/self/statm", encoding="utf-8") as fh:
                pages = int(fh.read().split()[1])
            return pages * 4096
        except (OSError, IndexError, ValueError):
            return None

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    kernel32 = ctypes.WinDLL("kernel32")
    psapi = ctypes.WinDLL("psapi")
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    handle = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        return None
    return int(counters.WorkingSetSize) or None


def resolve_mode(request: str, ram_bytes: int | None) -> str:
    mode = (request or "auto").strip().lower()
    if mode == "lite":
        return "lite"
    if mode == "full":
        return "full"
    if ram_bytes is None:
        return "full"
    if ram_bytes <= LITE_RAM_BYTES:
        return "lite"
    return "full"


def _configured_request() -> tuple[str, str, bool]:
    """(请求档位, 来源, 是否被环境变量锁住)。

    环境变量优先于界面上保存的选择。没设环境变量时读 data/runtime_profile.json。
    测试进程不读这份文件，避免本机选了轻量之后把离线测试的问答接口关掉。
    """
    raw = (getattr(settings, "runtime_profile", "") or "").strip().lower()
    if raw in _MODES:
        return raw, "env", True
    if "pytest" not in sys.modules:
        try:
            data = json.loads(profile_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            saved = str(data.get("mode") or "").strip().lower()
            if saved in _MODES:
                return saved, "user", False
    return "auto", "auto", False


def _ensure_base() -> dict[str, float | int]:
    global _base
    if _base is None:
        _base = {
            "cache_memory_max_mb": float(settings.cache_memory_max_mb),
            "query_workers": int(settings.query_workers),
        }
    return _base


def _summary(resolved: str, ram_bytes: int | None, locked: bool) -> str:
    ram = human_bytes(ram_bytes) if ram_bytes else "未知"
    if resolved == "lite":
        text = (
            f"本机内存 {ram}。轻量档：问答和自动盯盘已暂停，"
            f"内存里的行情缓存上限 {LITE_CACHE_MB:.0f}MB，查询同时最多 {LITE_WORKERS} 路。"
            "传统查询、导出、证书和墙钟照常。"
            "切回「完整」后问答和盯盘马上恢复；要让已经驻留的程序让出内存，退出助手再打开一次。"
        )
    elif ram_bytes is None:
        text = "没读到本机内存，按完整档运行。问答、盯盘和传统查询都可用。"
    else:
        cap = float(_base["cache_memory_max_mb"]) if _base else float(settings.cache_memory_max_mb)
        workers = int(_base["query_workers"]) if _base else int(settings.query_workers)
        text = (
            f"本机内存 {ram}。完整档：问答和盯盘都开着，"
            f"内存缓存上限 {cap:.0f}MB，查询同时最多 {workers} 路。"
        )
    if locked:
        text += " 档位由环境变量 RUNTIME_PROFILE 固定，界面上改不了。"
    return text


def public() -> dict[str, Any]:
    ram = _state.get("ram_bytes")
    if not isinstance(ram, int):
        ram = physical_memory_bytes()
    rss = process_rss_bytes()
    resolved = str(_state["resolved"])
    return {
        "request": _state["request"],
        "resolved": resolved,
        "source": _state["source"],
        "locked": bool(_state["locked"]),
        "agents_enabled": resolved != "lite",
        "ram_bytes": ram,
        "ram_human": human_bytes(ram) if ram else "未知",
        "process_bytes": rss,
        "process_human": human_bytes(rss) if rss else "未知",
        "cache_memory_max_mb": float(settings.cache_memory_max_mb),
        "query_workers": int(settings.query_workers),
        "threshold_gib": 8,
        "summary": _summary(resolved, ram if isinstance(ram, int) else None, bool(_state["locked"])),
    }


def apply(request: str, *, persist: bool = False, source: str = "user") -> dict[str, Any]:
    """切档位。lite 会立刻缩缓存、降并发、停掉后续盯盘；full 把上限恢复成启动时的配置。"""
    mode = (request or "").strip().lower()
    if mode not in _MODES:
        raise ValueError("mode 须为 auto、full 或 lite")
    base = _ensure_base()
    ram = physical_memory_bytes()
    resolved = resolve_mode(mode, ram)
    previous = _state["resolved"]
    _state["request"] = mode
    _state["resolved"] = resolved
    _state["source"] = source
    _state["locked"] = source == "env"
    _state["ram_bytes"] = ram

    if resolved == "lite":
        settings.cache_memory_max_mb = min(float(base["cache_memory_max_mb"]), LITE_CACHE_MB)
        settings.query_workers = min(int(base["query_workers"]), LITE_WORKERS)
    else:
        settings.cache_memory_max_mb = float(base["cache_memory_max_mb"])
        settings.query_workers = int(base["query_workers"])

    if previous != resolved:
        from src.platform import cache_memory
        from src.market.client import reset_http_pool

        if resolved == "lite":
            # 磁盘缓存还在，下次查询会按新上限重新装进内存。
            cache_memory.clear()
            gc.collect()
        reset_http_pool()

    if persist and source == "user":
        path = profile_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps({"mode": mode}, ensure_ascii=False))
    return public()


def apply_startup() -> dict[str, Any]:
    """进程起来时套用环境变量或上次在界面里保存的档位。测试里不调用。"""
    if "pytest" in sys.modules:
        return public()
    request, source, _locked = _configured_request()
    return apply(request, persist=False, source=source)


def reset_for_tests() -> None:
    """把被轻量档改过的上限放回去，并忘掉启动时拍下的基线。"""
    global _base
    if _base is not None:
        settings.cache_memory_max_mb = float(_base["cache_memory_max_mb"])
        settings.query_workers = int(_base["query_workers"])
    _base = None
    _state.update(
        {
            "request": "auto",
            "resolved": "full",
            "source": "default",
            "locked": False,
            "ram_bytes": None,
        }
    )
