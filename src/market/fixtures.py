"""Offline fixtures so S1/S2 can run without a live licence.

These rows are marked source=offline and must never be written as live cache.
"""

from src.market.normalize import Instrument, normalize_instrument

WATCH_SEED = [
    normalize_instrument("600038.SH", "中直股份", "SH"),
    normalize_instrument("600893.SH", "航发动力", "SH"),
    normalize_instrument("000725.SZ", "京东方A", "SZ"),
    normalize_instrument("002230.SZ", "科大讯飞", "SZ"),
    normalize_instrument("600129.SH", "太极集团", "SH"),
    normalize_instrument("601166.SH", "兴业银行", "SH"),
]

# Offline screening universe (S3). Live mode uses hslt/list + bj/list/all.
UNIVERSE_HS = WATCH_SEED + [
    normalize_instrument("000001.SZ", "平安银行", "SZ"),
    normalize_instrument("600519.SH", "贵州茅台", "SH"),
    normalize_instrument("300750.SZ", "宁德时代", "SZ"),
    normalize_instrument("688001.SH", "华兴源创", "SH"),
    normalize_instrument("000768.SZ", "中航西飞", "SZ"),
]
UNIVERSE_BJ = [
    normalize_instrument("430017.BJ", "星昊医药", "BJ"),
    normalize_instrument("830799.BJ", "艾融软件", "BJ"),
    normalize_instrument("833533.BJ", "凯华材料", "BJ"),
]
UNIVERSE = UNIVERSE_HS + UNIVERSE_BJ
_INST = {i.code6: i for i in UNIVERSE}

INDUSTRY = {
    "600038": "国防军工",
    "600893": "国防军工",
    "000725": "电子",
    "002230": "计算机",
    "600129": "医药生物",
    "601166": "银行",
    "000001": "银行",
    "600519": "食品饮料",
    "300750": "电力设备",
    "688001": "机械设备",
    "000768": "国防军工",
    "430017": "医药生物",
    "830799": "计算机",
    "833533": "电子",
}


def _row(inst: Instrument, **extra) -> dict:
    base = {
        "code6": inst.code6,
        "code_full": inst.code_full,
        "name": inst.name,
        "exchange": inst.exchange,
        "market": inst.market,
        "source": "offline",
    }
    base.update(extra)
    return base


QUOTE = {
    "600038": _row(WATCH_SEED[0], p=26.86, pc=1.21, pe=31.4),
    "600893": _row(WATCH_SEED[1], p=37.08, pc=-0.84, pe=62.7),
    "000725": _row(WATCH_SEED[2], p=5.78, pc=2.12, pe=22.1),
    "002230": _row(WATCH_SEED[3], p=41.25, pc=-1.06, pe=48.6),
    "600129": _row(WATCH_SEED[4], p=16.72, pc=0.54, pe=18.9),
    "601166": _row(WATCH_SEED[5], p=18.02, pc=-0.33, pe=6.2),
    "000001": _row(_INST["000001"], p=11.52, pc=0.26, pe=5.8),
    "600519": _row(_INST["600519"], p=1482.0, pc=-0.41, pe=28.3),
    "300750": _row(_INST["300750"], p=198.4, pc=1.15, pe=22.6),
    "688001": _row(_INST["688001"], p=32.18, pc=0.72, pe=45.1),
    "000768": _row(_INST["000768"], p=27.65, pc=1.88, pe=38.2),
    "430017": _row(_INST["430017"], p=8.46, pc=2.31, pe=None),
    "830799": _row(_INST["830799"], p=12.08, pc=-0.55, pe=None),
    "833533": _row(_INST["833533"], p=15.33, pc=0.18, pe=None),
}

