from __future__ import annotations

from src.market.institutions import match_institution


def _num(value) -> float | None:
    if value in (None, "", "-", "—"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def normalize_holder(item: dict, catalog: list[dict] | None = None) -> dict:
    name = str(item.get("Gdmc") or item.get("gdmc") or item.get("name") or "").strip()
    inst = match_institution(name, catalog)
    return {
        "name": name,
        "shares": _num(item.get("Cgsl") or item.get("cgsl") or item.get("shares")),
        "pct": _num(item.get("Cgbl") or item.get("cgbl") or item.get("pct")),
        "reason": str(item.get("Bdyy") or item.get("bdyy") or item.get("reason") or ""),
        "institution": inst["name"] if inst else "",
        "institution_kind": inst["kind"] if inst else "",
    }


def normalize_holders(items: list | None, catalog: list[dict] | None = None) -> list[dict]:
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        row = normalize_holder(item, catalog)
        if row["name"]:
            out.append(row)
    return out


def summarize(items: list[dict], limit: int = 3) -> str:
    names = [x["name"] for x in items[:limit] if x.get("name")]
    return "、".join(names) or ""


def diff_holders(old_items: list[dict] | None, new_items: list[dict] | None) -> dict:
    old_map = {x["name"]: x for x in old_items or [] if x.get("name")}
    new_map = {x["name"]: x for x in new_items or [] if x.get("name")}
    entered, exited, increased, decreased = [], [], [], []
    for name, cur in new_map.items():
        prev = old_map.get(name)
        if not prev:
            entered.append(cur)
            continue
        cur_v = cur.get("shares") if cur.get("shares") is not None else cur.get("pct")
        prev_v = prev.get("shares") if prev.get("shares") is not None else prev.get("pct")
        if cur_v is None or prev_v is None:
            continue
        if cur_v > prev_v:
            increased.append({**cur, "from": prev_v, "to": cur_v})
        elif cur_v < prev_v:
            decreased.append({**cur, "from": prev_v, "to": cur_v})
    for name, prev in old_map.items():
        if name not in new_map:
            exited.append(prev)
    return {
        "entered": entered,
        "exited": exited,
        "increased": increased,
        "decreased": decreased,
        "changed": bool(entered or exited or increased or decreased),
    }


def format_diff(diff: dict) -> str:
    bits = []
    for label, key in (("新进", "entered"), ("退出", "exited"), ("增持", "increased"), ("减持", "decreased")):
        rows = diff.get(key) or []
        if not rows:
            continue
        names = []
        for row in rows:
            tag = row.get("institution") or row.get("name")
            if row.get("from") is not None:
                names.append(f"{tag}({row['from']}→{row['to']})")
            else:
                names.append(tag)
        bits.append(f"{label}：{'、'.join(names)}")
    return "；".join(bits)


def watch_hits(diff: dict) -> list[dict]:
    hits = []
    for key in ("entered", "exited", "increased", "decreased"):
        for row in diff.get(key) or []:
            if row.get("institution"):
                hits.append(row)
    return hits
