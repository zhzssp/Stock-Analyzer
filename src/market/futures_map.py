"""行业 → 关联期货品种。只提供映射，不假装有行情。"""

from __future__ import annotations

from src.market.taxonomy import infer_l1

# 备注4：商品 / 金融期货树，按申万一级挂常用品种。
FUTURES_BY_L1: dict[str, list[dict]] = {
    "有色金属": [
        {"id": "cu", "name": "铜", "group": "工业金属", "venues": ("LME", "SHFE")},
        {"id": "al", "name": "铝", "group": "工业金属", "venues": ("LME", "SHFE")},
        {"id": "zn", "name": "锌", "group": "工业金属", "venues": ("LME", "SHFE")},
        {"id": "au", "name": "黄金", "group": "贵金属", "venues": ("COMEX", "SHFE")},
        {"id": "ag", "name": "白银", "group": "贵金属", "venues": ("COMEX", "SHFE")},
    ],
    "石油石化": [
        {"id": "wti", "name": "WTI原油", "group": "能源", "venues": ("NYMEX",)},
        {"id": "brent", "name": "布伦特原油", "group": "能源", "venues": ("ICE",)},
        {"id": "ng", "name": "天然气", "group": "能源", "venues": ("NYMEX",)},
    ],
    "煤炭": [
        {"id": "wti", "name": "WTI原油", "group": "能源", "venues": ("NYMEX",)},
    ],
    "基础化工": [
        {"id": "eg", "name": "乙二醇", "group": "化工", "venues": ("DCE",)},
        {"id": "ru", "name": "合成胶", "group": "化工", "venues": ("SHFE",)},
    ],
    "农林牧渔": [
        {"id": "c", "name": "玉米", "group": "谷物", "venues": ("CBOT", "DCE")},
        {"id": "s", "name": "大豆", "group": "谷物", "venues": ("CBOT", "DCE")},
        {"id": "w", "name": "小麦", "group": "谷物", "venues": ("CBOT",)},
        {"id": "lh", "name": "生猪", "group": "国内特色", "venues": ("DCE",)},
        {"id": "feed", "name": "饲料相关", "group": "农产品", "venues": ("DCE",)},
    ],
    "食品饮料": [
        {"id": "c", "name": "玉米", "group": "谷物", "venues": ("CBOT", "DCE")},
        {"id": "s", "name": "大豆", "group": "谷物", "venues": ("CBOT", "DCE")},
    ],
    "银行": [
        {"id": "us10y", "name": "美国国债期货", "group": "利率", "venues": ("CBOT",)},
        {"id": "spx", "name": "标普500指数", "group": "股指", "venues": ("CME",)},
    ],
    "非银金融": [
        {"id": "spx", "name": "标普500指数", "group": "股指", "venues": ("CME",)},
        {"id": "hsi", "name": "恒生指数", "group": "股指", "venues": ("HKEX",)},
    ],
}


def contracts_for(industry: str = "", concept: str = "") -> list[dict]:
    l1 = infer_l1(industry, concept)
    rows = list(FUTURES_BY_L1.get(l1) or [])
    return [{**row, "sw_l1": l1, "quote": None, "reason": "等待期货行情源"} for row in rows]


def catalog() -> dict:
    return {
        "by_l1": {k: v for k, v in FUTURES_BY_L1.items()},
        "groups": ("能源", "化工", "工业金属", "贵金属", "农产品", "股指", "利率", "外汇"),
        "quotes_enabled": False,
    }
