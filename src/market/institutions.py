"""图2主权基金、图3投行、备注3基金/汇金白名单。只做名称识别，不做介绍页。"""

from __future__ import annotations


def _entry(kind: str, name: str, aliases: tuple[str, ...] = (), extra: dict | None = None) -> dict:
    row = {"kind": kind, "name": name, "aliases": (name, *aliases)}
    if extra:
        row.update(extra)
    return row


INSTITUTIONS: list[dict] = [
    _entry("swf", "挪威政府全球养老基金", ("GPFG", "NBIM", "Norges Bank"), {"country": "挪威", "aum": "2.1万亿美元"}),
    _entry("swf", "国家外汇管理局投资公司", ("外管局", "SAFE", "华安投资"), {"country": "中国", "aum": "1.99万亿美元"}),
    _entry("swf", "中国投资有限责任公司", ("中投", "CIC"), {"country": "中国", "aum": "1.33万亿美元"}),
    _entry("swf", "阿布扎比投资局", ("ADIA",), {"country": "阿联酋", "aum": "1.06万亿美元"}),
    _entry("swf", "科威特投资局", ("KIA",), {"country": "科威特", "aum": "1.03万亿美元"}),
    _entry("swf", "沙特公共投资基金", ("PIF",), {"country": "沙特阿拉伯", "aum": "约0.933万亿美元"}),
    _entry("swf", "新加坡政府投资公司", ("GIC",), {"country": "新加坡", "aum": "约0.80万亿美元"}),
    _entry("swf", "印尼国家投资管理局", ("INA",), {"country": "印度尼西亚", "aum": "约0.60万亿美元"}),
    _entry("swf", "卡塔尔投资局", ("QIA",), {"country": "卡塔尔", "aum": "约0.533万亿美元"}),
    _entry("swf", "香港金融管理局投资组合", ("金管局", "HKMA"), {"country": "中国香港", "aum": "约0.51万亿美元"}),
    _entry("stabilizer", "中央汇金", ("汇金", "中国投资有限责任公司汇金", "中央汇金投资")),
    _entry("stabilizer", "中国证券金融", ("证金", "中证金融")),
    _entry("ib", "摩根大通", ("JPM", "JPMorgan", "JP Morgan", "小摩")),
    _entry("ib", "高盛", ("Goldman", "Goldman Sachs", "GS")),
    _entry("ib", "摩根士丹利", ("Morgan Stanley", "大摩", "MS")),
    _entry("ib", "花旗集团", ("花旗", "Citi", "Citigroup")),
    _entry("ib", "美国银行", ("美银", "BofA", "Bank of America", "BAC")),
    _entry("ib", "瑞银集团", ("瑞银", "UBS")),
    _entry("fund", "富国通胀通缩主题轮动", ("富国通胀通缩",)),
    _entry("fund", "易方达瑞享", ("易方达瑞享I",)),
    _entry("fund", "国泰金鹰增长", ()),
    _entry("fund", "信澳新能源产业股票", ("信澳新能源",)),
    _entry("etf", "易方达品质未来主动管理ETF", ("易方达品质未来",)),
    _entry("etf", "华夏质量价值甄选主动管理ETF", ("华夏质量价值甄选",)),
    _entry("etf", "永赢景气精选主动管理ETF", ("永赢景气精选",)),
    _entry("fund", "鹏华优质回报两年定开混合", ("鹏华优质回报",)),
]


def _fold(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def match_institution(name: str) -> dict | None:
    folded = _fold(name)
    if not folded:
        return None
    best = None
    best_len = 0
    for item in INSTITUTIONS:
        for alias in item["aliases"]:
            key = _fold(alias)
            if not key:
                continue
            if key == folded or key in folded or folded in key:
                if len(key) > best_len:
                    best = item
                    best_len = len(key)
    return best


def match_many(names: list[str], kinds: tuple[str, ...] | None = None) -> list[dict]:
    hits = []
    seen = set()
    for raw in names:
        item = match_institution(raw)
        if not item:
            continue
        if kinds and item["kind"] not in kinds:
            continue
        key = item["name"]
        if key in seen:
            continue
        seen.add(key)
        hits.append({**item, "matched": raw})
    return hits


def catalog() -> list[dict]:
    return [
        {"kind": i["kind"], "name": i["name"], "aliases": list(i["aliases"]), **{k: i[k] for k in i if k not in {"kind", "name", "aliases"}}}
        for i in INSTITUTIONS
    ]
