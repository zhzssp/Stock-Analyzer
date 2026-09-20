from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.config import ROOT

POLICY_DIR = ROOT / "config" / "agents"


@dataclass(frozen=True)
class AgentPolicy:
    id: str
    tools: tuple[str, ...]
    max_rounds: int = 3
    inject_watch_hits: bool = False
    inject_today_queue: bool = False
    always_tools: tuple[str, ...] = ()
    research_hints: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    plan_prompt: str = ""
    write_prompt: str = ""


_FALLBACK = {
    "analyst": AgentPolicy(
        id="analyst",
        tools=(
            "excel_parse",
            "warehouse_get",
            "market_fetch",
            "quote",
            "company_profile",
            "holders_flow",
            "finance_snapshot",
            "universe",
            "query_run",
            "excel_list",
            "excel_read",
            "excel_diff",
            "capital_flow",
            "corp_events",
            "bottom",
            "taxonomy_lookup",
            "fund_holding",
            "futures_map",
            "export_share",
            "watch_card",
            "watch_review",
            "watch_rules",
        ),
        rules=("只引用 Tool 数字；禁止荐股。",),
        plan_prompt="你是本机股票分析助手。禁止编造数字，禁止荐股。",
        write_prompt="只用下面 Tool 数字回答，禁止编造。没有的字段直说没有。",
    ),
    "researcher": AgentPolicy(
        id="researcher",
        tools=(
            "universe",
            "quote",
            "company_profile",
            "capital_flow",
            "corp_events",
            "bottom",
            "excel_list",
            "market_fetch",
            "warehouse_get",
            "web_finance_search",
            "futures_quote",
            "futures_map",
            "policy_news",
            "fund_holding",
            "taxonomy_lookup",
            "watch_card",
            "watch_review",
            "watch_rules",
        ),
        inject_watch_hits=True,
        inject_today_queue=True,
        always_tools=("universe",),
        research_hints=("看市场", "趋势", "盘面", "自选相关", "今日市场", "今天市场"),
        rules=("先看今日该看与盯盘命中；未启用 Tool 跳过；禁止荐股。",),
        plan_prompt="你是本机看市场助手。禁止编造新闻或期货价格。",
        write_prompt="按命中规则 / 盘面事实 / 数据缺口组织。禁止编造，禁止荐股。",
    ),
}


def _as_tuple(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(str(x) for x in value if str(x).strip())


def _from_dict(data: dict, fallback: AgentPolicy) -> AgentPolicy:
    return AgentPolicy(
        id=str(data.get("id") or fallback.id),
        tools=_as_tuple(data.get("tools")) or fallback.tools,
        max_rounds=int(data.get("max_rounds") or fallback.max_rounds),
        inject_watch_hits=bool(data.get("inject_watch_hits", fallback.inject_watch_hits)),
        inject_today_queue=bool(data.get("inject_today_queue", fallback.inject_today_queue)),
        always_tools=_as_tuple(data.get("always_tools")) or fallback.always_tools,
        research_hints=_as_tuple(data.get("research_hints")) or fallback.research_hints,
        forbidden=_as_tuple(data.get("forbidden")) or fallback.forbidden,
        rules=_as_tuple(data.get("rules")) or fallback.rules,
        plan_prompt=str(data.get("plan_prompt") or fallback.plan_prompt).strip(),
        write_prompt=str(data.get("write_prompt") or fallback.write_prompt).strip(),
    )


@lru_cache(maxsize=8)
def load_policy(name: str) -> AgentPolicy:
    key = (name or "analyst").strip().lower()
    fallback = _FALLBACK.get(key) or _FALLBACK["analyst"]
    path = POLICY_DIR / f"{fallback.id}.yaml"
    if not path.exists():
        return fallback
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return fallback
    return _from_dict(raw, fallback)


def reload_policies() -> list[str]:
    load_policy.cache_clear()
    from src.agents.reviewer import reload_review_config

    reload_review_config()
    return [load_policy("analyst").id, load_policy("researcher").id]


def tools_for(agent: str) -> list[str]:
    return list(load_policy(agent).tools)


def research_hints() -> tuple[str, ...]:
    return load_policy("researcher").research_hints


def policy_public(name: str) -> dict:
    pol = load_policy(name)
    return {
        "id": pol.id,
        "tools": list(pol.tools),
        "max_rounds": pol.max_rounds,
        "inject_watch_hits": pol.inject_watch_hits,
        "inject_today_queue": pol.inject_today_queue,
        "research_hints": list(pol.research_hints),
        "forbidden": list(pol.forbidden),
        "rules": list(pol.rules),
    }


def policies_public() -> dict[str, dict]:
    return {"analyst": policy_public("analyst"), "researcher": policy_public("researcher")}
