from __future__ import annotations

import json
from typing import Any

from src.query.registry import registry

OPS = ("lte", "gte", "eq")
COMPARES = ("threshold", "card")
CARD_FIELDS = ("buy_low", "buy_high", "reduce_at", "cost", "reduce_for_rule")
SCOPES = ("all", "group", "codes")
SCHEDULES = ("session", "eod")
SEVERITIES = ("watch", "act")
GROUPS = ("自选", "观察", "备选")

TEMPLATE_SPECS: dict[str, dict] = {
    "holders-change": {
        "name": "股东变动",
        "enabled": 1,
        "reason": "",
        "schedule": "eod",
        "severity": "watch",
        "blurb": "十大股东名单相对上次快照有增减。",
        "params": {"mode": "any", "highlight_watch": True, "scope": "all"},
        "schema": [
            {"key": "mode", "label": "触发", "type": "select", "options": [{"id": "any", "label": "任意变动"}, {"id": "watch_only", "label": "仅白名单机构"}]},
            {"key": "highlight_watch", "label": "点名关注机构", "type": "bool"},
            {"key": "scope", "label": "范围", "type": "scope"},
        ],
    },
    "fund-holding": {
        "name": "活跃资金持股",
        "enabled": 1,
        "reason": "",
        "schedule": "eod",
        "severity": "watch",
        "blurb": "基金持股里出现你勾选的关注机构。",
        "params": {"scope": "all"},
        "schema": [{"key": "scope", "label": "范围", "type": "scope"}],
    },
    "capital-flow": {
        "name": "资金异常",
        "enabled": 1,
        "reason": "",
        "schedule": "eod",
        "severity": "watch",
        "blurb": "净流入相对近窗均值偏大。",
        "params": {"mean_multiple": 2, "scope": "all"},
        "schema": [
            {"key": "mean_multiple", "label": "相对均值倍数", "type": "number"},
            {"key": "scope", "label": "范围", "type": "scope"},
        ],
    },
    "corp-events": {
        "name": "分红 / 增发 / 解禁",
        "enabled": 1,
        "reason": "",
        "schedule": "eod",
        "severity": "watch",
        "blurb": "公司事件摘要相对上次快照有变化。",
        "params": {"dividends": True, "seo": True, "unlock": True, "scope": "all"},
        "schema": [
            {"key": "dividends", "label": "分红", "type": "bool"},
            {"key": "seo", "label": "增发", "type": "bool"},
            {"key": "unlock", "label": "解禁", "type": "bool"},
            {"key": "scope", "label": "范围", "type": "scope"},
        ],
    },
    "near-bottom": {
        "name": "接近底部",
        "enabled": 1,
        "reason": "",
        "schedule": "session",
        "severity": "act",
        "blurb": "现价相对长窗底的偏离不超过阈值。",
        "params": {"off_low_max": 8, "scope": "all"},
        "schema": [
            {"key": "off_low_max", "label": "离底%上限", "type": "number"},
            {"key": "scope", "label": "范围", "type": "scope"},
        ],
    },
    "near-target": {
        "name": "接近减仓",
        "enabled": 1,
        "reason": "",
        "schedule": "session",
        "severity": "act",
        "blurb": "现价靠近卡上减仓价；未填则用统计目标卖价。",
        "params": {"within_pct": 5, "scope": "all"},
        "schema": [
            {"key": "within_pct", "label": "距减仓区%上限", "type": "number"},
            {"key": "scope", "label": "范围", "type": "scope"},
        ],
    },
    "futures": {
        "name": "期货联动",
        "enabled": 0,
        "reason": "仅有品种映射，等待期货行情",
        "schedule": "eod",
        "severity": "watch",
        "blurb": "期货价格未接入。",
        "params": {},
        "schema": [],
    },
    "news": {
        "name": "资讯冲击",
        "enabled": 0,
        "reason": "等待授权检索源",
        "schedule": "eod",
        "severity": "watch",
        "blurb": "没有授权检索源。",
        "params": {},
        "schema": [],
    },
    "policy": {
        "name": "产业政策",
        "enabled": 0,
        "reason": "等待资讯 Tool",
        "schedule": "eod",
        "severity": "watch",
        "blurb": "产业政策 Tool 未启用。",
        "params": {},
        "schema": [],
    },
}

JOB_DEFS = [
    {
        "job_key": key,
        "name": spec["name"],
        "enabled": spec["enabled"],
        "reason": spec["reason"],
        "schedule": spec["schedule"],
        "severity": spec["severity"],
        "params": spec["params"],
    }
    for key, spec in TEMPLATE_SPECS.items()
]


