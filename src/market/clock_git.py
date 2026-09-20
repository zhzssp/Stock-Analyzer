from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import ROOT, settings
from src.market.clock import configured_clock_dir

_LOCK = threading.Lock()
_STATUS_NAME = "clock_git_status.json"


def _status_path() -> Path:
    return settings.data_dir / _STATUS_NAME


def _log_path() -> Path:
    folder = settings.data_dir / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "clock-git.log"


def _log(message: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}\n"
    try:
        with _log_path().open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def _read_status() -> dict[str, Any]:
    path = _status_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_status(**fields: Any) -> dict[str, Any]:
    payload = _read_status()
    payload.update(fields)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _status_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return payload


def find_git_root(path: Path) -> Path | None:
    current = path.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def git_root_for(clock_dir: Path | None = None) -> Path | None:
    root = (clock_dir or configured_clock_dir())
    if root is None:
        return None
    try:
        resolved = root.expanduser().resolve()
    except OSError:
        return None
    git_root = find_git_root(resolved)
    if git_root is None:
        return None
    product = ROOT.resolve()
    if git_root == product:
        return None
    try:
        resolved.relative_to(product)
        return None
    except ValueError:
        pass
    return git_root


def _git(git_root: Path, args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(git_root), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def _add_paths(git_root: Path, clock_dir: Path) -> list[str]:
    rel = clock_dir.resolve().relative_to(git_root.resolve())
    quotes = rel / "quotes" if rel.parts else Path("quotes")
    universe = rel / "universe" if rel.parts else Path("universe")
    return [quotes.as_posix(), universe.as_posix()]


def flush(clock_dir: Path | None = None, timeout: float = 10.0) -> dict[str, Any]:
    """Commit quotes/universe if CLOCK_DIR is a dedicated git repo, then push when a remote exists."""
    target = clock_dir or configured_clock_dir()
    info = {
        "ok": False,
        "enabled": False,
        "reason": "",
        "committed": False,
        "pushed": False,
    }
    if target is None:
        info["reason"] = "未选择账本文件夹"
        return info
    git_root = git_root_for(target)
    if git_root is None:
        info["reason"] = "账本目录不是独立 git 仓库（也不会写入产品仓库）"
        return info
    info["enabled"] = True
    try:
        paths = [p for p in _add_paths(git_root, Path(target)) if (git_root / p).exists()]
        if not paths:
            info["ok"] = True
            info["reason"] = "没有 quotes/universe 可提交"
            _write_status(enabled=True, ok=True, last_error="")
            return info
    except ValueError:
        info["reason"] = "账本目录不在该 git 仓库内"
        _write_status(enabled=True, ok=False, last_error=info["reason"])
        return info
    try:
        added = _git(git_root, ["add", "--", *paths], timeout=min(5.0, timeout))
        if added.returncode != 0:
            info["reason"] = (added.stderr or added.stdout or "git add 失败").strip()[:300]
            _log(f"add failed: {info['reason']}")
            _write_status(enabled=True, ok=False, last_error=info["reason"])
            return info
        porcelain = _git(git_root, ["status", "--porcelain", "--", *paths], timeout=min(5.0, timeout))
        pending = (porcelain.stdout or "").strip()
        if pending:
            message = f"clock: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            committed = _git(
                git_root,
                ["-c", "user.name=Stock-Analyzer", "-c", "user.email=clock@local", "-c", "commit.gpgsign=false", "commit", "-m", message, "--", *paths],
                timeout=min(8.0, timeout),
            )
            if committed.returncode != 0:
                info["reason"] = (committed.stderr or committed.stdout or "git commit 失败").strip()[:300]
                _log(f"commit failed: {info['reason']}")
                _write_status(enabled=True, ok=False, last_error=info["reason"])
                return info
            info["committed"] = True
        remotes = _git(git_root, ["remote"], timeout=min(3.0, timeout))
        if (remotes.stdout or "").strip():
            pushed = _git(git_root, ["push"], timeout=timeout)
            if pushed.returncode != 0:
                info["reason"] = (pushed.stderr or pushed.stdout or "git push 失败").strip()[:300]
                _log(f"push failed: {info['reason']}")
                _write_status(enabled=True, ok=False, last_error=info["reason"], last_ok=False)
                return info
            info["pushed"] = True
        info["ok"] = True
        info["reason"] = ""
        _write_status(enabled=True, ok=True, last_error="", last_ok=True)
        if info["committed"] or info["pushed"]:
            _log(f"flush ok committed={info['committed']} pushed={info['pushed']}")
        return info
    except subprocess.TimeoutExpired:
        info["reason"] = "git 超时"
        _log(info["reason"])
        _write_status(enabled=True, ok=False, last_error=info["reason"], last_ok=False)
        return info
    except OSError as exc:
        info["reason"] = str(exc)[:300]
        _log(info["reason"])
        _write_status(enabled=True, ok=False, last_error=info["reason"], last_ok=False)
        return info


def git_status_payload() -> dict[str, Any]:
    target = configured_clock_dir()
    git_root = git_root_for(target) if target is not None else None
    saved = _read_status()
    enabled = git_root is not None
    last_ok = saved.get("last_ok")
    if last_ok is None:
        last_ok = saved.get("ok")
    reason = ""
    if target is None:
        reason = "未选择账本文件夹"
    elif git_root is None:
        reason = "未启用 git 备份"
    elif last_ok is False:
        reason = str(saved.get("last_error") or "档案还没备份到远程，下次打开会再试")
    return {
        "enabled": enabled,
        "ok": last_ok,
        "reason": reason,
        "git_root": str(git_root) if git_root else "",
        "updated_at": saved.get("updated_at") or "",
    }


def schedule_flush(clock_dir: Path | None = None) -> None:
    if "pytest" in os.environ.get("PYTEST_CURRENT_TEST", "") or "pytest" in __import__("sys").modules:
        return
    if git_root_for(clock_dir) is None:
        return

    def worker() -> None:
        if not _LOCK.acquire(blocking=False):
            return
        try:
            flush(clock_dir=clock_dir, timeout=10.0)
        finally:
            _LOCK.release()

    threading.Thread(target=worker, name="clock-git-flush", daemon=True).start()


def main() -> int:
    info = flush(timeout=10.0)
    if info.get("ok") or not info.get("enabled"):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
