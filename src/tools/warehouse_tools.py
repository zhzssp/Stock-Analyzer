from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.config import settings
from src.models import Artifact
from src.platform.storage import cache_file, usage
from src.tools.base import ToolContext, ToolResult, ToolSpec
from src.tools.excel_tools import excel_read
from src.tools.registry import registry
from src.tools.resolve import mentioned, resolve_codes, watch_instruments


def _arts(ctx: ToolContext) -> list[Artifact]:
    return (
        ctx.db.query(Artifact)
        .filter_by(user_id=ctx.user_id)
        .order_by(Artifact.id.desc())
        .all()
    )


def _cache_index() -> list[dict]:
    out = []
    if not settings.cache_dir.exists():
        return out
    for path in sorted(settings.cache_dir.glob("*.json")):
        stat = path.stat()
        out.append(
            {
                "key": path.stem,
                "bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            }
        )
    return out


def warehouse_get(args: dict, ctx: ToolContext) -> ToolResult:
    kind = (args.get("kind") or "list").strip().lower()
    extras = watch_instruments(ctx)
    if args.get("codes") or args.get("code"):
        raw = args.get("codes") or [args["code"]]
        insts = resolve_codes(raw, ctx.market, extras)
    else:
        insts = mentioned(args.get("question") or "", ctx.market, extras)

    if kind == "list":
        arts = [
            {
                "id": a.id,
                "filename": a.filename,
                "pool_name": a.pool_name,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "exists": Path(a.path).exists(),
            }
            for a in _arts(ctx)[:20]
        ]
        return ToolResult(
            ok=True,
            data={
                "artifacts": arts,
                "cache": _cache_index(),
                "watch_count": len(extras),
                "storage": usage(),
            },
            source="warehouse_get",
            cite="仓库目录 · warehouse_get",
        )

    if kind in {"artifact", "excel"}:
        return excel_read(args, ctx)

    if kind == "cache":
        key = (args.get("key") or "").strip()
        if not key:
            return ToolResult(ok=True, data=_cache_index(), source="warehouse_get", cite="缓存目录")
        path = cache_file(key)
        if not path.exists():
            return ToolResult(ok=False, error=f"缓存没有 {key}", source="warehouse_get", cite="缓存")
        text = path.read_text(encoding="utf-8")
        preview = text[:4000]
        return ToolResult(
            ok=True,
            data={"key": key, "bytes": path.stat().st_size, "preview": preview, "truncated": len(text) > 4000},
            source="warehouse_get",
            cite=f"缓存 · {key}",
        )

    if kind in {"bars", "history"}:
        if not insts:
            return ToolResult(ok=False, error="请提供 code / codes，或在问题里点名股票", source="warehouse_get", cite="日线仓库")
        limit = int(args.get("limit") or 40)
        start = args.get("start")
        end = args.get("end")
        rows = []
        for inst in insts[:8]:
            bars = ctx.market.history(inst, start=start, end=end, limit=limit)
            rows.append(
                {
                    "name": inst.name,
                    "code": inst.code_full,
                    "count": len(bars),
                    "start": bars[0].get("d") if bars else None,
                    "end": bars[-1].get("d") if bars else None,
                    "bars": bars,
                    "source": "offline" if ctx.market.offline else "live-or-cache",
                }
            )
        return ToolResult(ok=True, data=rows, source="warehouse_get", cite="日线仓库 · history")

    return ToolResult(
        ok=False,
        error="kind 只能是 list / artifact / cache / bars",
        source="warehouse_get",
        cite="仓库",
    )


registry.register(
    ToolSpec(
        "warehouse_get",
        "仓库历史",
        "artifact",
        "从本机仓库取历史：导出档案、行情缓存、日线。kind=list|artifact|cache|bars",
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["list", "artifact", "cache", "bars", "history"]},
                "code": {"type": "string"},
                "codes": {"type": "array", "items": {"type": "string"}},
                "start": {"type": "string", "description": "YYYY-MM-DD 或 YYYYMMDD"},
                "end": {"type": "string"},
                "limit": {"type": "integer"},
                "id": {"type": "integer"},
                "filename": {"type": "string"},
                "key": {"type": "string", "description": "缓存文件名（不含 .json）"},
                "question": {"type": "string"},
            },
        },
    ),
    warehouse_get,
)
