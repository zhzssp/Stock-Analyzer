"""三期明确不接的能力：保持灰卡或空列，集中登记原因。"""

from __future__ import annotations

from typing import Any

# 与 R-20260921 U1–U6、P-20260915 对齐；关闭欠账前不要删条目。
PHASE3_GAPS: tuple[dict[str, Any], ...] = (
    {
        "id": "U1",
        "name": "期货行情 / 期货联动",
        "kind": "tool+monitor",
        "status": "placeholder",
        "reason": "麦蕊只有期货分类树，无品种 OHLC；futures_quote 保持关闭，监控灰卡。",
    },
    {
        "id": "U2",
        "name": "Agent 全网资讯检索",
        "kind": "tool",
        "status": "placeholder",
        "reason": "麦蕊无新闻/检索接口；web_finance_search 保持关闭。监控可配白名单 URL，不等于 Agent 检索。",
    },
    {
        "id": "U3",
        "name": "Agent 产业政策检索",
        "kind": "tool",
        "status": "placeholder",
        "reason": "同 U2；policy_news 保持关闭。",
    },
    {
        "id": "U4",
        "name": "监控资讯 / 政策（未配源）",
        "kind": "monitor",
        "status": "gray_until_config",
        "reason": "偏好里未填检索源时资讯冲击 / 产业政策保持灰卡；配源后仅抓白名单。",
    },
    {
        "id": "U5",
        "name": "个股日频北向",
        "kind": "column",
        "status": "empty",
        "reason": "麦蕊无个股每日北向；列 northbound 恒空，禁止用资金流冒充。",
        "field": "northbound",
    },
    {
        "id": "U6",
        "name": "出口 / 海外占比",
        "kind": "tool",
        "status": "manual_table",
        "reason": "麦蕊利润表无出口占比；仅读 data/export_share.csv，无表则空。",
    },
    {
        "id": "P3-1m",
        "name": "1 分钟 K / 订单流",
        "kind": "api",
        "status": "deferred",
        "reason": "hsstock/orderflow 与 Quant Pro 1m 耗次数大，二期刻意未接。",
    },
    {
        "id": "P3-fund",
        "name": "基金 / 可转债档案",
        "kind": "api",
        "status": "deferred",
        "reason": "jj/fd 栏目未纳入查询列；需另开需求。",
    },
)


def gap_catalog() -> list[dict[str, Any]]:
    return [dict(x) for x in PHASE3_GAPS]


def field_unavailable(key: str) -> str | None:
    for item in PHASE3_GAPS:
        if item.get("field") == key:
            return str(item.get("reason") or "")
    return None
