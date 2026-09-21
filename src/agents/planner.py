from __future__ import annotations

import json
from typing import Any

from src.agents.llm import chat_completions, chat_completions_stream, llm_available, llm_supports_tools
from src.agents.policy import load_policy, research_hints
from src.tools.registry import registry
from src.tools.resolve import mentioned, watch_instruments
from src.tools.table_parse import looks_like_table


BOTTOM_HINTS = ("离底", "底部", "目标卖价", "顶底", "17年")
QUOTE_HINTS = ("现价", "最新价", "涨跌", "行情", "多少钱", "市盈", "pe", "PE")
HOLDER_HINTS = ("股东", "十大")
FINANCE_HINTS = ("财务", "研发", "净利率", "毛利率", "每股", "净资产", "未分配", "股本", "收益")
COMPANY_HINTS = ("主营", "行业", "概念", "做什么", "经营", "申万", "板块")
FUND_HINTS = ("基金", "汇金", "持仓", "ETF", "投行")
FUTURES_HINTS = ("期货", "原油", "铜价", "生猪", "大宗")
EXPORT_HINTS = ("出口", "海外占比", "外市场")
EXCEL_HINTS = ("excel", "Excel", "导出", "档案", "上周", "上次", "历史表", "对照", "那张表")
DIFF_HINTS = ("变化", "变动", "对比", "差异", "diff")
TABLE_HINTS = ("自选表", "整表", "查表", "自选现在")
PASTE_HINTS = ("粘贴", "这张表", "这份表", "上传的", "附件")
WAREHOUSE_HINTS = ("仓库", "日线", "K线", "k线", "历史行情", "历史数据", "缓存")
API_HINTS = ("接口", "实时", "实盘", "查一下", "按代码")
ACTION_HINTS = ("该不该", "减仓", "买入", "买区", "决策卡", "成本", "作废", "持有逻辑")
REVIEW_HINTS = ("复盘", "次日", "假信号", "规则有效", "同向", "反向")
RULE_HINTS = ("监控规则", "监控需求", "盯盘规则", "我的规则", "守则")
RESEARCH_HINTS = research_hints()


