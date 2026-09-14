from __future__ import annotations

import json
from typing import Any

import httpx

from src.config import settings
from src.tools.registry import registry
from src.tools.resolve import mentioned, watch_instruments


BOTTOM_HINTS = ("离底", "底部", "目标卖价", "顶底", "17年")
QUOTE_HINTS = ("现价", "最新价", "涨跌", "行情", "多少钱", "市盈", "pe", "PE")
HOLDER_HINTS = ("股东", "十大")
FINANCE_HINTS = ("财务", "研发", "净利率", "毛利率", "每股", "净资产", "未分配", "股本", "收益")
COMPANY_HINTS = ("主营", "行业", "概念", "做什么", "经营")
EXCEL_HINTS = ("excel", "Excel", "导出", "档案", "上周", "上次", "历史表", "对照", "那张表")
DIFF_HINTS = ("变化", "变动", "对比", "差异", "diff")
TABLE_HINTS = ("自选表", "整表", "查表", "自选现在")


def _has(text: str, keys: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(k.lower() in low or k in text for k in keys)


def heuristic_plan(question: str, called: set[str], ctx) -> list[dict]:
    extras = watch_instruments(ctx)
    insts = mentioned(question, ctx.market, extras)
    codes = [i.code_full for i in insts]
    payload = {"question": question, "codes": codes} if codes else {"question": question}

    wants_quote = _has(question, QUOTE_HINTS)
    wants_holders = _has(question, HOLDER_HINTS)
    wants_finance = _has(question, FINANCE_HINTS)
    wants_company = _has(question, COMPANY_HINTS)
    wants_excel = _has(question, EXCEL_HINTS)
    wants_diff = _has(question, DIFF_HINTS)
    wants_table = _has(question, TABLE_HINTS)

    if not any((wants_quote, wants_holders, wants_finance, wants_company, wants_excel, wants_diff, wants_table)):
        if insts:
            wants_quote = True
            wants_company = True
        else:
            wants_table = True

    calls: list[dict] = []

    def add(tool_id: str, args: dict | None = None) -> None:
        if tool_id in called:
            return
        if any(c["id"] == tool_id for c in calls):
            return
        calls.append({"id": tool_id, "args": args or payload})

    if wants_quote:
        add("quote")
    if wants_holders:
        add("holders_flow")
    if wants_finance:
        add("finance_snapshot")
    if wants_company:
        add("company_profile")
    if wants_table:
        add("query_run")
    if wants_excel or wants_diff:
        if "excel_list" not in called:
            add("excel_list", {"limit": 8})
        elif wants_diff and "excel_diff" not in called:
            add("excel_diff", {})
        elif "excel_read" not in called:
            add("excel_read", {})
    return calls


def llm_available() -> bool:
    return bool(settings.llm_api_key.strip())


def llm_plan(question: str, observations: list[dict], called: set[str]) -> list[dict] | None:
    if not llm_available():
        return None
    tools = [s for s in registry.schemas_for_llm() if s["function"]["name"] not in called]
    if not tools:
        return []
    messages = [
        {
            "role": "system",
            "content": "你是本机股票研究助手。只能通过 Tool 取数，禁止编造价格、财务或离底数字。没有数据就说没有。",
        },
        {"role": "user", "content": question},
    ]
    if observations:
        messages.append({"role": "assistant", "content": "已取得 Tool 结果：" + json.dumps(observations, ensure_ascii=False)[:4000]})
    try:
        resp = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"},
            json={
                "model": settings.llm_model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        raw = msg.get("tool_calls") or []
        calls = []
        for item in raw:
            fn = item.get("function") or {}
            name = fn.get("name")
            if not name:
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"question": question}
            calls.append({"id": name, "args": args})
        return calls
    except Exception:
        return None


def plan(question: str, observations: list[dict], ctx) -> list[dict]:
    called = {str(o.get("id")) for o in observations}
    llm_calls = llm_plan(question, observations, called)
    if llm_calls is not None:
        return llm_calls
    return heuristic_plan(question, called, ctx)


def write_answer(question: str, observations: list[dict]) -> tuple[str, list[dict]]:
    cites = []
    seen = set()
    for obs in observations:
        key = obs.get("cite") or obs.get("source")
        if key and key not in seen:
            seen.add(key)
            cites.append({"cite": key, "source": obs.get("source"), "ok": obs.get("ok")})

    if _has(question, BOTTOM_HINTS):
        lines = [
            "离底%、目标卖价依赖日线回溯（S0 正式 licence 实测后才会接入）。",
            "当前没有底部字段，不能编造数字。下面只给已经取到的现价/财务/股东。",
        ]
    else:
        lines = []

    if not observations:
        return "没有调用到可用 Tool，也没有现成数字可报。请点名自选里的股票，或先导出一张表。", cites

    for obs in observations:
        if not obs.get("ok"):
            lines.append(f"{obs.get('cite') or obs.get('id')}：{obs.get('error') or '失败'}")
            continue
        data = obs.get("data")
        tool = obs.get("id")
        if tool == "quote" and isinstance(data, list):
            for row in data:
                price = _fmt(row.get("price"))
                pct = row.get("pct")
                pct_s = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else "—"
                pe = _fmt(row.get("pe"))
                lines.append(f"{row.get('name')}（{row.get('code')}）现价 {price}，涨跌 {pct_s}，市盈率 {pe}。")
        elif tool == "holders_flow" and isinstance(data, list):
            for row in data:
                holders = row.get("holders") or "暂无股东数据"
                lines.append(f"{row.get('name')} 前十大流通股东：{holders}。")
        elif tool == "finance_snapshot" and isinstance(data, list):
            for row in data:
                bits = []
                mapping = (
                    ("yffy", "研发费用"),
                    ("eps", "每股收益"),
                    ("mgjzc", "每股净资产"),
                    ("mgwfplr", "每股未分配利润"),
                    ("gross", "毛利率"),
                    ("net", "净利率"),
                )
                for key, label in mapping:
                    val = row.get(key)
                    bits.append(f"{label} {val if val is not None else '无数据'}")
                lines.append(f"{row.get('name')} 财务：{'，'.join(bits)}。")
        elif tool == "company_profile" and isinstance(data, list):
            for row in data:
                lines.append(
                    f"{row.get('name')} 所属行业 {row.get('industry') or '无数据'}；"
                    f"概念 {row.get('concept') or '无数据'}；主营 {row.get('business') or '无数据'}。"
                )
        elif tool == "excel_list" and isinstance(data, list):
            if not data:
                lines.append("档案库还是空的。先到传统查询导出一张 Excel。")
            else:
                names = "、".join(x.get("filename") for x in data[:5] if x.get("filename"))
                lines.append(f"最近导出 {len(data)} 份：{names}。")
        elif tool == "excel_read" and isinstance(data, dict):
            rows = data.get("rows") or []
            preview = "、".join(str(r.get("名称") or r.get("代码") or "") for r in rows[:6] if r)
            lines.append(f"已读取 {data.get('filename')}，共预览 {len(rows)} 行：{preview or '空表'}。")
        elif tool == "excel_diff" and isinstance(data, dict):
            n = data.get("change_count", 0)
            col = data.get("column")
            if n == 0:
                lines.append(f"{data.get('a', {}).get('filename')} 与 {data.get('b', {}).get('filename')} 的「{col}」没有差异。")
            else:
                sample = data.get("changes") or []
                bits = [f"{c.get('name') or c.get('code')}：{c.get('before')} → {c.get('after')}" for c in sample[:5]]
                lines.append(f"对照「{col}」有 {n} 处变化。例如：{'；'.join(bits)}")
        elif tool == "query_run" and isinstance(data, dict):
            rows = data.get("rows") or []
            bits = [f"{r.get('name')} { _fmt(r.get('price')) }" for r in rows[:8]]
            lines.append(f"查询引擎返回 {data.get('count')} 只。前几只：{'，'.join(bits)}。")
        elif tool == "universe" and isinstance(data, list):
            lines.append("当前自选：" + "、".join(f"{x.get('name')} {x.get('code')}" for x in data))
        else:
            lines.append(f"{obs.get('cite') or tool} 已返回数据。")

    text = "\n".join(lines) if lines else "Tool 已执行，但没有可展示的字段。"
    return text, cites


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return str(value)
