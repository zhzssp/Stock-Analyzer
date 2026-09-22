"""估算一次「刷新」触发的麦蕊 HTTP 次数（默认列、force_live、冷缓存）。

用法：.venv\\Scripts\\python.exe scripts/count_refresh_http.py
"""
from __future__ import annotations

import math
from unittest.mock import patch

from src.market.client import MarketClient
from src.market.normalize import normalize_instrument
from src.query.engine import QueryEngine
from src.query.registry import registry


def _fake_json(path: str, codes_in_path: str = ""):
    if "ssjy_more" in path:
        parts = path.split("/")[-1].split(",")
        return [{"dm": c, "p": 1.0, "pc": 0.1} for c in parts if c]
    if "ssjy/" in path:
        code = path.rsplit("/", 1)[-1]
        return [{"dm": code, "p": 1.0, "pc": 0.1}]
    if "hsindex" in path:
        return {"p": 3000.0, "pc": 0.1}
    if "history" in path and "transaction" not in path:
        return [{"t": "20260901", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100}]
    if "transaction" in path:
        return [{"t": "20260922", "zmbtdcje": 1, "zmstdcje": 1, "ddx": 0.1}]
    if "hszg/zg" in path:
        return [{"name": "申万-测试行业"}]
    if "gsjj" in path:
        return [{"bscope": "测试", "idea": "概念"}]
    if "flowholder" in path or "topholder" in path or "pershareindex" in path:
        return [{"mgwfplr": 1, "mgjzc": 1, "jbmgsy": 1, "xsmlv": 1, "jlv": 1, "gdmc": "A", "cgbl": 1}]
    if "income" in path or "capital" in path:
        return [{"yffy": 1, "zgb": 1, "ysltag": 1}]
    return {}


def main() -> None:
    calls: list[str] = []

    def counting_get(self, path: str):
        calls.append(path)
        return _fake_json(path, path)

    n = 10
    insts = [
        normalize_instrument(f"{c:06d}.SH" if i % 2 == 0 else f"{c:06d}.SZ", f"T{i}", "SH" if i % 2 == 0 else "SZ")
        for i, c in enumerate(range(600001, 600001 + n))
    ]
    fields = registry.default_keys()

    client = MarketClient.__new__(MarketClient)
    client.offline = False
    client.sample_only = False
    client.status = "live"
    client.licence = "MOCK"
    client._registry = None

    with patch.object(MarketClient, "_get", counting_get):
        with patch.object(MarketClient, "_cache_get", return_value=None):
            with patch.object(MarketClient, "_cache_put", lambda *a, **k: None):
                with patch("src.market.clock.configured_clock_dir", return_value=None):
                    engine = QueryEngine(client)
                    engine.run(insts, fields, force_live=True)
                    board_calls: list[str] = []
                    def board_get(self, path: str):
                        board_calls.append(path)
                        return _fake_json(path)
                    with patch.object(MarketClient, "_get", board_get):
                        client.index_quotes()

    query_http = len(calls)
    board_http = len(board_calls)
    quote_batches = sum(1 for p in calls if "ssjy_more" in p)
    quote_single = sum(1 for p in calls if "/hsrl/ssjy/" in p and "more" not in p)

    print(f"默认列 field 数: {len(fields)}")
    print(f"自选 N={n}, force_live, 无墙钟目录, 冷缓存（无 bars 命中）")
    print(f"  查询 run 麦蕊 HTTP: {query_http}")
    print(f"    其中 ssjy_more 批次数: {quote_batches}, 单只 ssjy 回退: {quote_single}")
    print(f"  顶部指数 board 麦蕊 HTTP: {board_http} (3 个指数，各试路径直到成功)")
    print(f"  一次「刷新」合计（仅麦蕊）: {query_http + board_http}")
    print(f"  公式估算: ceil(N/20) + N*9 ≈ {math.ceil(n/20) + n * 9}（实测 {query_http}）")


if __name__ == "__main__":
    main()
