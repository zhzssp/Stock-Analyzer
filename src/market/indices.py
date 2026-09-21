from __future__ import annotations

import json
from pathlib import Path

from src.config import settings

# 官网 hsdata：先 hszg/list（type2=7 指数成分），叶子 code 形如 zhishu_000001，
# 再 hszg/gg/{tree_code} 取成份。hszsdata 只有点位/K 线，没有成份名单。
# 科创综指 000680 不在指数树里（树里只有科创50 zhishu_000688）。
NO_TREE_CODES = frozenset({"000680"})


def index_code6(code: str) -> str:
    return str(code or "").split(".")[0].strip()


def index_tree_code(index_code: str) -> str | None:
    code6 = index_code6(index_code)
    if not code6 or code6 in NO_TREE_CODES:
        return None
    return f"zhishu_{code6}"


def constituent_paths(index_code: str) -> tuple[str, ...]:
    tree = index_tree_code(index_code)
    if not tree:
        return ()
    return (f"/hszg/gg/{tree}",)


def codes_from_constituent_rows(rows) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        dm = str(row.get("dm") or row.get("code") or row.get("gpdm") or "").strip()
        if not dm or dm in seen:
            continue
        seen.add(dm)
        codes.append(dm)
    return codes


INDEX_SPECS = [
    {"code": "000001.SH", "label": "上证指数", "market": "sh"},
    {"code": "399001.SZ", "label": "深证成指", "market": "sz"},
    {"code": "899050.BJ", "label": "北证50", "market": "bj"},
    {"code": "000680.SH", "label": "科创综指", "market": "kc"},
    {"code": "399006.SZ", "label": "创业板指", "market": "cy"},
    {"code": "000905.SH", "label": "中证500", "market": "hs"},
    {"code": "000016.SH", "label": "上证50", "market": "sh"},
]

# Header pulse: 上证 / 深成 / 科创. 科创用科创50点位，不是科创综指成份池。
BOARD_INDICES = [
    {"code": "000001.SH", "short": "上证", "label": "上证指数"},
    {"code": "399001.SZ", "short": "深成", "label": "深证成指"},
    {"code": "000688.SH", "short": "科创", "label": "科创50"},
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

    tree = index_tree_code(code)
    if not tree:
        return {
            "code": code,
            "enabled": False,
            "reason": "麦蕊 hszg 指数树无该节点",
            "count": 0,
            "codes": [],
            "source": "",
        }

    from src.platform.storage import read_cache_json

    cached = read_cache_json(f"index_{code}") or []
    codes = codes_from_constituent_rows(cached) if isinstance(cached, list) else []
    return {
        "code": code,
        "enabled": True,
        "reason": "",
        "count": len(codes) if codes else None,
        "codes": codes,
        "source": f"hszg/gg/{tree}",
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
