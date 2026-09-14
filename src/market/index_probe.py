"""S0 helper: probe 'index -> constituents' endpoints. Never invent constituents."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx

from src.config import settings
from src.market.indices import INDEX_SPECS, probe_path


CANDIDATE_PATHS = (
    "/hsindex/constituent/{code}",
    "/hsindex/chengfen/{code}",
    "/hsindex/component/{code}",
    "/hsindex/weight/{code}",
    "/hslt/zs/{code}",
)


def _url(path: str, licence: str) -> str:
    return f"{settings.mairui_base}{path}/{licence}"


def write_status(payload: dict) -> None:
    path = probe_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_disabled(reason: str, extra: dict | None = None) -> dict:
    indices = {}
    for spec in INDEX_SPECS:
        rec = {"enabled": False, "reason": reason, "codes": [], "source": ""}
        if extra:
            rec.update(extra.get(spec["code"]) or {})
        indices[spec["code"]] = rec
    return {
        "probed_at": datetime.now().isoformat(timespec="seconds"),
        "sample_only": extra.get("sample_only") if extra else None,
        "indices": indices,
        "sszs_reverse_ok": False,
        "constituent_api": None,
        "note": "未证实前不得把交易所全部挂牌当作指数成份。全市场反扫 hscp/sszs 默认不做。",
    }


def probe(licence: str | None = None) -> dict:
    licence = (licence or settings.mairui_licence or settings.demo_licence).strip()
    sample_only = licence == settings.demo_licence
    if settings.mairui_offline and not settings.mairui_licence:
        payload = default_disabled("离线未实测；正式 licence 请跑 scripts/Verify-Index.ps1")
        payload["sample_only"] = True
        write_status(payload)
        return payload

    findings: dict[str, Any] = {"attempts": [], "sszs": None}
    constituent_api = None
    codes_by_index: dict[str, list[str]] = {}

    try:
        with httpx.Client(timeout=20.0) as client:
            for spec in INDEX_SPECS[:3]:
                for tmpl in CANDIDATE_PATHS:
                    path = tmpl.format(code=spec["code"])
                    url = _url(path, licence)
                    try:
                        resp = client.get(url)
                        ok = resp.status_code == 200
                        data = resp.json() if ok else None
                        count = len(data) if isinstance(data, list) else 0
                        findings["attempts"].append({"url": path, "ok": ok, "count": count, "status": resp.status_code})
                        if ok and count >= 10 and not sample_only:
                            constituent_api = path
                            codes = []
                            for row in data:
                                if not isinstance(row, dict):
                                    continue
                                dm = row.get("dm") or row.get("code") or row.get("gpdm") or ""
                                if dm:
                                    codes.append(str(dm))
                            if codes:
                                codes_by_index[spec["code"]] = codes
                    except Exception as exc:
                        findings["attempts"].append({"url": path, "ok": False, "error": str(exc)})

            try:
                sszs = client.get(_url("/hscp/sszs/600038", licence))
                findings["sszs"] = {"ok": sszs.status_code == 200, "count": len(sszs.json()) if sszs.status_code == 200 and isinstance(sszs.json(), list) else 0}
            except Exception as exc:
                findings["sszs"] = {"ok": False, "error": str(exc)}
    except Exception as exc:
        findings["error"] = str(exc)

    reason = "演示 licence 无法验证成份接口" if sample_only else "未找到可用的指数→成份接口"
    extra = {"sample_only": sample_only}
    for code, codes in codes_by_index.items():
        extra[code] = {
            "enabled": True,
            "reason": "",
            "codes": codes,
            "source": constituent_api or "",
        }
    payload = default_disabled(reason, extra)
    payload["sample_only"] = sample_only
    payload["constituent_api"] = constituent_api
    payload["sszs_reverse_ok"] = bool((findings.get("sszs") or {}).get("ok"))
    payload["findings"] = findings
    if sample_only:
        for rec in payload["indices"].values():
            rec["enabled"] = False
            rec["codes"] = []
            rec["reason"] = "演示 licence 无法验证成份接口"
    write_status(payload)
    return payload


if __name__ == "__main__":
    result = probe()
    print(json.dumps({k: result[k] for k in ("probed_at", "sample_only", "constituent_api", "sszs_reverse_ok") if k in result}, ensure_ascii=False, indent=2))
