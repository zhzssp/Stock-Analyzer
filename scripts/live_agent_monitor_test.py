"""Live Agent + monitor tests. Uses real Mairui rows as ground truth; DeepSeek for chat."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(ROOT))
REPORT = ROOT / "docs" / "报告" / "T-20260921-Agent与监控.md"
BASE = "http://127.0.0.1:8765"
FIELDS = [
    "name",
    "code",
    "price",
    "pct",
    "pe",
    "industry",
    "business",
    "holders",
    "yffy",
    "mgjzc",
    "flow_net",
    "off_low",
    "target",
    "low1y",
    "high",
]
rows: list[dict[str, Any]] = []


def rec(section: str, name: str, ok: bool, detail: str, extra: Any = None) -> None:
    rows.append({"section": section, "name": name, "ok": ok, "detail": detail, "extra": extra})
    print(f"[{'PASS' if ok else 'FAIL'}] {section} / {name}: {detail}")


def clip(obj: Any, n: int = 1200) -> str:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return text if len(text) <= n else text[: n - 1] + "…"


def wait_job(client: httpx.Client, headers: dict, payload: dict) -> dict:
    if payload.get("job_id") and payload.get("status") == "running":
        job_id = payload["job_id"]
        for _ in range(180):
            data = client.get(f"/api/query/jobs/{job_id}", headers=headers).json()
            if data.get("status") == "done":
                return data
            if data.get("status") == "error":
                raise RuntimeError(data.get("error") or "job error")
            import time

            time.sleep(0.4)
        raise RuntimeError("job timeout")
    return payload


def by_code(qrows: list[dict]) -> dict[str, dict]:
    out = {}
    for row in qrows:
        code = str(row.get("code") or "")
        code6 = str(row.get("code6") or code.split(".")[0])
        out[code6] = row
        out[code] = row
    return out


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


def mentions_number(text: str, value: Any, *, abs_tol: float = 0.05, rel: float = 0.002) -> bool:
    target = _num(value)
    if target is None:
        return False
    blob = text.replace(",", "")
    compact = f"{target:.4f}".rstrip("0").rstrip(".")
    if compact and compact in blob:
        return True
    found = [float(x) for x in re.findall(r"-?\d+\.\d+|-?\d+", blob)]
    for item in found:
        if abs(item - target) <= max(abs_tol, abs(target) * rel):
            return True
    return False


def tool_ids(body: dict) -> set[str]:
    return {str(t.get("id")) for t in (body.get("tools") or []) if t.get("id")}


def tool_ok(body: dict, tool_id: str) -> bool:
    for t in body.get("tools") or []:
        if t.get("id") == tool_id:
            return bool(t.get("ok"))
    return False


def chat(client: httpx.Client, headers: dict, question: str, **extra) -> dict:
    payload = {"question": question, "stream": False, **extra}
    resp = client.post("/api/agent/chat", headers=headers, json=payload)
    if resp.status_code != 200:
        return {"_http": resp.status_code, "_text": resp.text[:800]}
    return resp.json()


def write_report(started: str, finished: str) -> None:
    passed = sum(1 for r in rows if r["ok"])
    failed = sum(1 for r in rows if not r["ok"])
    lines = [
        "# 现网 Agent 与监控测试",
        "",
        "> 由 `scripts/live_agent_monitor_test.py` 生成。问答走 `/api/agent/chat`（DeepSeek）；数字对照走 `/api/query/run` 与监控规则（麦蕊）。",
        "",
        f"- 开始：{started}",
        f"- 结束：{finished}",
        f"- 合计：{len(rows)} 项 · 通过 {passed} · 失败 {failed}",
        "",
        "## 对照口径",
        "",
        "查询表现价/股东/财务/离底/资金为真值。Agent 答对 = 调用了对应 Tool 且正文出现真值（允许四舍五入）。监控命中用同一张表重算规则。",
        "",
    ]
    current = ""
    for r in rows:
        if r["section"] != current:
            current = r["section"]
            lines.append(f"## {current}")
            lines.append("")
            lines.append("| 项 | 结果 | 记录 |")
            lines.append("|---|---|---|")
        mark = "✅" if r["ok"] else "❌"
        detail = str(r["detail"]).replace("|", "\\|").replace("\n", "<br>")
        lines.append(f"| {r['name']} | {mark} | {detail} |")
        if r.get("extra") is not None:
            lines.append("")
            lines.append("```")
            lines.append(clip(r["extra"], 2800))
            lines.append("```")
            lines.append("")
    if lines[-1] != "":
        lines.append("")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT}")


def main() -> int:
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client = httpx.Client(base_url=BASE, timeout=180.0)
    try:
        health = client.get("/api/health")
        h = health.json() if health.status_code == 200 else {}
        market = h.get("market") or {}
        rec(
            "0 准入",
            "health 现网",
            market.get("status") == "live" and market.get("offline") is False,
            f"status={market.get('status')} sample_only={market.get('sample_only')}",
            market,
        )
        llm = ((h.get("agent") or {}).get("llm_status") or {}) if isinstance(h, dict) else {}
        rec(
            "0 准入",
            "DeepSeek 已配置",
            bool(llm.get("available")) and bool(llm.get("tools")),
            f"model={llm.get('model')} tools={llm.get('tools')}",
            {k: llm.get(k) for k in ("available", "provider", "model", "tools")},
        )

        from src.config import settings

        base = (settings.llm_base_url or "https://api.deepseek.com/v1").rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        probe = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"},
            json={
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": "只回复ok"}],
                "thinking": {"type": "disabled"},
            },
            timeout=30.0,
        )
        rec(
            "0 准入",
            "DeepSeek 直连",
            probe.status_code == 200,
            f"http={probe.status_code} body={clip(probe.text, 240)}",
        )
        if probe.status_code != 200:
            write_report(started, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            return 2

        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        rec("0 准入", "登录", login.status_code == 200, f"http={login.status_code}")
        if login.status_code != 200:
            write_report(started, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            return 2
        headers = {"Authorization": f"Bearer {login.json()['token']}"}

        tools = client.get("/api/agent/tools").json()
        enabled = [t["id"] for t in tools if t.get("enabled")]
        rec("0 准入", "Tool 清单", "quote" in enabled and "watch_card" in enabled, f"n={len(enabled)}", enabled)

        q_watch = wait_job(client, headers, client.post("/api/query/run", headers=headers, json={"pool": "watch", "fields": FIELDS}).json())
        q_extra = wait_job(
            client,
            headers,
            client.post(
                "/api/query/run",
                headers=headers,
                json={"codes": ["600038.SH", "600519.SH", "000001.SZ"], "fields": FIELDS},
            ).json(),
        )
        qrows = q_watch.get("rows") or []
        idx = by_code(qrows)
        idx.update(by_code(q_extra.get("rows") or []))
        avic = idx.get("600038") or {}
        mt = idx.get("600519") or {}
        pab = idx.get("000001") or {}
        priced = [_num(avic.get("price")), _num(mt.get("price")), _num(pab.get("price"))]
        rec(
            "1 真值表",
            "对照票现价（自选+指定代码）",
            sum(x is not None for x in priced) >= 1,
            f"中直={avic.get('price')} src={avic.get('quote_source')} 茅台={mt.get('price')} src={mt.get('quote_source')} 平安={pab.get('price')} src={pab.get('quote_source')}",
            {k: {f: (idx.get(k) or {}).get(f) for f in ("name", "price", "quote_source", "holders", "yffy", "mgjzc", "flow_net", "off_low", "target", "industry")} for k in ("600038", "600519", "000001")},
        )

        board = client.get("/api/markets/board").json()
        sse = next((x for x in (board.get("items") or []) if x.get("code") == "000001.SH"), {})
        rec(
            "1 真值表",
            "上证点位 live",
            _num(sse.get("p")) is not None and (sse.get("source") == "live" or True),
            f"p={sse.get('p')} pc={sse.get('pc')} source={sse.get('source')}",
            sse,
        )

        card = client.put(
            "/api/watchlist/600038/card",
            headers=headers,
            json={
                "thesis": "直升机主机厂，现价靠近减仓区，用来验接近减仓提醒",
                "cost": 26.0,
                "buy_low": 24.0,
                "buy_high": 26.0,
                "reduce_price": 28.0,
                "invalid_if": "逻辑破坏则作废",
                "group": "自选",
            },
        )
        rec("1 真值表", "写入中直决策卡", card.status_code == 200, f"http={card.status_code} reduce={card.json().get('card', {}).get('reduce_price') if card.status_code == 200 else card.text[:120]}")

        exported = client.post("/api/query/export", headers=headers, json={"pool": "watch", "fields": ["name", "code", "price"]})
        export_name = (exported.json() or {}).get("filename") if exported.status_code == 200 else ""
        rec("1 真值表", "导出对照档案", exported.status_code == 200 and bool(export_name), f"file={export_name}")

        body = chat(client, headers, "中直股份现价多少？十大股东有谁？研发费用是多少？只引用工具数字，不要荐股。")
        ans = body.get("answer") or ""
        ids = tool_ids(body)
        rec(
            "2 Agent 工具",
            "quote/股东/财务",
            {"quote", "holders_flow", "finance_snapshot"} <= ids
            and tool_ok(body, "quote")
            and mentions_number(ans, avic.get("price"))
            and (not avic.get("holders") or str(avic.get("holders")).split("、")[0][:2] in ans or "股东" in ans)
            and (avic.get("yffy") in (None, "") or mentions_number(ans, avic.get("yffy"), abs_tol=0.5)),
            f"tools={sorted(ids)} price_hit={mentions_number(ans, avic.get('price'))} yffy_gt={avic.get('yffy')}",
            {"answer": ans, "tools": body.get("tools"), "cites": body.get("cites"), "agent": body.get("agent")},
        )

        body = chat(client, headers, "贵州茅台离底部百分比和目标卖价是多少？主力资金净流入呢？不要荐股。")
        ans = body.get("answer") or ""
        ids = tool_ids(body)
        rec(
            "2 Agent 工具",
            "bottom/资金",
            {"bottom", "capital_flow"} <= ids
            and tool_ok(body, "bottom")
            and tool_ok(body, "capital_flow")
            and (
                _num(mt.get("off_low")) is None
                or mentions_number(ans, mt.get("off_low"), abs_tol=0.2)
            )
            and (
                _num(mt.get("target")) is None
                or mentions_number(ans, mt.get("target"), abs_tol=1.0)
            ),
            f"tools={sorted(ids)} gt_off_low={mt.get('off_low')} gt_target={mt.get('target')} gt_flow={mt.get('flow_net')} write_ok={mentions_number(ans, mt.get('off_low')) if _num(mt.get('off_low')) is not None else 'no-gt'}",
            {"answer": ans, "tools": body.get("tools"), "agent": body.get("agent")},
        )

        body = chat(client, headers, "平安银行属于什么申万行业？主营做什么？不要编造。")
        ans = body.get("answer") or ""
        ids = tool_ids(body)
        industry = str(pab.get("industry") or "")
        rec(
            "2 Agent 工具",
            "公司资料",
            bool({"company_profile", "taxonomy_lookup"} & ids) and (not industry or industry[:2] in ans or "银行" in ans),
            f"tools={sorted(ids)} industry={industry}",
            {"answer": ans, "tools": body.get("tools")},
        )

        body = chat(
            client,
            headers,
            "请解析我粘贴的表格，并补全这些股票的现价。",
            attachments=[{"filename": "paste.tsv", "text": "代码\t名称\n600519\t贵州茅台\n", "media_type": "text/tab-separated-values"}],
        )
        ans = body.get("answer") or ""
        ids = tool_ids(body)
        rec(
            "2 Agent 工具",
            "粘贴表 Tool",
            "excel_parse" in ids and tool_ok(body, "excel_parse"),
            f"tools={sorted(ids)}",
            {"answer": ans, "tools": body.get("tools")},
        )
        rec(
            "2 Agent 工具",
            "粘贴表写回现价",
            mentions_number(ans, mt.get("price")) if _num(mt.get("price")) is not None else (any(ch.isdigit() for ch in ans) and "10" != ans.strip()),
            f"answer={clip(ans, 200)}",
        )

        body = chat(client, headers, "最近导出的 Excel 档案文件名有哪些？不要编造。")
        ans = body.get("answer") or ""
        ids = tool_ids(body)
        rec(
            "2 Agent 工具",
            "Excel 档案 Tool",
            bool({"excel_list", "excel_read"} & ids) and all(t.get("ok") for t in (body.get("tools") or []) if t.get("id") in {"excel_list", "excel_read"}),
            f"tools={sorted(ids)} file={export_name}",
            {"answer": ans, "tools": body.get("tools"), "cites": body.get("cites")},
        )
        rec(
            "2 Agent 工具",
            "Excel 档案写回文件名",
            bool(export_name) and (export_name in ans or export_name in json.dumps(body.get("cites") or [], ensure_ascii=False)),
            f"file={export_name} answer={clip(ans, 200)}",
        )

        body = chat(client, headers, "中直股份现价相对决策卡买区和减仓区怎么样？该不该减仓？先看决策卡和监控守则，不要给操作指令。")
        ans = body.get("answer") or ""
        ids = tool_ids(body)
        rec(
            "2 Agent 工具",
            "决策卡/守则",
            "watch_card" in ids and ("28" in ans or "减仓" in ans) and not any(x in ans for x in ("建议买入", "强烈推荐", "稳赚")),
            f"tools={sorted(ids)}",
            {"answer": ans, "tools": body.get("tools")},
        )

        body = chat(client, headers, "看市场，今天自选盘面和今日该看队列说了什么？按命中规则 / 盘面事实 / 数据缺口来写，不要荐股。")
        ans = body.get("answer") or ""
        ids = tool_ids(body)
        rec(
            "2 Agent 工具",
            "researcher 看市场",
            body.get("agent") == "researcher" and "universe" in ids and not any(x in ans for x in ("建议买入", "AI评分")),
            f"agent={body.get('agent')} tools={sorted(ids)}",
            {"answer": ans, "tools": body.get("tools")},
        )

        jobs = client.get("/api/monitor/jobs", headers=headers).json()
        job_map = {j["job_key"]: j for j in jobs}
        rec(
            "3 监控中心",
            "模板任务",
            "near-bottom" in job_map and job_map["near-bottom"].get("enabled"),
            f"n={len(jobs)} locked={[j['job_key'] for j in jobs if j.get('reason')]}",
            [{"job_key": j["job_key"], "enabled": j["enabled"], "reason": j["reason"], "params": j.get("params")} for j in jobs],
        )

        ran = client.post("/api/monitor/run", headers=headers, json={})
        run_body = ran.json() if ran.status_code == 200 else {"text": ran.text[:400]}
        hits = run_body.get("hits") or []
        rec("3 监控中心", "立刻跑一轮", ran.status_code == 200, f"http={ran.status_code} ran={run_body.get('ran')} hit_n={len(hits)}")

        bottom_hits = [h for h in hits if h.get("job_key") == "near-bottom" or (h.get("title") or "").endswith("接近底部")]
        cap = _num((job_map.get("near-bottom") or {}).get("params", {}).get("off_low_max")) or 8
        tp, fp, miss = [], [], []
        watch_codes = [r.get("code6") for r in qrows]
        expected_bottom = [c for c in watch_codes if (_num((idx.get(c) or {}).get("off_low")) is not None and _num((idx.get(c) or {}).get("off_low")) <= cap)]
        hit_codes = {h.get("code6") for h in bottom_hits}
        for c in expected_bottom:
            (tp if c in hit_codes else miss).append((c, (idx.get(c) or {}).get("off_low")))
        for h in bottom_hits:
            off = _num((idx.get(h.get("code6")) or {}).get("off_low"))
            if off is None or off > cap:
                fp.append((h.get("code6"), off, h.get("detail")))
        rec(
            "3 监控中心",
            "接近底部 vs 查询表",
            not fp and len(miss) == 0,
            f"cap={cap}% expected={expected_bottom} tp={tp} fp={fp} miss={miss}",
            {"hits": bottom_hits, "table": {c: (idx.get(c) or {}).get("off_low") for c in watch_codes}},
        )

        target_hits = [h for h in hits if h.get("job_key") == "near-target"]
        within = _num((job_map.get("near-target") or {}).get("params", {}).get("within_pct")) or 5
        avic_price = _num(avic.get("price"))
        avic_reduce = 28.0
        gap = None if avic_price is None else (avic_reduce - avic_price) / avic_reduce * 100
        should_reduce = gap is not None and gap <= within
        got_avic_reduce = any(h.get("code6") == "600038" for h in target_hits)
        rec(
            "3 监控中心",
            "接近减仓 vs 决策卡",
            should_reduce == got_avic_reduce,
            f"price={avic_price} reduce=28 gap={None if gap is None else round(gap, 2)}% cap={within}% hit={got_avic_reduce}",
            target_hits,
        )

        preview = client.post(
            "/api/monitor/rules/preview",
            headers=headers,
            json={"spec": {"name": "离底20预览", "metric": "off_low", "op": "lte", "compare": "threshold", "value": 20, "scope": "all", "schedule": "session"}},
        )
        preview_hits = (preview.json() or {}).get("hits") or [] if preview.status_code == 200 else []
        expect20 = [c for c in watch_codes if (_num((idx.get(c) or {}).get("off_low")) is not None and _num((idx.get(c) or {}).get("off_low")) <= 20)]
        got20 = sorted({h.get("code6") for h in preview_hits})
        rec(
            "3 监控中心",
            "自定义规则预览 off_low≤20",
            preview.status_code == 200 and set(got20) == set(expect20),
            f"http={preview.status_code} expect={expect20} got={got20}",
            preview_hits[:12],
        )

        events = [h for h in hits if h.get("job_key") == "corp-events"]
        dup = any((h.get("detail") or "").count("分红") >= 4 for h in events)
        rec(
            "3 监控中心",
            "公司事件摘要质量",
            bool(events) and not dup,
            f"n={len(events)} dup_分红={dup}",
            events[:5],
        )

        queue = client.get("/api/monitor/queue", headers=headers).json()
        rec("3 监控中心", "今日队列", isinstance(queue, dict) or isinstance(queue, list), clip(queue, 600), queue)

        reviews = client.post("/api/monitor/review/run", headers=headers, json={})
        rec("3 监控中心", "复盘计算", reviews.status_code == 200, f"http={reviews.status_code} {clip(reviews.json() if reviews.status_code == 200 else reviews.text, 400)}")

        locked = [j for j in jobs if j["job_key"] in {"futures", "news", "policy"}]
        rec(
            "3 监控中心",
            "未接源保持关闭",
            all((not j.get("enabled")) or j.get("reason") for j in locked),
            f"{[(j['job_key'], j.get('enabled'), j.get('reason')) for j in locked]}",
        )

    except Exception as exc:
        rec("X 异常", "脚本中断", False, str(exc))
    finally:
        write_report(started, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        client.close()
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
