"""申万一级 / 七大板块 / 2026 概念。静态主数据，不把 hszg 名称当成官方码表。"""

from __future__ import annotations

from typing import Any

SW_L1 = (
    "银行",
    "非银金融",
    "食品饮料",
    "医药生物",
    "家用电器",
    "美容护理",
    "商贸零售",
    "电子",
    "电力设备",
    "计算机",
    "通信",
    "汽车",
    "机械设备",
    "国防军工",
    "有色金属",
    "石油石化",
    "煤炭",
    "基础化工",
    "钢铁",
    "建筑材料",
    "建筑装饰",
    "公用事业",
    "环保",
    "交通运输",
    "仓储物流",
    "农林牧渔",
    "纺织服饰",
    "轻工制造",
    "社会服务",
    "传媒",
    "房地产",
)

SECTORS: dict[str, tuple[str, ...]] = {
    "大金融": ("银行", "非银金融"),
    "大消费": ("食品饮料", "医药生物", "家用电器", "美容护理", "商贸零售"),
    "高端制造与科技": ("电子", "电力设备", "计算机", "通信", "汽车", "机械设备", "国防军工"),
    "周期": ("有色金属", "石油石化", "煤炭", "基础化工", "钢铁", "建筑材料", "建筑装饰"),
    "公用事业与环保": ("公用事业", "环保"),
    "交通运输与物流": ("交通运输", "仓储物流"),
    "其他": ("农林牧渔", "纺织服饰", "轻工制造", "社会服务", "传媒", "房地产"),
}

L1_TO_SECTOR = {name: sector for sector, names in SECTORS.items() for name in names}

# 备注里的二级关键词 → 申万一级。用来从概念串或行业别名回推。
L2_TO_L1: dict[str, str] = {
    "国有大行": "银行",
    "股份制银行": "银行",
    "城商行": "银行",
    "农商行": "银行",
    "证券": "非银金融",
    "保险": "非银金融",
    "信托": "非银金融",
    "期货": "非银金融",
    "租赁": "非银金融",
    "多元金融": "非银金融",
    "白酒": "食品饮料",
    "啤酒": "食品饮料",
    "乳制品": "食品饮料",
    "调味品": "食品饮料",
    "休闲食品": "食品饮料",
    "软饮料": "食品饮料",
    "化学制药": "医药生物",
    "中药": "医药生物",
    "生物制品": "医药生物",
    "疫苗": "医药生物",
    "医疗器械": "医药生物",
    "医药商业": "医药生物",
    "医疗服务": "医药生物",
    "白电": "家用电器",
    "黑电": "家用电器",
    "小家电": "家用电器",
    "厨卫电器": "家用电器",
    "化妆品": "美容护理",
    "个护用品": "美容护理",
    "医美": "美容护理",
    "百货": "商贸零售",
    "超市": "商贸零售",
    "专业连锁": "商贸零售",
    "电商": "商贸零售",
    "半导体": "电子",
    "消费电子": "电子",
    "光学光电子": "电子",
    "电子元件": "电子",
    "光伏": "电力设备",
    "风电": "电力设备",
    "储能": "电力设备",
    "电网设备": "电力设备",
    "新能源车设备": "电力设备",
    "软件": "计算机",
    "IT服务": "计算机",
    "通信设备": "通信",
    "光模块": "通信",
    "卫星通信": "通信",
    "乘用车": "汽车",
    "商用车": "汽车",
    "汽车零部件": "汽车",
    "机床": "机械设备",
    "工程机械": "机械设备",
    "机器人": "机械设备",
    "航空装备": "国防军工",
    "航天装备": "国防军工",
    "船舶制造": "国防军工",
    "兵器装备": "国防军工",
    "军工电子": "国防军工",
    "直升机": "国防军工",
    "航空发动机": "国防军工",
    "工业金属": "有色金属",
    "贵金属": "有色金属",
    "能源金属": "有色金属",
    "铜": "有色金属",
    "铝": "有色金属",
    "黄金": "有色金属",
    "石油开采": "石油石化",
    "石油加工": "石油石化",
    "煤炭开采": "煤炭",
    "化学原料": "基础化工",
    "普钢": "钢铁",
    "特钢": "钢铁",
    "水泥": "建筑材料",
    "玻璃": "建筑材料",
    "房屋建设": "建筑装饰",
    "火电": "公用事业",
    "水电": "公用事业",
    "核电": "公用事业",
    "固废处理": "环保",
    "铁路运输": "交通运输",
    "航空运输": "交通运输",
    "快递": "仓储物流",
    "种植业": "农林牧渔",
    "畜牧业": "农林牧渔",
    "生猪": "农林牧渔",
    "纺织制造": "纺织服饰",
    "造纸": "轻工制造",
    "旅游": "社会服务",
    "游戏": "传媒",
    "房地产开发": "房地产",
}

