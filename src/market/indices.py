from __future__ import annotations

import json
from pathlib import Path

from src.config import settings

# Official names. Offline uses fixture slices; live probe may replace codes.
CANDIDATE_PATHS = (
    "/hsindex/constituent/{code}",
    "/hsindex/chengfen/{code}",
    "/hsindex/component/{code}",
    "/hsindex/weight/{code}",
    "/hslt/zs/{code}",
)

INDEX_SPECS = [
    {"code": "000001.SH", "label": "上证指数", "market": "sh"},
    {"code": "399001.SZ", "label": "深证成指", "market": "sz"},
    {"code": "899050.BJ", "label": "北证50", "market": "bj"},
    {"code": "000680.SH", "label": "科创综指", "market": "kc"},
    {"code": "399006.SZ", "label": "创业板指", "market": "cy"},
    {"code": "000905.SH", "label": "中证500", "market": "hs"},
    {"code": "000016.SH", "label": "上证50", "market": "sh"},
]


def probe_path() -> Path:
    return settings.data_dir / "index_probe.json"


def load_probe() -> dict:
    path = probe_path()
    if not path.exists():
        return {"sample_only": None, "probed_at": None, "indices": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"sample_only": None, "probed_at": None, "indices": {}}


def index_status(code: str) -> dict:
    rec = (load_probe().get("indices") or {}).get(code) or {}
    if bool(rec.get("enabled")) and rec.get("codes"):
        codes = [str(x) for x in rec["codes"]]
        return {
            "code": code,
            "enabled": True,
            "reason": "",
            "count": len(codes),
            "codes": codes,
            "source": rec.get("source") or "probe",
        }

    offline = settings.mairui_offline or not str(settings.mairui_licence or "").strip()
    if offline:
        from src.market.fixtures import INDEX_CONSTITUENTS

        codes = list(INDEX_CONSTITUENTS.get(code) or [])
        return {
            "code": code,
            "enabled": bool(codes),
            "reason": "" if codes else "离线切片未覆盖该指数",
            "count": len(codes),
            "codes": codes,
            "source": "offline-fixture" if codes else "",
        }

    return {
        "code": code,
        "enabled": False,
        "reason": rec.get("reason") or "等待正式 licence 实测成份接口",
        "count": 0,
        "codes": [],
        "source": rec.get("source") or "",
    }


def all_index_pools() -> list[dict]:
    out = []
    for spec in INDEX_SPECS:
        st = index_status(spec["code"])
        out.append(
            {
                "id": f"index:{spec['code']}",
                "kind": "index",
                "label": spec["label"],
                "code": spec["code"],
                "enabled": st["enabled"],
                "reason": st["reason"],
                "count": st["count"] if st["enabled"] else None,
            }
        )
    return out