PROFILE = {
    "600038": _row(
        WATCH_SEED[0],
        industry="国防军工",
        concept="航空装备,直升机",
        business="直升机整机及零部件研制、生产与销售",
    ),
    "600893": _row(
        WATCH_SEED[1],
        industry="国防军工",
        concept="航空发动机",
        business="航空发动机及燃气轮机研制",
    ),
    "000725": _row(
        WATCH_SEED[2],
        industry="电子",
        concept="面板,半导体显示",
        business="半导体显示器件、智慧系统及健康服务",
    ),
    "002230": _row(
        WATCH_SEED[3],
        industry="计算机",
        concept="人工智能,智能语音",
        business="智能语音及人工智能技术和产品",
    ),
    "600129": _row(
        WATCH_SEED[4],
        industry="医药生物",
        concept="中药",
        business="中成药研发、生产与销售",
    ),
    "601166": _row(
        WATCH_SEED[5],
        industry="银行",
        concept="银行",
        business="商业银行业务",
    ),
    "000001": _row(_INST["000001"], industry="银行", concept="银行", business="商业银行业务"),
    "600519": _row(_INST["600519"], industry="食品饮料", concept="白酒", business="白酒生产与销售"),
    "300750": _row(_INST["300750"], industry="电力设备", concept="锂电池,新能源", business="动力电池及储能系统"),
    "688001": _row(_INST["688001"], industry="机械设备", concept="科创板,半导体设备", business="半导体检测设备"),
    "000768": _row(_INST["000768"], industry="国防军工", concept="航空装备", business="军民用飞机研制"),
    "430017": _row(_INST["430017"], industry="医药生物", concept="北交所,化学药", business="化学制剂研发与生产"),
    "830799": _row(_INST["830799"], industry="计算机", concept="北交所,金融科技", business="银行软件与金融科技服务"),
    "833533": _row(_INST["833533"], industry="电子", concept="北交所,电子材料", business="电子材料研发与销售"),
}

HOLDERS = {
    code: _row(
        inst,
        holders="中国航空工业集团等",
        holders_detail=[
            {"Pm": 1, "Gdmc": "控股股东", "Cgbl": 48.2},
            {"Pm": 2, "Gdmc": "香港中央结算", "Cgbl": 3.1},
        ],
    )
    for code, inst in (
        (i.code6, i) for i in WATCH_SEED
    )
}

FINANCE = {
    "600038": _row(WATCH_SEED[0], mgwfplr=3.21, yffy=19.4, mgjzc=21.43, jbmgsy=0.86, xsmlv=18.2, jlv=6.1, zgb=59.0, ysltag=48.2),
    "600893": _row(WATCH_SEED[1], mgwfplr=2.04, yffy=32.3, mgjzc=15.07, jbmgsy=0.59, xsmlv=16.8, jlv=4.2, zgb=266.4, ysltag=266.4),
    "000725": _row(WATCH_SEED[2], mgwfplr=1.12, yffy=110.5, mgjzc=4.55, jbmgsy=0.26, xsmlv=15.0, jlv=3.3, zgb=3769.0, ysltag=3769.0),
    "002230": _row(WATCH_SEED[3], mgwfplr=4.88, yffy=38.9, mgjzc=9.51, jbmgsy=0.85, xsmlv=41.2, jlv=8.7, zgb=232.5, ysltag=212.0),
    "600129": _row(WATCH_SEED[4], mgwfplr=2.66, yffy=3.4, mgjzc=6.51, jbmgsy=0.88, xsmlv=52.0, jlv=11.4, zgb=55.7, ysltag=55.7),
    "601166": _row(WATCH_SEED[5], mgwfplr=8.12, yffy=0.0, mgjzc=20.47, jbmgsy=3.21, xsmlv=None, jlv=28.1, zgb=2077.0, ysltag=2077.0),
    "000001": _row(_INST["000001"], mgwfplr=7.02, yffy=0.0, mgjzc=16.88, jbmgsy=1.98, xsmlv=None, jlv=24.6, zgb=1941.0, ysltag=1941.0),
    "600519": _row(_INST["600519"], mgwfplr=82.4, yffy=3.1, mgjzc=168.2, jbmgsy=52.4, xsmlv=91.6, jlv=52.1, zgb=125.6, ysltag=125.6),
    "300750": _row(_INST["300750"], mgwfplr=18.6, yffy=86.2, mgjzc=32.4, jbmgsy=8.76, xsmlv=22.4, jlv=12.8, zgb=440.0, ysltag=380.0),
    "688001": _row(_INST["688001"], mgwfplr=1.88, yffy=2.4, mgjzc=8.12, jbmgsy=0.71, xsmlv=38.5, jlv=9.2, zgb=44.1, ysltag=18.6),
    "000768": _row(_INST["000768"], mgwfplr=2.44, yffy=21.8, mgjzc=9.76, jbmgsy=0.72, xsmlv=14.6, jlv=4.8, zgb=277.0, ysltag=277.0),
}
