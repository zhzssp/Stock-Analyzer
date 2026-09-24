"""Live workbench tests that never call /api/agent/*. Writes docs/reports/T-20260921-现网无Agent.md."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "docs" / "报告" / "T-20260921-现网无Agent.md"
BASE = "http://127.0.0.1:8765"
SEED_THESES = (
    "直升机主机厂，现价靠近减仓区，用来验接近减仓提醒",
    "中药主业，买区尚未触及",
    "光伏周期底部附近，用来验接近底部提醒",
)
QUOTE_FIELDS = ["name", "code", "price", "pct", "pe", "pb", "mcap", "fcap", "turnover"]
FULL_FIELDS = QUOTE_FIELDS + [
    "industry",
    "business",
    "holders",
    "top_holders",
    "zgb",
    "ltgb",
    "mgjzc",
    "eps",
    "yffy",
    "gross",
    "net",
    "flow_in",
    "flow_out",
    "flow_net",
    "northbound",
    "low1y",
    "high",
    "off_low",
    "multiple",
    "target",
]
STOCKS = ["000001.SZ", "600519.SH", "600038.SH"]

rows: list[dict[str, Any]] = []


def rec(section: str, name: str, ok: bool, detail: str, extra: Any = None) -> None:
    rows.append(
        {
            "section": section,
            "name": name,
            "ok": ok,
            "detail": detail,
            "extra": extra,
        }
    )
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {section} / {name}: {detail}")


def clip(obj: Any, n: int = 800) -> str:
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
            time.sleep(0.4)
        raise RuntimeError("job timeout")
    return payload


def write_report(started: str, finished: str) -> None:
    passed = sum(1 for r in rows if r["ok"])
    failed = sum(1 for r in rows if not r["ok"])
    lines = [
        "# 现网无 Agent 功能测试",
        "",
        "> 由 `scripts/live_no_agent_test.py` 生成。**不调用** `/api/agent/*`，因此不消耗 DeepSeek 额度。",
        "> 查询 / 导出 / 监控只打麦蕊数据接口。",
        "",
        f"- 开始：{started}",
        f"- 结束：{finished}",
        f"- 合计：{len(rows)} 项 · 通过 {passed} · 失败 {failed}",
        "",
        "## 额度说明",
        "",
        "导出 Excel、查询表、自选、监控、档案对照走 `MarketClient` 与本地文件，代码路径不经过 `src/agents/llm.py` 的 `chat_completions`。",
        "本轮脚本未请求 `/api/agent/chat`。",
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
            lines.append(clip(r["extra"], 2500))
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
        h = health.json() if health.status_code == 200 else {"_http": health.status_code, "text": health.text[:400]}
        m = (h.get("market") or {}) if isinstance(h, dict) else {}
        rec(
            "0 准入",
            "health 现网",
            m.get("status") == "live" and m.get("offline") is False and m.get("sample_only") is False,
            f"status={m.get('status')} offline={m.get('offline')} sample_only={m.get('sample_only')}",
            m,
        )
        llm = ((h.get("agent") or {}).get("llm_status") or {}) if isinstance(h, dict) else {}
        rec(
            "0 准入",
            "模型已配置但本轮不调用",
            bool((h.get("agent") or {}).get("llm")),
            f"available={llm.get('available')} model={llm.get('model')}（脚本禁止打 /api/agent/*）",
            llm,
        )

        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        rec("0 准入", "登录", login.status_code == 200, f"http={login.status_code}")
        if login.status_code != 200:
            write_report(started, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            return 2
        headers = {"Authorization": f"Bearer {login.json()['token']}"}

        watch = client.get("/api/watchlist", headers=headers).json()
        fake = [w["code6"] for w in watch if (w.get("card") or {}).get("thesis") in SEED_THESES]
        rec(
            "A 自选",
            "列表",
            isinstance(watch, list) and len(watch) >= 1,
            f"count={len(watch)} codes={[w.get('code_full') for w in watch[:12]]}",
        )
        rec("A 自选", "样例决策卡已清除", not fake, f"仍带样例文案的代码={fake or '无'}")

        search = client.get("/api/markets/instruments", params={"q": "平安银行", "limit": 10}, headers=headers)
        hits = search.json() if search.status_code == 200 else []
        ping = next((x for x in hits if str(x.get("code6")) == "000001"), None)
        rec(
            "A 自选",
            "搜索平安银行",
            bool(ping),
            f"http={search.status_code} n={len(hits) if isinstance(hits, list) else 0} hit={ping}",
        )

        snapshot = [{"code_full": w["code_full"], "code6": w["code6"], "name": w["name"], "group": w.get("group")} for w in watch]
        added_new = False
        if ping and ping["code6"] not in {w["code6"] for w in watch}:
            add = client.post("/api/watchlist/items", headers=headers, json={"items": [{"code_full": ping["code_full"], "code6": ping["code6"], "name": ping["name"]}]})
            rec("A 自选", "加入平安银行", add.status_code == 200, f"http={add.status_code} body={clip(add.json() if add.status_code==200 else add.text, 400)}")
            added_new = add.status_code == 200
        else:
            rec("A 自选", "加入平安银行", True, "已在自选，跳过新增")

        after = client.get("/api/watchlist", headers=headers).json()
        codes = [w["code6"] for w in after]
        if len(codes) >= 2:
            reordered = list(reversed(codes))
            ord_res = client.put("/api/watchlist/order", headers=headers, json={"codes": reordered})
            now = [w["code6"] for w in ord_res.json()] if ord_res.status_code == 200 else []
            rec("A 自选", "改顺序", now[:2] == reordered[:2], f"http={ord_res.status_code} first={now[:3]}")
            client.put("/api/watchlist/order", headers=headers, json={"codes": codes})
        else:
            rec("A 自选", "改顺序", True, "不足 2 只，跳过")

        target = next((w for w in after if w["code6"] == "600038"), after[0] if after else None)
        if target:
            original_card = dict(target.get("card") or {})
            put = client.put(
                f"/api/watchlist/{target['code6']}/card",
                headers=headers,
                json={"thesis": "live-test-card", "cost": 1.23, "buy_low": 1.0, "buy_high": 2.0, "reduce_price": 3.0},
            )
            got = (put.json().get("card") or {}) if put.status_code == 200 else {}
            rec("A 自选", "写决策卡", got.get("thesis") == "live-test-card" and got.get("cost") == 1.23, f"http={put.status_code} card={clip(got, 400)}")
            restore = {
                "thesis": original_card.get("thesis") or "",
                "cost": original_card.get("cost"),
                "shares": original_card.get("shares"),
                "buy_low": original_card.get("buy_low"),
                "buy_high": original_card.get("buy_high"),
                "reduce_price": original_card.get("reduce_price"),
                "invalid_if": original_card.get("invalid_if") or "",
                "group": target.get("group"),
            }
            client.put(f"/api/watchlist/{target['code6']}/card", headers=headers, json=restore)
        else:
            rec("A 自选", "写决策卡", False, "自选为空")

        if added_new:
            client.put("/api/watchlist", headers=headers, json={"items": snapshot})
            rec("A 自选", "恢复自选快照", True, f"restored={len(snapshot)}")

        board = client.get("/api/markets/board").json()
        items = board.get("items") or []
        pts = [i.get("p") for i in items]
        rec(
            "B 分析表",
            "大盘指数",
            all(i.get("source") == "live" for i in items) and len({p for p in pts if p is not None}) >= 2,
            f"items={[{'code': i.get('code'), 'p': i.get('p'), 'pc': i.get('pc'), 'source': i.get('source')} for i in items]}",
        )

        q = wait_job(
            client,
            headers,
            client.post(
                "/api/query/run",
                headers=headers,
                json={"codes": STOCKS, "fields": FULL_FIELDS, "pool_name": "live-no-agent-full"},
            ).json(),
        )
        qrows = q.get("rows") or []
        prices = [r.get("price") for r in qrows]
        north = [r.get("northbound") for r in qrows]
        flows = [(r.get("name"), r.get("flow_in"), r.get("flow_out"), r.get("flow_net")) for r in qrows]
        rec(
            "B 分析表",
            "三只票现价互异且 live",
            q.get("market", {}).get("status") == "live" and len({p for p in prices if p not in (None, "")}) >= 2,
            f"market={q.get('market')} clock={q.get('clock')} prices={list(zip([r.get('code') for r in qrows], prices))}",
        )
        rec("B 分析表", "北向为空（预期）", all(v in (None, "", "-") for v in north), f"northbound={north}")
        flow_ok = any(a not in (None, "") and b not in (None, "") for _, a, b, _ in flows)
        rec("B 分析表", "资金流向有数", flow_ok, f"flow={flows}")
        rec(
            "B 分析表",
            "股东/财务/底顶抽查",
            bool(qrows) and qrows[0].get("name") and (qrows[0].get("mgjzc") not in (None, "") or qrows[0].get("holders")),
            clip({k: qrows[0].get(k) for k in ["name", "industry", "holders", "mgjzc", "eps", "yffy", "low1y", "high", "target"]}, 1200),
        )
        sample_note = q.get("sample")
        rec("B 分析表", "非离线切片标记", sample_note is False or sample_note in (None, False), f"sample={sample_note} note={q.get('note')}")

        watch_q = wait_job(client, headers, client.post("/api/query/run", headers=headers, json={"pool": "watch", "fields": QUOTE_FIELDS}).json())
        rec(
            "C 股票池",
            "自选查询行数",
            watch_q.get("count") == len(client.get("/api/watchlist", headers=headers).json()),
            f"count={watch_q.get('count')} pool={watch_q.get('pool')}",
        )

        for pid, label, pred in (
            ("index:000001.SH", "上证成份数量级", lambda n: n >= 20),
            ("exchange:sz", "深市列表数量级", lambda n: n >= 500),
            ("board:cy", "创业板列表 300 前缀池", lambda n: n >= 50),
        ):
            r = client.get(f"/api/markets/pools/{pid}/instruments", headers=headers)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"text": r.text[:300]}
            if r.status_code != 200:
                rec("C 股票池", label, False, f"http={r.status_code} body={clip(body, 400)}")
                continue
            items = body.get("items") if isinstance(body, dict) else body
            n = body.get("count") if isinstance(body, dict) else (len(items) if isinstance(items, list) else 0)
            rec(
                "C 股票池",
                label,
                pred(int(n or 0)),
                f"http={r.status_code} n={n} sample={clip(body, 400) if isinstance(body, dict) else clip(items[:3] if isinstance(items, list) else items, 400)}",
            )

        exp1 = wait_job(
            client,
            headers,
            client.post(
                "/api/query/export",
                headers=headers,
                json={"pool": "watch", "fields": QUOTE_FIELDS, "pool_name": "自选"},
            ).json(),
        )
        rec(
            "D 导出档案",
            "第一次导出",
            bool(exp1.get("id") and exp1.get("filename", "").endswith(".xlsx") and exp1.get("download_url")),
            f"id={exp1.get('id')} file={exp1.get('filename')} rows={exp1.get('count')}",
        )
        exp2 = wait_job(
            client,
            headers,
            client.post(
                "/api/query/export",
                headers=headers,
                json={"pool": "watch", "fields": QUOTE_FIELDS, "pool_name": "自选"},
            ).json(),
        )
        rec("D 导出档案", "第二次导出", bool(exp2.get("id") and exp2.get("id") != exp1.get("id")), f"id={exp2.get('id')} file={exp2.get('filename')}")

        if exp2.get("id"):
            prev = client.get(f"/api/artifacts/{exp2['id']}/preview", headers=headers)
            rec("D 导出档案", "档案预览", prev.status_code == 200, f"http={prev.status_code} {clip(prev.json() if prev.status_code==200 else prev.text, 600)}")
        dl = client.get(exp2.get("download_url") or f"/api/artifacts/{exp2.get('id')}/download", headers=headers)
        rec(
            "D 导出档案",
            "下载 xlsx",
            dl.status_code == 200 and (len(dl.content) > 1000 or "sheet" in (dl.headers.get("content-type") or "")),
            f"http={dl.status_code} bytes={len(dl.content)} ctype={dl.headers.get('content-type')}",
        )

        if exp1.get("id") and exp2.get("id"):
            diff = client.post("/api/artifacts/diff", headers=headers, json={"id_a": exp1["id"], "id_b": exp2["id"], "column": "price"})
            rec("D 导出档案", "对照上一份", diff.status_code == 200, f"http={diff.status_code} {clip(diff.json() if diff.status_code==200 else diff.text, 700)}")

        arts = client.get("/api/artifacts", headers=headers)
        rec("D 导出档案", "档案库列表", arts.status_code == 200 and isinstance(arts.json(), list), f"http={arts.status_code} n={len(arts.json()) if arts.status_code==200 else 0}")

        sto = client.get("/api/storage", headers=headers)
        rec("D 导出档案", "本机存储", sto.status_code == 200, clip(sto.json() if sto.status_code == 200 else sto.text, 800))

        jobs = client.get("/api/monitor/jobs", headers=headers)
        jlist = jobs.json() if jobs.status_code == 200 else []
        rec("F 监控", "规则列表", jobs.status_code == 200 and isinstance(jlist, list) and len(jlist) >= 1, f"n={len(jlist) if isinstance(jlist, list) else 0} keys={[j.get('job_key') or j.get('key') for j in (jlist[:12] if isinstance(jlist, list) else [])]}")

        if isinstance(jlist, list) and jlist:
            key = jlist[0].get("job_key") or jlist[0].get("key")
            off = client.post(f"/api/monitor/jobs/{key}/toggle", headers=headers, json={"enabled": False})
            on = client.post(f"/api/monitor/jobs/{key}/toggle", headers=headers, json={"enabled": True})
            rec("F 监控", "开关一条规则", off.status_code == 200 and on.status_code == 200, f"key={key} off={off.status_code} on={on.status_code}")

        one_key = None
        if isinstance(jlist, list):
            for j in jlist:
                if j.get("enabled") or j.get("enabled") == 1:
                    one_key = j.get("job_key") or j.get("key")
                    break
            if not one_key and jlist:
                one_key = jlist[0].get("job_key") or jlist[0].get("key")
        if one_key:
            one = client.post(f"/api/monitor/jobs/{one_key}/run", headers=headers)
            rec("F 监控", "只跑一条", one.status_code == 200, f"key={one_key} http={one.status_code} {clip(one.json() if one.status_code==200 else one.text, 700)}")

        run = client.post("/api/monitor/run", headers=headers)
        rec("F 监控", "立刻跑一轮", run.status_code == 200, f"http={run.status_code} {clip(run.json() if run.status_code==200 else run.text, 800)}")

        alerts = client.get("/api/alerts", headers=headers)
        rec("F 监控", "提醒列表", alerts.status_code == 200, f"http={alerts.status_code} n={len(alerts.json()) if alerts.status_code==200 and isinstance(alerts.json(), list) else 'n/a'} {clip(alerts.json() if alerts.status_code==200 else alerts.text, 600)}")

        rev = client.post("/api/monitor/review/run", headers=headers)
        rec("F 监控", "复盘打标", rev.status_code == 200, f"http={rev.status_code} {clip(rev.json() if rev.status_code==200 else rev.text, 700)}")

        tax = client.get("/api/markets/taxonomy").json()
        rec("G 预期空", "北向口径声明", tax.get("northbound") == "未接入", f"northbound={tax.get('northbound')}")

    except Exception as exc:
        rec("脚本", "未捕获异常", False, repr(exc))
    finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_report(started, finished)
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
