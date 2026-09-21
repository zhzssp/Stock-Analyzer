"""麦蕊 hszg 树：指数与概念官方成分（与 indices.py 指数路径共用 list + gg 模式）。"""

from __future__ import annotations

from src.market.indices import codes_from_constituent_rows

# type2=2 热门概念，type2=3 概念板块（官网 hszg/list 字段）
CONCEPT_TYPE2 = frozenset({2, 3})


def match_concept_nodes(label: str, nodes: list[dict]) -> list[str]:
    needle = (label or "").strip()
    if not needle:
        return []
    hits: list[str] = []
    for row in nodes:
        if row.get("isleaf") != 1:
            continue
        if row.get("type2") not in CONCEPT_TYPE2:
            continue
        name = str(row.get("name") or "")
        short = name.split("-")[-1] if name else ""
        if needle in {name, short} or needle in name or short.endswith(needle) or needle in short:
            code = str(row.get("code") or "").strip()
            if code and code not in hits:
                hits.append(code)
    return hits


def constituent_codes(rows) -> list[str]:
    return codes_from_constituent_rows(rows)