def _has(text: str, keys: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(k.lower() in low or k in text for k in keys)


def _allowed(ctx) -> set[str] | None:
    if ctx.allowed_tools is None:
        return None
    return set(ctx.allowed_tools)


def _codes_from_obs(observations: list[dict] | None) -> list[str]:
    codes: list[str] = []
    for obs in observations or []:
        if not obs.get("ok"):
            continue
        data = obs.get("data")
        if isinstance(data, dict):
            for item in data.get("codes") or []:
                if item and item not in codes:
                    codes.append(str(item))
            for row in data.get("rows") or []:
                token = row.get("code") or row.get("code_full") or row.get("code6")
                if token and token not in codes:
                    codes.append(str(token))
        elif isinstance(data, list):
            for row in data:
                if isinstance(row, dict):
                    token = row.get("code") or row.get("code_full")
                    if token and token not in codes:
                        codes.append(str(token))
    return codes


def _history_text(ctx) -> str:
    return " ".join(str(m.get("content") or "") for m in (getattr(ctx, "history", None) or []))


# market_fetch(resource=…) 与专用 Tool 功能重叠；同一轮只保留专用 Tool。
_FETCH_DEDICATED = {
    "quote": "quote",
    "holders": "holders_flow",
    "finance": "finance_snapshot",
    "capital_flow": "capital_flow",
    "events": "corp_events",
}


def _resolve_fetch_resource(
    question: str,
    *,
    wants_warehouse: bool,
    wants_holders: bool,
    wants_finance: bool,
    wants_flow: bool,
    wants_events: bool,
    wants_quote: bool,
    codes: list[str],
    wants_table: bool,
    wants_api: bool,
) -> str | None:
    if not (wants_api or (codes and wants_quote and not wants_table)):
        return None
    if wants_warehouse and _has(question, ("日线", "K线", "k线", "历史行情")):
        return "history"
    if wants_holders:
        return "holders"
    if wants_finance:
        return "finance"
    if wants_flow:
        return "capital_flow"
    if wants_events:
        return "events"
    return "quote"


def _dedicated_covers_fetch(resource: str, flags: dict[str, bool]) -> bool:
    tool = _FETCH_DEDICATED.get(resource)
    if not tool:
        return False
    mapping = {
        "quote": "wants_quote",
        "holders": "wants_holders",
        "finance": "wants_finance",
        "capital_flow": "wants_flow",
        "events": "wants_events",
    }
    return bool(flags.get(mapping.get(resource, "")))


def heuristic_plan(question: str, called: set[str], ctx, observations: list[dict] | None = None) -> list[dict]:
    extras = watch_instruments(ctx)
    insts = mentioned(question + " " + _history_text(ctx), ctx.market, extras)
    codes = [i.code_full for i in insts] or _codes_from_obs(observations)
    payload = {"question": question, "codes": codes} if codes else {"question": question}
    has_paste = bool(ctx.attachments) or looks_like_table(question)

    wants_quote = _has(question, QUOTE_HINTS)
    wants_holders = _has(question, HOLDER_HINTS)
    wants_finance = _has(question, FINANCE_HINTS)
    wants_company = _has(question, COMPANY_HINTS)
    wants_excel = _has(question, EXCEL_HINTS)
    wants_diff = _has(question, DIFF_HINTS)
    wants_table = _has(question, TABLE_HINTS)
    wants_bottom = _has(question, BOTTOM_HINTS)
    wants_flow = _has(question, ("资金", "净流入", "主力"))
    wants_events = _has(question, ("分红", "增发", "解禁", "事件"))
    wants_paste = has_paste or _has(question, PASTE_HINTS)
    wants_warehouse = _has(question, WAREHOUSE_HINTS)
    wants_api = _has(question, API_HINTS)
    wants_research = _has(question, research_hints())
    wants_funds = _has(question, FUND_HINTS)
    wants_futures = _has(question, FUTURES_HINTS)
    wants_export = _has(question, EXPORT_HINTS)
    wants_action = _has(question, ACTION_HINTS)
    wants_review = _has(question, REVIEW_HINTS)
    wants_rules = _has(question, RULE_HINTS)

    if not any(
        (
            wants_quote,
            wants_holders,
            wants_finance,
            wants_company,
            wants_excel,
            wants_diff,
            wants_table,
            wants_bottom,
            wants_flow,
            wants_events,
            wants_paste,
            wants_warehouse,
            wants_api,
            wants_research,
            wants_funds,
            wants_futures,
            wants_export,
            wants_action,
            wants_review,
            wants_rules,
        )
    ):
        if insts:
            wants_quote = True
            wants_company = True
        elif has_paste:
            wants_paste = True
        elif wants_research:
            pass
        else:
            wants_table = True

    calls: list[dict] = []
    allow = _allowed(ctx)

    def add(tool_id: str, args: dict | None = None) -> None:
        if allow is not None and tool_id not in allow:
            return
        if tool_id in called:
            return
        if any(c["id"] == tool_id for c in calls):
            return
        calls.append({"id": tool_id, "args": args or payload})

    if wants_research:
        add("universe")
        add("quote")
        add("company_profile")
        add("capital_flow")
        add("watch_card")
        add("watch_rules")
    if wants_action:
        add("watch_card")
        add("watch_rules")
    if wants_rules:
        add("watch_rules")
    if wants_review:
        add("watch_review")
    if wants_paste:
        add("excel_parse", {"question": question})
    if wants_warehouse:
        kind = "bars" if _has(question, ("日线", "K线", "k线", "历史行情")) else "list"
        add("warehouse_get", {**payload, "kind": kind, "limit": 30})
    fetch_flags = {
        "wants_quote": wants_quote,
        "wants_holders": wants_holders,
        "wants_finance": wants_finance,
        "wants_flow": wants_flow,
        "wants_events": wants_events,
    }
    fetch_resource = _resolve_fetch_resource(
        question,
        wants_warehouse=wants_warehouse,
        wants_holders=wants_holders,
        wants_finance=wants_finance,
        wants_flow=wants_flow,
        wants_events=wants_events,
        wants_quote=wants_quote,
        codes=codes,
        wants_table=wants_table,
        wants_api=wants_api,
    )
    if fetch_resource and not _dedicated_covers_fetch(fetch_resource, fetch_flags):
        add("market_fetch", {**payload, "resource": fetch_resource})
    if wants_quote:
        add("quote")
    if wants_holders:
        add("holders_flow")
    if wants_finance:
        add("finance_snapshot")
    if wants_company:
        add("company_profile")
        add("taxonomy_lookup")
    if wants_funds:
        add("fund_holding")
    if wants_futures:
        add("futures_map")
    if wants_export:
        add("export_share")
    if wants_bottom:
        add("bottom")
    if wants_flow:
        add("capital_flow")
    if wants_events:
        add("corp_events")
    if wants_table:
        add("query_run")
    if wants_excel or wants_diff:
        if "excel_list" not in called:
            add("excel_list", {"limit": 8})
        elif wants_diff and "excel_diff" not in called:
            add("excel_diff", {})
        elif "excel_read" not in called:
            add("excel_read", {})
    if "excel_parse" in called and codes and "quote" not in called and "market_fetch" not in called:
        add("quote", {**payload})
    return calls


def _note_llm_error(ctx, message: str | None) -> None:
    if ctx is not None and message and not getattr(ctx, "llm_notice", None):
        ctx.llm_notice = message


def _prepend_llm_notice(ctx, text: str) -> str:
    notice = getattr(ctx, "llm_notice", None) if ctx else None
    if not notice:
        return text
    return f"⚠️ {notice}\n\n{text}"


def llm_plan(question: str, observations: list[dict], called: set[str], ctx) -> list[dict] | None:
    if not llm_available() or not llm_supports_tools():
        return None
    allow = _allowed(ctx)
    tools = [
        s
        for s in registry.schemas_for_llm()
        if s["function"]["name"] not in called and (allow is None or s["function"]["name"] in allow)
    ]
    if not tools:
        return []
    extra = ""
    if ctx.attachments:
        extra = f"\n用户附带了 {len(ctx.attachments)} 个表格/文件，优先调用 excel_parse。"
    from src.agents.user_context import format_monitor_prompt

    rules = format_monitor_prompt(getattr(ctx, "db", None), getattr(ctx, "user_id", None))
    if rules:
        extra = extra + "\n" + rules
    messages = [
        {
            "role": "system",
            "content": (load_policy(getattr(ctx, "agent_name", None) or "analyst").plan_prompt + extra),
        },
    ]
    for turn in (getattr(ctx, "history", None) or [])[-6:]:
        role = turn.get("role") or "user"
        if role not in {"user", "assistant", "system"}:
            role = "user"
        messages.append({"role": role, "content": turn.get("content") or ""})
    messages.append({"role": "user", "content": question})
    if observations:
        messages.append({"role": "assistant", "content": "已取得 Tool 结果：" + json.dumps(observations, ensure_ascii=False)[:4000]})
    result = chat_completions(messages, tools=tools)
    if result.error:
        _note_llm_error(ctx, result.error)
        return None
    msg = result.message
    if msg is None:
        return None
    raw = msg.get("tool_calls") or []
    calls = []
    for item in raw:
        fn = item.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        if allow is not None and name not in allow:
            continue
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {"question": question}
        calls.append({"id": name, "args": args})
    return calls


def plan(question: str, observations: list[dict], ctx) -> list[dict]:
    called = {str(o.get("id")) for o in observations}
    llm_calls = llm_plan(question, observations, called, ctx)
    if llm_calls is not None:
        return llm_calls
    return heuristic_plan(question, called, ctx, observations)


def _cites(observations: list[dict]) -> list[dict]:
    cites = []
    seen = set()
    for obs in observations:
        key = obs.get("cite") or obs.get("source")
        if key and key not in seen:
            seen.add(key)
            cites.append({"cite": key, "source": obs.get("source"), "ok": obs.get("ok")})
    return cites


def write_answer(question: str, observations: list[dict], agent: str = "analyst", ctx=None) -> tuple[str, list[dict]]:
    cites = _cites(observations)
    if not observations:
        return "没有调用到可用 Tool，也没有现成数字可报。请点名自选里的股票，或先导出一张表。", cites
    drafted = _draft_lines(observations)
    if llm_available():
        prose = _llm_write(question, drafted, agent, ctx)
        if prose:
            return _prepend_llm_notice(ctx, prose), cites
    body = "\n".join(drafted) if drafted else "Tool 已执行，但没有可展示的字段。"
    return _prepend_llm_notice(ctx, body), cites


def write_answer_iter(question: str, observations: list[dict], agent: str = "analyst", ctx=None):
    cites = _cites(observations)
    if not observations:
        yield "没有调用到可用 Tool，也没有现成数字可报。请点名自选里的股票，或先导出一张表。", cites
        return
    drafted = _draft_lines(observations)
    fallback = "\n".join(drafted) if drafted else "Tool 已执行，但没有可展示的字段。"
    prompt = _write_prompt(agent, ctx)
    if llm_available():
        acc = []
        for chunk in chat_completions_stream(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": question + "\n\n已取到：\n" + "\n".join(drafted)},
            ],
            on_error=lambda msg: _note_llm_error(ctx, msg),
        ):
            acc.append(chunk)
            yield chunk, cites
        if acc and "".join(acc).strip():
            return
        prose = _llm_write(question, drafted, agent, ctx)
        if prose:
            yield _prepend_llm_notice(ctx, prose), cites
            return
    yield _prepend_llm_notice(ctx, fallback), cites


