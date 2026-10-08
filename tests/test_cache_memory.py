"""C 期：缓存读的内存层。

只验一件事：语义一点没变，但第二次以后不再读盘。
「文件被外部改了 / 删了 / 被预算淘汰了」这三类失效是最容易出 bug 的地方，逐条锁死。
"""

import json
import threading

import pytest

from src.config import settings
from src.platform import cache_memory
from src.platform.storage import clear_cache, read_cache_json, write_cache_json


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "cache_memory_enabled", True)
    cache_memory.clear()
    yield
    cache_memory.clear()


def test_second_read_comes_from_memory():
    write_cache_json("k1", {"a": 1})
    first = read_cache_json("k1")

    hits_before = cache_memory.stats()["hits"]
    second = read_cache_json("k1")

    assert first == second == {"a": 1}
    assert cache_memory.stats()["hits"] == hits_before + 1
    # 同一份对象 = 没有重新解析一遍 JSON
    assert second is first


def test_write_replaces_cached_value():
    """写盘后必须立刻读到新值——否则就是「改了数据界面不变」这种最难查的 bug。"""
    write_cache_json("k2", {"v": 1})
    assert read_cache_json("k2")["v"] == 1

    write_cache_json("k2", {"value": 2})
    assert read_cache_json("k2")["value"] == 2


def test_external_edit_is_detected():
    write_cache_json("k3", {"v": 1})
    assert read_cache_json("k3")["v"] == 1

    (settings.cache_dir / "k3.json").write_text(json.dumps({"v": 999}), encoding="utf-8")

    assert read_cache_json("k3")["v"] == 999


def test_deleted_file_does_not_resurrect():
    write_cache_json("k4", {"v": 1})
    assert read_cache_json("k4") is not None

    (settings.cache_dir / "k4.json").unlink()

    assert read_cache_json("k4") is None
    assert cache_memory.stats()["entries"] == 0


def test_missing_file_returns_none():
    assert read_cache_json("never_written") is None


def test_clear_cache_clears_memory():
    write_cache_json("k5", {"v": 1})
    read_cache_json("k5")
    assert cache_memory.stats()["entries"] >= 1

    clear_cache()

    assert cache_memory.stats()["entries"] == 0


def test_budget_pressure_evicts(monkeypatch):
    monkeypatch.setattr(settings, "cache_memory_max_mb", 0.001)  # ~1 KB
    cache_memory.clear()
    for i in range(30):
        write_cache_json(f"big{i}", {"pad": "x" * 200})
        read_cache_json(f"big{i}")

    st = cache_memory.stats()
    assert st["entries"] < 30
    assert st["bytes"] <= st["budget_bytes"]


def test_disabled_falls_back_to_disk(monkeypatch):
    monkeypatch.setattr(settings, "cache_memory_enabled", False)
    cache_memory.clear()

    write_cache_json("k6", {"v": 1})
    hits_before = cache_memory.stats()["hits"]
    assert read_cache_json("k6") == {"v": 1}
    assert read_cache_json("k6") == {"v": 1}
    # 关掉后一次都不该命中，但仍然要读到正确内容
    assert cache_memory.stats()["hits"] == hits_before
    assert cache_memory.stats()["entries"] == 0


def test_slow_cache_ttl_hit_uses_memory():
    """慢字段是这条链路的最大受益者：监控每 5 分钟都要读一遍。"""
    from src.market.slow_cache import read_fresh, write

    write("slow_t1", {"x": 1})
    first = read_fresh("slow_t1", 60)

    hits_before = cache_memory.stats()["hits"]
    second = read_fresh("slow_t1", 60)

    assert first == second == {"x": 1}
    assert cache_memory.stats()["hits"] == hits_before + 1


def test_concurrent_read_is_safe():
    """真实场景是「一个写、多个读」：4 个查询线程同时读同一份 bars / 慢字段缓存。

    这里不并发写同一个 key——那是写-写竞态，磁盘本来就没保证，不属于本层该解决的事。
    """
    for i in range(5):
        write_cache_json(f"t{i}", {"i": i})

    errors: list[BaseException] = []

    def worker(idx: int) -> None:
        try:
            got = read_cache_json(f"t{idx % 5}")
            assert isinstance(got, dict), got
            assert got["i"] == idx % 5
        except BaseException as exc:  # noqa: BLE001 - 收集起来统一断言
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors[:3]
