"""缓存 / 快照的原子写。

原来 write_text 先截断再写，那一瞬间文件是空的，并发的查询线程 json.loads 就失败，
取数结果直接丢掉。这里锁死「替换发生前，目标文件始终是完整的旧内容」。
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import settings
from src.platform.storage import atomic_write_text, read_cache_json, write_cache_json


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    yield


def test_target_file_holds_old_content_until_replace(monkeypatch):
    """原子性的精确验证：replace 之前，读到的必须还是旧内容。"""
    path = settings.cache_dir / "atomic.json"
    path.write_text('{"v": 1}', encoding="utf-8")

    seen: dict = {}
    real_replace = os.replace

    def slow_replace(src, dst):
        seen["tmp_exists"] = Path(src).exists()
        seen["target_during"] = Path(dst).read_text(encoding="utf-8")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", slow_replace)
    atomic_write_text(path, '{"v": 2}')

    assert seen["tmp_exists"] is True
    assert seen["target_during"] == '{"v": 1}'
    assert json.loads(path.read_text(encoding="utf-8"))["v"] == 2


def test_no_temp_file_left_behind():
    write_cache_json("atomic1", {"v": 1})
    leftovers = [p.name for p in settings.cache_dir.iterdir() if p.suffix == ".tmp" or ".tmp." in p.name]
    assert leftovers == []


def test_write_cache_json_roundtrip():
    write_cache_json("atomic2", {"v": 42, "list": [1, 2, 3]})
    assert read_cache_json("atomic2") == {"v": 42, "list": [1, 2, 3]}


def test_falls_back_when_replace_fails(monkeypatch):
    """Windows 上目标被别的进程读着时 replace 会失败：这时也不能把内容写丢。"""
    path = settings.cache_dir / "atomic3.json"

    def boom_replace(_src, _dst):
        raise OSError("being used by another process")

    monkeypatch.setattr(os, "replace", boom_replace)
    atomic_write_text(path, '{"v": 9}')

    assert json.loads(path.read_text(encoding="utf-8"))["v"] == 9


def test_snapshot_write_is_atomic(tmp_path, monkeypatch):
    """表级快照同样是整表覆盖，读的人不能读到半张表。"""
    from src.query.snapshot import load_table_snapshot, save_table_snapshot

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    calls: list[str] = []
    real_replace = os.replace

    def spy_replace(src, dst):
        calls.append(str(dst))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    save_table_snapshot(
        1,
        pool="watch",
        field_keys=["price"],
        codes=["600519"],
        rows=[{"code6": "600519", "price": 10}],
        clock={},
        refresh_mode="cache",
    )

    assert any("user_1.json" in c for c in calls)
    snap = load_table_snapshot(1)
    assert snap["pool"] == "watch"
    assert snap["rows"][0]["price"] == 10