def _write_prompt(agent: str, ctx=None) -> str:
    prompt = load_policy(agent).write_prompt
    if ctx is None:
        return prompt
    from src.agents.user_context import format_monitor_prompt

    extra = format_monitor_prompt(getattr(ctx, "db", None), getattr(ctx, "user_id", None))
    return prompt + ("\n" + extra if extra else "")


def _llm_write(question: str, drafted: list[str], agent: str = "analyst", ctx=None) -> str | None:
    result = chat_completions(
        [
            {"role": "system", "content": _write_prompt(agent, ctx)},
            {"role": "user", "content": question + "\n\n已取到：\n" + "\n".join(drafted)},
        ]
    )
    if result.error:
        _note_llm_error(ctx, result.error)
        return None
    msg = result.message
    if not msg:
        return None
    return msg.get("content")


def _draft_lines(observations: list[dict]) -> list[str]:
    lines = []

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
                    f"七大板块 {row.get('sector') or '无数据'}；申万一级 {row.get('sw_l1') or '无数据'}；"
                    f"2026概念 {row.get('hot_concepts') or '无'}；"
                    f"概念 {row.get('concept') or '无数据'}；主营 {row.get('business') or '无数据'}。"
                )
        elif tool == "fund_holding" and isinstance(data, list):
            for row in data:
                hits = row.get("watch_hits") or []
                names = "、".join(h.get("name") for h in hits if h.get("name")) or "未命中白名单"
                lines.append(f"{row.get('name')} 活跃资金：{names}。")
        elif tool == "futures_map":
            lines.append("关联期货仅有品种映射，尚未接入行情，不编价格。")
        elif tool == "export_share" and isinstance(data, list):
            for row in data:
                lines.append(
                    f"{row.get('name')} 出口占比 {row.get('export_pct') or '无数据'}，"
                    f"外市场占比 {row.get('overseas_pct') or '无数据'}。"
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
        elif tool == "watch_card" and isinstance(data, list):
            for row in data:
                if not row.get("filled"):
                    lines.append(f"{row.get('name')} 未填决策卡，监控仍用统计底 / 默认目标卖价。")
                    continue
                bits = []
                if row.get("group"):
                    bits.append(f"分组 {row.get('group')}")
                if row.get("thesis"):
                    bits.append(f"逻辑 {row.get('thesis')}")
                if row.get("buy_low") is not None or row.get("buy_high") is not None:
                    bits.append(f"买区 {row.get('buy_low') or '—'}–{row.get('buy_high') or '—'}")
                if row.get("reduce_price") is not None:
                    bits.append(f"减仓 {row.get('reduce_price')}")
                if row.get("cost") is not None:
                    bits.append(f"成本 {row.get('cost')}")
                if row.get("invalid_if"):
                    bits.append(f"作废条件 {row.get('invalid_if')}")
                lines.append(f"{row.get('name')} 决策卡：{'；'.join(bits) or '已填但无数字'}。")
        elif tool == "watch_review" and isinstance(data, dict):
            counts = data.get("counts") or {}
            bits = [f"{k} {v}" for k, v in counts.items() if v]
            lines.append("次日复盘计数：" + ("，".join(bits) or "还没有打标。"))
            for row in (data.get("done") or data.get("items") or [])[:6]:
                ret = row.get("review_return_pct")
                ret_s = f"{ret:+.2f}%" if isinstance(ret, (int, float)) else "—"
                lines.append(
                    f"{row.get('name') or row.get('code6')} {row.get('job_key')} "
                    f"{row.get('review_label') or row.get('review_status')} 次日 {ret_s}。"
                )
        elif tool == "watch_rules" and isinstance(data, list):
            if not data:
                lines.append("还没有已开启的监控规则。")
            for row in data:
                scan = "自动扫描" if row.get("scan") else "仅问答"
                bits = [scan]
                if row.get("summary"):
                    bits.append(str(row["summary"]))
                if row.get("definition"):
                    bits.append("定义 " + str(row["definition"]))
                if row.get("need"):
                    bits.append("需求 " + str(row["need"]))
                lines.append(f"{row.get('name')}：{'；'.join(bits)}。")
        elif tool == "bottom" and isinstance(data, list):
            for row in data:
                if row.get("low_long") is None:
                    lines.append(f"{row.get('name')}：{row.get('note') or '无日线，不能算底/顶'}。")
                    continue
                lines.append(
                    f"{row.get('name')} 现价 {row.get('price')}，近1年底 {row.get('low1y')}，"
                    f"长窗底 {row.get('low_long')}，顶 {row.get('high')}，离底 {row.get('off_low')}%，"
                    f"目标卖价 {row.get('target')}（{row.get('note')}）。"
                )
        elif tool == "capital_flow" and isinstance(data, list):
            for row in data:
                lines.append(f"{row.get('name')} 最新净流入 {row.get('latest_net')}，近窗均值 {row.get('mean_net')}。")
        elif tool == "corp_events" and isinstance(data, list):
            for row in data:
                bits = []
                for key, label in (("dividends", "分红"), ("seo", "增发"), ("unlock", "解禁")):
                    items = row.get(key) or []
                    if items:
                        bits.append(f"{label}{len(items)}条")
                ann = row.get("announcements") or []
                if ann:
                    bits.append(f"公告{len(ann)}条")
                qa = row.get("interactive_qa") or []
                if qa:
                    bits.append(f"问董秘{len(qa)}条")
                lines.append(f"{row.get('name')} 事件：{'，'.join(bits) or '近期无分红/增发/解禁'}。")
        elif tool == "corp_disclosure" and isinstance(data, list):
            for row in data:
                ann = row.get("announcements") or []
                qa = row.get("interactive_qa") or []
                titles = [x.get("title") for x in ann if x.get("title")]
                lines.append(f"{row.get('name')} 公告 {len(ann)} 条" + (f"：{'；'.join(titles[:2])}" if titles else "") + f"；问董秘 {len(qa)} 条。")
        elif tool == "limit_review" and isinstance(data, list):
            for row in data:
                perf = (row.get("limit_perf") or [{}])[0] if row.get("limit_perf") else {}
                auc = (row.get("auction") or [{}])[0] if row.get("auction") else {}
                lines.append(
                    f"{row.get('name')} 涨跌停方向 {perf.get('direction')}，竞价开盘量 {auc.get('open_vol')}。"
                )
        elif tool == "market_breadth" and isinstance(data, dict):
            watch = data.get("watch_on_board") or []
            ind = data.get("sector_funds_industry") or []
            top = ind[0].get("name") if ind else ""
            lines.append(f"龙虎榜 {data.get('dragon_tiger_count')} 只；自选上榜 {len(watch)} 只；行业资金首位 {top or '无'}。")
        elif tool == "excel_parse" and isinstance(data, dict):
            codes = "、".join(data.get("codes") or []) or "未识别代码"
            lines.append(
                f"已解析 {data.get('filename') or '粘贴表'}：{data.get('row_count', len(data.get('rows') or []))} 行，代码 {codes}。"
            )
        elif tool == "warehouse_get":
            if isinstance(data, dict) and "artifacts" in data:
                names = "、".join(x.get("filename") or "" for x in (data.get("artifacts") or [])[:5])
                lines.append(f"仓库内 {len(data.get('artifacts') or [])} 份档案、{len(data.get('cache') or [])} 个缓存。{names}")
            elif isinstance(data, list):
                for row in data:
                    lines.append(
                        f"{row.get('name')} 日线 {row.get('count')} 条，{row.get('start')} → {row.get('end')}。"
                    )
            elif isinstance(data, dict) and data.get("filename"):
                lines.append(f"已读档案 {data.get('filename')}，预览 {len(data.get('rows') or [])} 行。")
            elif isinstance(data, dict) and data.get("key"):
                lines.append(f"缓存 {data.get('key')}，{data.get('bytes')} 字节。")
        elif tool == "market_fetch" and isinstance(data, dict):
            src = data.get("source") or ""
            for row in data.get("rows") or []:
                if data.get("resource") == "quote":
                    lines.append(f"{row.get('name')}（{row.get('code')}）现价 {row.get('price')}，来源 {src}。")
                elif data.get("resource") == "history":
                    lines.append(f"{row.get('name')} 接口日线 {row.get('count')} 条，来源 {src}。")
                else:
                    lines.append(f"{row.get('name')} {data.get('resource')} 已返回，来源 {src}。")
        else:
            lines.append(f"{obs.get('cite') or tool} 已返回数据。")
    return lines


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return str(value)
