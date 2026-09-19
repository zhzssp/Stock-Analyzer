from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db import Base
from src.models import Artifact, User
from src.platform.storage import (
    cache_file,
    clear_cache,
    enforce_cache_budget,
    human_bytes,
    prune_artifacts,
    trim_alerts_log,
    trim_bars,
    write_cache_json,
)


def test_cache_file_strips_path_bits(tmp_path: Path):
    path = cache_file("../secret", cache_dir=tmp_path)
    assert path.parent == tmp_path
    assert path.name == "secret.json"


def test_trim_bars_keeps_last_window():
    rows = [{"d": str(i), "c": i} for i in range(20)]
    out = trim_bars(rows, max_bars=5)
    assert [r["c"] for r in out] == [15, 16, 17, 18, 19]


def test_human_bytes():
    assert human_bytes(512) == "512 B"
    assert human_bytes(2048).endswith("KB")
    assert "MB" in human_bytes(2 * 1024 * 1024)


def test_cache_budget_evicts_old_bars_before_lists(tmp_path: Path):
    old = tmp_path / "bars_600038_n.json"
    old.write_text('{"x": "' + ("a" * 80) + '"}', encoding="utf-8")
    newer = tmp_path / "bars_000001_n.json"
    newer.write_text('{"x": "' + ("b" * 80) + '"}', encoding="utf-8")
    kept = tmp_path / "list_hs.json"
    kept.write_text('{"x": "' + ("c" * 80) + '"}', encoding="utf-8")
    stamp = 1_700_000_000
    old.touch()
    newer.touch()
    kept.touch()
    import os

    os.utime(old, (stamp, stamp))
    os.utime(newer, (stamp + 10, stamp + 10))
    os.utime(kept, (stamp - 100, stamp - 100))
    result = enforce_cache_budget(cache_dir=tmp_path, max_bytes=200)
    assert old.exists() is False
    assert kept.exists() is True
    assert result["deleted"] == ["bars_600038_n"]


def test_clear_cache_only_json(tmp_path: Path):
    (tmp_path / "bars_1.json").write_text("[]", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("keep", encoding="utf-8")
    result = clear_cache(cache_dir=tmp_path)
    assert result["deleted"] == 1
    assert (tmp_path / "notes.txt").exists()
    assert not (tmp_path / "bars_1.json").exists()


def test_write_cache_overwrites_same_key(tmp_path: Path):
    write_cache_json("bars_600038_n", [{"d": "1"}], cache_dir=tmp_path, max_bytes=10_000)
    write_cache_json("bars_600038_n", [{"d": "2"}, {"d": "3"}], cache_dir=tmp_path, max_bytes=10_000)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert '"3"' in files[0].read_text(encoding="utf-8")


def test_trim_alerts_log_keeps_tail(tmp_path: Path):
    path = tmp_path / "alerts.log"
    path.write_text("old\n" + ("x" * 4000) + "\nkeep-me\n", encoding="utf-8")
    result = trim_alerts_log(path=path, max_bytes=200)
    assert result["trimmed"] is True
    text = path.read_text(encoding="utf-8")
    assert "keep-me" in text
    assert "old\n" not in text


def _session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_prune_artifacts_keeps_newest(tmp_path: Path):
    db = _session(tmp_path)
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    folder = tmp_path / "arts"
    folder.mkdir()
    ids = []
    base = datetime(2026, 1, 1)
    for i in range(5):
        path = folder / f"{i}.xlsx"
        path.write_bytes(b"PK")
        rec = Artifact(
            user_id=user.id,
            path=str(path),
            filename=path.name,
            pool_name="t",
            created_at=base + timedelta(days=i),
        )
        db.add(rec)
        db.commit()
        ids.append(rec.id)
    result = prune_artifacts(db, user_id=user.id, keep=2, artifact_dir=folder)
    assert result["removed"] == 3
    left = db.query(Artifact).order_by(Artifact.id).all()
    assert [r.filename for r in left] == ["3.xlsx", "4.xlsx"]
    assert not (folder / "0.xlsx").exists()
    assert (folder / "4.xlsx").exists()
    db.close()
