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
            "corp_disclosure",
            "limit_review",
            "market_breadth",
            "web_finance_search",
            "policy_news",
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
            "corp_disclosure",
            "limit_review",
            "market_breadth",
            "bottom",
            "excel_list",
            "market_fetch",
            "warehouse_get",
            "web_finance_search",
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


# 输出守门：这些是明确的买卖措辞。问答路径只查这一列，不把 YAML 里的「荐股」当子串，
# 否则「不荐股」也会被误伤。前面紧挨着「不」的（如「不建议买入」）跳过。
ADVICE_WORDS = (
    "建议买入", "建议卖出", "推荐买入", "推荐卖出",
    "可以买入", "可以卖出", "应该买入", "应该卖出",
    "不该买入", "不该卖出",
    "可以加仓", "建议加仓", "可以满仓", "建议满仓", "建议清仓", "应该清仓", "不该清仓",
    "可以减仓", "建议减仓", "应该减仓", "不该减仓",
    "必涨", "稳赚", "包赚", "无风险",
)


def _phrase_hit(body: str, word: str) -> bool:
    start = 0
    while True:
        idx = body.find(word, start)
        if idx < 0:
            return False
        if idx == 0 or body[idx - 1] != "不":
            return True
        start = idx + len(word)


def guard_answer(text: str, forbidden: tuple[str, ...] = ()) -> str:
    """命中明确买卖措辞时追加注记。

    不删内容。问答调用时不要传入 YAML 的 forbidden（「荐股」会命中「不荐股」）。
    """
    body = text or ""
    hits = [w for w in ADVICE_WORDS if _phrase_hit(body, w)]
    hits += [w for w in (forbidden or ()) if w and _phrase_hit(body, w)]
    if not hits:
        return body
    words = "、".join(sorted(set(hits)))
    return f"{body}\n\n⚠️ 注：回答含「{words}」相关表述。本助手不提供买卖建议，以上仅为数据整理。"


@lru_cache(maxsize=8)
def load_policy(name: str) -> AgentPolicy:
    key = (name or "analyst").strip().lower()
    fallback = _FALLBACK.get(key)
    if fallback is None:
        # 以前会静默读 analyst 的配置：agent=reviewer 这类错误完全看不出来
        raise ValueError(f"未知 agent：{name}（可用：{', '.join(sorted(_FALLBACK))}）")
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