def _num(value: Any) -> float | None:
    if value in (None, "", "-", "—", False):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def parse_json(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def merge_params(job_key: str, raw: str | None) -> dict:
    spec = TEMPLATE_SPECS.get(job_key) or {}
    base = dict(spec.get("params") or {})
    extra = parse_json(raw, {})
    if isinstance(extra, dict):
        base.update(extra)
    return base


def metric_specs() -> list[dict]:
    return [
        {
            "key": s.key,
            "label": s.label,
            "group": s.group,
            "alertable": s.alertable,
            "realtime": s.realtime,
        }
        for s in registry.alertable()
        if s.alertable in {"threshold", "card"}
    ]


def _compare(left: float | None, op: str, right: float | None) -> bool:
    if left is None or right is None:
        return False
    if op == "lte":
        return left <= right
    if op == "gte":
        return left >= right
    if op == "eq":
        return left == right
    return False


def in_scope(item, params: dict) -> bool:
    scope = params.get("scope") or "all"
    if isinstance(scope, dict):
        kind = scope.get("type") or "all"
        group = scope.get("group")
        codes = {str(c) for c in (scope.get("codes") or [])}
    else:
        kind = str(scope)
        group = params.get("group")
        codes = {str(c) for c in (params.get("codes") or [])}
    if kind in {"", "all", "watch"}:
        return True
    if kind == "group":
        return (item.group_name or "自选") == (group or "自选")
    if kind == "codes":
        return item.code6 in codes or item.code_full in codes
    return True


def validate_custom_spec(spec: dict) -> dict:
    name = str(spec.get("name") or "").strip() or "自定义规则"
    metric = str(spec.get("metric") or "").strip()
    op = str(spec.get("op") or "lte").strip()
    compare = str(spec.get("compare") or "threshold").strip()
    schedule = str(spec.get("schedule") or "eod").strip()
    severity = str(spec.get("severity") or "watch").strip()
    if op not in OPS:
        raise ValueError("运算符只支持 <= / >= / =")
    if compare not in COMPARES:
        raise ValueError("比较方式只支持阈值或相对决策卡")
    if schedule not in SCHEDULES:
        raise ValueError("扫描时点只支持盘中或日终")
    if severity not in SEVERITIES:
        raise ValueError("严重度只支持观察或行动")
    field = registry.get(metric) if metric in {s.key for s in registry.all()} else None
    if field is None or not field.alertable:
        raise ValueError("指标不在可监控清单里")
    if schedule == "session" and not field.realtime and compare != "card":
        raise ValueError("盘中只能扫实时指标（现价、涨跌、离底、距买区/减仓区）")
    card_field = str(spec.get("card_field") or "").strip()
    if compare == "card":
        if card_field not in CARD_FIELDS:
            raise ValueError("相对决策卡请选择买区低/高、减仓价或成本")
        if metric not in {"price", "pct", "off_low", "vs_cost", "dist_buy", "dist_reduce"}:
            raise ValueError("相对决策卡时左侧请用现价或位置类指标")
    value = spec.get("value")
    if compare == "threshold" and _num(value) is None:
        raise ValueError("阈值规则需要一个数字")
    scope = spec.get("scope") or "all"
    if isinstance(scope, str) and scope not in SCOPES:
        raise ValueError("范围只支持全部自选 / 分组 / 指定代码")
    return {
        "name": name[:64],
        "metric": metric,
        "op": op,
        "compare": compare,
        "card_field": card_field,
        "value": _num(value),
        "scope": scope,
        "schedule": schedule,
        "severity": severity,
        "title_template": str(spec.get("title_template") or "")[:80],
    }


def eval_custom(row: dict, spec: dict) -> tuple[bool, str]:
    metric = spec["metric"]
    left = _num(row.get(metric))
    if spec["compare"] == "card":
        right = _num(row.get(spec["card_field"]))
        if spec["card_field"] == "reduce_for_rule":
            right = _num(row.get("reduce_at"))
            if right is None:
                right = _num(row.get("target"))
        if right is None:
            return False, ""
    else:
        right = _num(spec.get("value"))
    if not _compare(left, spec["op"], right):
        return False, ""
    op_label = {"lte": "≤", "gte": "≥", "eq": "="}[spec["op"]]
    label = next((s.label for s in registry.all() if s.key == metric), metric)
    return True, f"{label} {left} {op_label} {right}"


def eval_near_bottom(row: dict, params: dict) -> tuple[bool, str]:
    off = _num(row.get("off_low"))
    cap = _num(params.get("off_low_max"))
    if cap is None:
        cap = 8
    if off is None or off > cap:
        return False, ""
    return True, f"现价 {row.get('price')}，离长窗底 {off}%（{row.get('low_note') or ''}）"


def eval_near_target(row: dict, params: dict) -> tuple[bool, str]:
    price = _num(row.get("price"))
    reduce_at = _num(row.get("reduce_at"))
    target = _num(row.get("target"))
    level = reduce_at if reduce_at is not None else target
    cap = _num(params.get("within_pct"))
    if cap is None:
        cap = 5
    if price is None or level is None:
        return False, ""
    gap = (level - price) / level * 100
    if gap > cap:
        return False, ""
    src = "卡上减仓价" if reduce_at is not None else "统计目标卖价"
    return True, f"现价 {price}，距{src} {round(gap, 2)}%（{level}）"
