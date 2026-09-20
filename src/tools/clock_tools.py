from __future__ import annotations

from src.market.clock import clock_series, configured_clock_dir, load_slot, status
from src.tools.base import ToolContext, ToolResult, ToolSpec
from src.tools.registry import registry


def clock_slot(args: dict, ctx: ToolContext) -> ToolResult:
    root = configured_clock_dir()
    if root is None:
        return ToolResult(ok=False, error="未选择账本文件夹", source="clock_slot", cite="墙钟档案")
    as_of = str(args.get("as_of") or "").strip()
    if not as_of:
        snap = status(root)
        as_of = str(snap.get("as_of") or "")
    if not as_of:
        return ToolResult(ok=False, error="还没有档口", source="clock_slot", cite="墙钟档案")
    payload = load_slot(root, as_of)
    if not payload:
        return ToolResult(ok=True, data={"as_of": as_of, "missing": True, "quotes": {}}, source="clock_slot", cite=f"墙钟 {as_of} 空洞")
    quotes = payload.get("quotes") or {}
    compact = {code: {"p": row.get("p"), "pc": row.get("pc")} for code, row in list(quotes.items())[:80]}
    return ToolResult(
        ok=True,
        data={"as_of": payload.get("as_of"), "count": len(quotes), "quotes": compact, "writers": payload.get("writers") or []},
        source="clock_slot",
        cite=f"墙钟档 {payload.get('as_of')}",
        as_of=str(payload.get("as_of") or ""),
    )


def clock_series_tool(args: dict, ctx: ToolContext) -> ToolResult:
    root = configured_clock_dir()
    if root is None:
        return ToolResult(ok=False, error="未选择账本文件夹", source="clock_series", cite="墙钟档案")
    code = str(args.get("code") or "").split(".")[0]
    start = str(args.get("start") or "")
    end = str(args.get("end") or "")
    if not code or not start or not end:
        return ToolResult(ok=False, error="需要 code、start、end", source="clock_series", cite="墙钟档案")
    points = clock_series(root, code, start, end)
    compact = [{"as_of": p.get("as_of"), "p": p.get("p"), "pc": p.get("pc")} for p in points]
    return ToolResult(
        ok=True,
        data={"code": code, "count": len(compact), "points": compact},
        source="clock_series",
        cite=f"墙钟序列 {code} {start}~{end}",
    )


registry.register(
    ToolSpec(
        "clock_slot",
        "墙钟某一档",
        "warehouse",
        "读取共享账本里某一墙钟档的现价横切面。没有该档则 missing。引用必须带 as_of。",
        {"type": "object", "properties": {"as_of": {"type": "string", "description": "档位时间，缺省为最新档"}}},
    ),
    clock_slot,
)
registry.register(
    ToolSpec(
        "clock_series",
        "墙钟时段序列",
        "warehouse",
        "读取某只股票在起止时间内的档口现价序列，缺档跳过不插值。引用必须带时间区间。",
        {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
            },
            "required": ["code", "start", "end"],
        },
    ),
    clock_series_tool,
)
