from __future__ import annotations

import json
from pathlib import Path

from src.config import settings

# Official names only. enabled=false until S0 writes data/index_probe.json.
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
    enabled = bool(rec.get("enabled")) and bool(rec.get("codes"))
    return {
        "code": code,
        "enabled": enabled,
        "reason": rec.get("reason") or ("等待正式 licence 实测成份接口" if not enabled else ""),
        "count": len(rec.get("codes") or []),
        "codes": list(rec.get("codes") or []),
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
