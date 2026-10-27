"""查询过程中被吞掉的失败，收成前端能直接显示的几条。"""

from __future__ import annotations

import re

_UUID = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)
_CJK = re.compile(r"[\u4e00-\u9fff]")
_STATUS = re.compile(r"(\d{3})\s+([A-Za-z][A-Za-z ]+)")


def friendly_failure(exc: BaseException | str) -> str:
    """技术报错收成「查询失败（原因）」。已经是中文说明的原样保留，证书不出现在句子里。"""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and status >= 400:
        reason = str(getattr(response, "reason_phrase", "") or "").strip()
        detail = f"HTTP {status}" + (f" {reason}" if reason else "")
        return f"查询失败（{detail}）"
    text = " ".join(str(exc or "").split())
    if not text:
        return "查询失败（请求失败）"
    if text.startswith("查询失败（"):
        return _UUID.sub("…", text)
    if _CJK.search(text) and "http://" not in text.lower() and "https://" not in text.lower():
        return text
    found = _STATUS.search(text)
    if found:
        return f"查询失败（HTTP {found.group(1)} {found.group(2).strip()}）"
    cleaned = _UUID.sub("…", text)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"For more information check:.*", "", cleaned)
    cleaned = " ".join(cleaned.split(" "))[:120].strip(" :'\"")
    return f"查询失败（{cleaned or '请求失败'}）"


def issue_level(message: str, default: str = "warn") -> str:
    text = message or ""
    if any(word in text for word in ("额度", "证书", "未配置", "探针")):
        return "error"
    return "error" if default == "error" else "warn"


def summarize_issues(notes: list[dict]) -> list[dict]:
    """同一类失败并成一行：级别、数据块、说明、只数、样例代码。"""
    groups: dict[tuple, dict] = {}
    order: list[tuple] = []
    for raw in notes:
        if not isinstance(raw, dict):
            continue
        block = str(raw.get("block") or "http")
        message = " ".join(str(raw.get("message") or "请求失败").split())[:180] or "请求失败"
        level = issue_level(message, "error" if raw.get("level") == "error" else "warn")
        key = (level, block, message)
        if key not in groups:
            groups[key] = {"level": level, "block": block, "message": message, "count": 0, "codes": []}
            order.append(key)
        group = groups[key]
        code = str(raw.get("code6") or "").strip()
        if code:
            group["count"] += 1
            if code not in group["codes"] and len(group["codes"]) < 8:
                group["codes"].append(code)
        elif group["count"] == 0:
            group["count"] = int(raw.get("count") or 1)
    return [groups[k] for k in order][:12]


def combine_issues(notes: list[dict], early: list[dict] | None = None) -> list[dict]:
    out = summarize_issues(notes)
    seen = {(item["level"], item["block"], item["message"]) for item in out}
    for item in early or []:
        if not isinstance(item, dict) or not item.get("message"):
            continue
        key = (item.get("level") or "warn", item.get("block") or "http", item.get("message"))
        if key in seen:
            continue
        if item.get("block") == "quote" and any(row.get("block") == "quote" for row in out):
            continue
        out.append(
            {
                "level": item.get("level") or "warn",
                "block": item.get("block") or "http",
                "message": item.get("message"),
                "count": int(item.get("count") or 1),
                "codes": list(item.get("codes") or [])[:8],
            }
        )
        seen.add(key)
    return out[:12]
