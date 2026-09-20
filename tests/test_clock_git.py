import shutil
import subprocess
from pathlib import Path

import pytest

from src.config import ROOT, settings
from src.market.clock_git import flush, git_root_for
from src.platform.tray import start_tray

git = shutil.which("git")


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )


def test_start_tray_skipped_under_pytest():
    assert start_tray("http://127.0.0.1:8765/") is None


def test_refuse_product_repo():
    assert git_root_for(ROOT) is None
    assert git_root_for(settings.data_dir) is None
    info = flush(clock_dir=ROOT)
    assert info["enabled"] is False
    assert info["committed"] is False


@pytest.mark.skipif(not git, reason="git not installed")
def test_flush_commits_only_quotes_and_universe(tmp_path: Path):
    repo = tmp_path / "clock-repo"
    repo.mkdir()
    _run_git(repo, "init")
    (repo / "secrets.env").write_text("KEY=1\n", encoding="utf-8")
    quotes = repo / "quotes" / "2026-09-18"
    quotes.mkdir(parents=True)
    (quotes / "1005.json").write_text('{"schema":1,"quotes":{"600038":{"p":26.0}}}\n', encoding="utf-8")
    universe = repo / "universe"
    universe.mkdir()
    (universe / "hanish.json").write_text('{"codes":["600038"]}\n', encoding="utf-8")
    if git_root_for(repo) is None:
        pytest.skip("tmp_path is inside the product tree; clock git refuses that")
    info = flush(clock_dir=repo, timeout=10)
    assert info["enabled"] is True, info
    assert info["ok"] is True, info
    assert info["committed"] is True, info
    names = _run_git(repo, "show", "--name-only", "--pretty=format:").stdout
    assert "quotes/" in names
    assert "universe/" in names
    assert "secrets.env" not in names
    again = flush(clock_dir=repo, timeout=10)
    assert again["ok"] is True
    assert again["committed"] is False
