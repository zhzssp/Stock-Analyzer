"""查询链路实测。

分两层，默认只跑免费的那一层：

    python scripts/bench_query.py              # 0 次请求：缓存读、连通性
    python scripts/bench_query.py --live       # 小额现网 A/B（约 200~300 次请求）

现网部分刻意用 N=3、每组跑两轮取第二轮：
轮一是预热（首次建连 / 首次拉日线），轮二才是稳定态。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.platform import cache_memory
from src.platform.storage import read_cache_json

REPORT_PATH = settings.data_dir / "bench_report.json"
# 这几只在 data/cache 里已有日线缓存，避免「首次拉日线」污染 A/B 对比
LIVE_CODES = [("600519.SH", "贵州茅台"), ("000001.SZ", "平安银行"), ("300274.SZ", "阳光电源")]


def banner(text: str) -> None:
    print(f"\n=== {text} ===")


def bench_cache_read(rounds: int = 20) -> dict:
    """零成本：内存层开关对读盘的影响。用的是本机真实缓存文件。"""
    keys = sorted(p.stem for p in settings.cache_dir.glob("*.json"))
    if not keys:
        return {"skipped": "data/cache 里没有缓存文件"}
    total_bytes = sum(p.stat().st_size for p in settings.cache_dir.glob("*.json"))
    out = {"files": len(keys), "bytes": total_bytes, "rounds": rounds, "runs": {}}
    for flag in (False, True):
        settings.cache_memory_enabled = flag
        cache_memory.clear()
        t0 = time.perf_counter()
        for _ in range(rounds):
            for key in keys:
                read_cache_json(key)
        sec = time.perf_counter() - t0
        out["runs"]["memory_on" if flag else "memory_off"] = {
            "sec": round(sec, 4),
            "reads": len(keys) * rounds,
            "stats": cache_memory.stats(),
        }
    settings.cache_memory_enabled = True
    cache_memory.clear()
    return out


def bench_cache_read_concurrent(threads: int = 4, rounds: int = 5) -> dict:
    """零成本：并发读会不会把 mtime 指纹打乱。

    命中时要 os.utime，而 utime 会改 mtime——并发的另一个线程如果正好在
    「utime 之后、指纹更新之前」做 stat，就会误判成文件被改过。
    """
    import threading

    keys = sorted(p.stem for p in settings.cache_dir.glob("*.json"))
    if not keys:
        return {"skipped": "data/cache 里没有缓存文件"}
    settings.cache_memory_enabled = True
    cache_memory.clear()
    for key in keys:
        read_cache_json(key)  # 预热：全部填进内存
    before = cache_memory.stats()

    def worker() -> None:
        for _ in range(rounds):
            for key in keys:
                read_cache_json(key)

    pool = [threading.Thread(target=worker) for _ in range(threads)]
    t0 = time.perf_counter()
    for t in pool:
        t.start()
    for t in pool:
        t.join()
    sec = time.perf_counter() - t0
    after = cache_memory.stats()
    return {
        "threads": threads,
        "rounds": rounds,
        "reads": len(keys) * rounds * threads,
        "sec": round(sec, 4),
        "before": before,
        "after": after,
        "hit_rate": round(after["hits"] / max(1, after["hits"] + after["misses"]), 3),
    }


def bench_connectivity() -> dict:
    """花 3 次请求（启动探针），确认现网通不通、延迟什么量级。"""
    from src.market.client import MarketClient, reset_http_pool

    reset_http_pool()
    t0 = time.perf_counter()
    try:
        client = MarketClient()
        sec = time.perf_counter() - t0
        return {
            "status": client.status,
            "sample_only": client.sample_only,
            "offline": client.offline,
            "probe_sec": round(sec, 3),
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": f"error: {type(exc).__name__}: {exc}", "probe_sec": round(time.perf_counter() - t0, 3)}


def _install_counter() -> dict:
    from src.market.client import MarketClient

    calls = {"n": 0}
    original = MarketClient._get

    def counted(self, path):
        calls["n"] += 1
        return original(self, path)

    MarketClient._get = counted
    return calls


def bench_live(n: int, groups: list[str]) -> dict:
    """小额现网 A/B。每组跑两轮，只记第二轮（稳定态）。"""
    from src.market.client import MarketClient, reset_http_pool
    from src.market.normalize import normalize_instrument
    from src.query.engine import QueryEngine
    from src.query.registry import registry

    calls = _install_counter()
    reset_http_pool()
    market = MarketClient()
    if market.offline:
        return {"skipped": "离线模式，无法现网实测"}
    if market.sample_only:
        return {"skipped": f"演示证书（status={market.status}），数据不真实"}

    insts = [normalize_instrument(code, name, "") for code, name in LIVE_CODES[:n]]
    keys = registry.default_keys()

    def run_once(mode: str) -> dict:
        calls["n"] = 0
        t0 = time.perf_counter()
        rows = QueryEngine(market).run(insts, keys, refresh_mode=mode, force_live=True)
        return {
            "sec": round(time.perf_counter() - t0, 3),
            "http": calls["n"],
            "rows": len(rows),
            "slow_cache": dict(getattr(market, "slow_cache_stats", {}) or {}),
        }

    def group(label: str, keepalive: bool, task_pool: bool, mode: str) -> dict:
        settings.http_keepalive = keepalive
        settings.query_task_pool = task_pool
        if not keepalive:
            reset_http_pool()
        warm = run_once(mode)
        measured = run_once(mode)
        return {"warm": warm, "measured": measured, "config": {"keepalive": keepalive, "task_pool": task_pool, "mode": mode}}

    out: dict = {"n": len(insts), "codes": [i.code6 for i in insts], "groups": {}}
    if "baseline" in groups:
        out["groups"]["baseline"] = group("baseline", False, False, "full")
    if "a" in groups:
        out["groups"]["A_keepalive"] = group("A", True, False, "full")
    if "ad" in groups:
        out["groups"]["A_D_keepalive_taskpool"] = group("A+D", True, True, "full")

    if "c" in groups:
        # C 的收益是纯 IO，会被网络延迟盖住，只能在 cache 模式下单独 A/B。
        settings.http_keepalive = True
        settings.query_task_pool = True
        runs = {}
        for flag in (False, True):
            settings.cache_memory_enabled = flag
            cache_memory.clear()
            runs["memory_on" if flag else "memory_off"] = {"warm": run_once("cache"), "measured": run_once("cache")}
        settings.cache_memory_enabled = True
        out["groups"]["C_cache"] = {**runs, "memory": cache_memory.stats()}

    settings.http_keepalive = True
    settings.query_task_pool = True
    total = 0
    for g in out["groups"].values():
        for run in g.values():
            if isinstance(run, dict) and "http" in run:
                total += run["http"]
    out["total_http"] = total
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="跑小额现网 A/B（会消耗麦蕊额度）")
    parser.add_argument("--n", type=int, default=3, help="现网实测的自选只数（默认 3）")
    parser.add_argument("--rounds", type=int, default=20, help="缓存读的轮数")
    parser.add_argument("--groups", default="baseline,a,ad,c", help="现网要跑哪几组：baseline,a,ad,c")
    args = parser.parse_args()

    report: dict = {"at": time.strftime("%Y-%m-%d %H:%M:%S")}

    banner("cache read (0 request)")
    report["cache_read"] = bench_cache_read(args.rounds)
    print(json.dumps(report["cache_read"], ensure_ascii=False, indent=2))

    banner("connectivity (3 requests)")
    report["connectivity"] = bench_connectivity()
    print(json.dumps(report["connectivity"], ensure_ascii=False, indent=2))

    if args.live:
        banner(f"live A/B (n={args.n}, about 200-300 requests)")
        report["live"] = bench_live(args.n, [g.strip().lower() for g in args.groups.split(",") if g.strip()])
        print(json.dumps(report["live"], ensure_ascii=False, indent=2))

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