CONCEPTS_2026: dict[str, tuple[str, ...]] = {
    "人工智能": ("人工智能", "AI", "大模型", "AI算力", "智能语音", "液冷"),
    "人形机器人": ("人形机器人", "伺服电机", "减速器"),
    "低空经济": ("低空经济", "无人机", "eVTOL", "低空物流"),
    "半导体国产替代": ("半导体国产替代", "先进封装", "Chiplet", "HBM", "存储芯片", "第三代半导体", "半导体显示", "半导体设备"),
    "新能源": ("新能源", "储能", "氢能", "光伏", "新能源车", "锂电池"),
    "脑机接口/生物计算": ("脑机接口", "生物计算"),
    "商业航天": ("商业航天", "低轨卫星", "卫星"),
}


def _norm(text: str) -> str:
    return (text or "").strip()


def _tokens(concept: str) -> list[str]:
    raw = (concept or "").replace("，", ",").replace("、", ",")
    return [p.strip() for p in raw.split(",") if p.strip()]


def infer_l1(industry: str, concept: str = "") -> str:
    name = _norm(industry)
    if name in L1_TO_SECTOR:
        return name
    if name in L2_TO_L1:
        return L2_TO_L1[name]
    for l1 in SW_L1:
        if l1 and l1 in name:
            return l1
    for token in [name, *_tokens(concept)]:
        if token in L2_TO_L1:
            return L2_TO_L1[token]
        for key, l1 in L2_TO_L1.items():
            if key and key in token:
                return l1
    return ""


def normalize_custom_concepts(items: Any) -> list[dict]:
    """User-owned labels. Still keyword aliases, not official constituents."""
    rows = items if isinstance(items, list) else []
    out: list[dict] = []
    seen: set[str] = set()
    for raw in rows[:16]:
        if not isinstance(raw, dict):
            continue
        label = _norm(str(raw.get("label") or raw.get("name") or ""))[:24]
        if not label or label in seen:
            continue
        if label in CONCEPTS_2026:
            raise ValueError("不要与内置 2026 概念重名，换一个名字")
        aliases: list[str] = []
        extra = raw.get("aliases") if raw.get("aliases") is not None else raw.get("needles")
        if isinstance(extra, str):
            extra = [p.strip() for p in extra.replace("，", ",").replace("、", ",").split(",")]
        for token in [label, *(extra or [])]:
            text = _norm(str(token))[:24]
            if text and text not in aliases:
                aliases.append(text)
        if not aliases:
            continue
        seen.add(label)
        out.append({"id": label, "label": label, "aliases": aliases[:8], "source": "custom"})
    return out


def extra_book(items: list[dict] | None) -> dict[str, tuple[str, ...]]:
    book: dict[str, tuple[str, ...]] = {}
    for row in items or []:
        label = _norm(str(row.get("label") or ""))
        aliases = tuple(a for a in (row.get("aliases") or []) if str(a).strip())
        if label and aliases:
            book[label] = aliases
    return book


def concept_book(extra: dict[str, tuple[str, ...]] | None = None) -> dict[str, tuple[str, ...]]:
    book = dict(CONCEPTS_2026)
    for label, aliases in (extra or {}).items():
        if not label or not aliases:
            continue
        if label in book:
            merged = list(book[label])
            for alias in aliases:
                if alias not in merged:
                    merged.append(alias)
            book[label] = tuple(merged)
        else:
            book[label] = tuple(aliases)
    return book


def infer_hot_concepts(concept: str, industry: str = "", extra: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    hay = f"{concept or ''} {industry or ''}"
    hits = []
    for label, aliases in concept_book(extra).items():
        if any(alias and alias in hay for alias in aliases):
            hits.append(label)
    return hits


def classify(industry: str = "", concept: str = "", extra: dict[str, tuple[str, ...]] | None = None) -> dict:
    l1 = infer_l1(industry, concept)
    sector = L1_TO_SECTOR.get(l1, "")
    hot = infer_hot_concepts(concept, industry, extra)
    return {
        "sector": sector,
        "sw_l1": l1,
        "hot_concepts": ",".join(hot),
        "hot_list": hot,
    }


def catalog(extra: dict[str, tuple[str, ...]] | None = None) -> dict:
    book = concept_book(extra)
    concepts = []
    for label, aliases in book.items():
        concepts.append(
            {
                "id": label,
                "label": label,
                "aliases": list(aliases),
                "source": "builtin" if label in CONCEPTS_2026 else "custom",
            }
        )
    return {
        "sectors": [{"id": k, "label": k, "sw_l1": list(v)} for k, v in SECTORS.items()],
        "sw_l1": list(SW_L1),
        "concepts_2026": [c for c in concepts if c["source"] == "builtin"],
        "concepts_custom": [c for c in concepts if c["source"] == "custom"],
    }


def search_needles(q: str, extra: dict[str, tuple[str, ...]] | None = None) -> set[str]:
    """If q is a sector / L1 / concept label, return strings that should match a stock haystack."""
    raw = _norm(q)
    if not raw:
        return set()
    book = concept_book(extra)
    out = {raw, raw.lower()}
    if raw in SECTORS:
        out.update(SECTORS[raw])
    if raw in book:
        out.update(book[raw])
    for label, aliases in book.items():
        if raw == label or raw in aliases:
            out.add(label)
            out.update(aliases)
    return {x for x in out if x}
