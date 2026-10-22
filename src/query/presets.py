"""列预设：看盘（少打麦蕊）/ 研究（查询与导出的默认核心列）/ 自定义。"""

from __future__ import annotations

from src.query.registry import registry

PRESET_WATCH = "watch"
PRESET_RESEARCH = "research"
PRESET_CUSTOM = "custom"

# 仅行情块 + 基础列；全量更新时才拉财务/股东等。
WATCH_KEYS: tuple[str, ...] = (
    "name",
    "code",
    "price",
    "pct",
    "pe",
    "pb",
)

# 前端查询与沪深全市场导出的默认列，顺序与工作台表头一致。
RESEARCH_KEYS: tuple[str, ...] = (
    "name",
    "code",
    "price",
    "pct",
    "industry",
    "concept",
    "business",
    "holders",
    "zgb",
    "ltgb",
    "mgwfplr",
    "mgjzc",
    "eps",
    "pe",
    "gross",
    "net",
    "pb",
)


def _valid(keys: tuple[str, ...] | list[str]) -> list[str]:
    allowed = {s.key for s in registry.all()}
    out: list[str] = []
    for k in keys:
        if k in allowed and k not in out:
            out.append(k)
    return out


def keys_for_preset(preset: str) -> list[str]:
    name = (preset or "").strip().lower()
    if name == PRESET_RESEARCH:
        return _valid(RESEARCH_KEYS)
    if name == PRESET_WATCH:
        return _valid(WATCH_KEYS)
    return _valid(RESEARCH_KEYS)


def catalog() -> list[dict]:
    return [
        {
            "id": PRESET_WATCH,
            "label": "看盘",
            "description": "名称、代码、现价与估值；刷新只更新行情，省麦蕊次数。",
            "fields": list(WATCH_KEYS),
        },
        {
            "id": PRESET_RESEARCH,
            "label": "研究",
            "description": "行业、概念、主营、前十大流通股东与财务估值；不含资金流和底顶。",
            "fields": list(RESEARCH_KEYS),
        },
        {
            "id": PRESET_CUSTOM,
            "label": "自定义",
            "description": "在下方勾选列；保存后按自定义清单查询。",
            "fields": [],
        },
    ]


def default_for_new_user() -> tuple[str, list[str]]:
    """查询结果的默认勾选：十七个研究列。看盘仍可在列设置里另选。"""
    return PRESET_RESEARCH, keys_for_preset(PRESET_RESEARCH)
