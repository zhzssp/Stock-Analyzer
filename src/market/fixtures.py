"""Offline fixtures so S1/S2 can run without a live licence.

These rows are marked source=offline and must never be written as live cache.
"""

from datetime import date, timedelta

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

# Offline constituent slices. Intentionally smaller than the matching exchange
# universe so 行情 cannot be mistaken for 沪市全部 / 深市全部 / 北交所全部.
INDEX_CONSTITUENTS = {
    "000001.SH": ["600038.SH", "600893.SH", "600129.SH", "601166.SH", "600519.SH"],
    "399001.SZ": ["000725.SZ", "000001.SZ", "002230.SZ", "000768.SZ"],
    "899050.BJ": ["430017.BJ", "830799.BJ"],
    "000680.SH": ["688001.SH"],
    "399006.SZ": ["300750.SZ"],
    "000905.SH": ["000725.SZ", "600038.SH"],
    "000016.SH": ["600519.SH", "601166.SH"],
}

# Header board (index points, not constituents).
INDEX_QUOTE = {
    "000001.SH": {"p": 3900.87, "pc": 1.86, "source": "offline"},
    "399001.SZ": {"p": 13650.68, "pc": 2.01, "source": "offline"},
    "000688.SH": {"p": 1948.21, "pc": 2.37, "source": "offline"},
}

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
    "600038": _row(WATCH_SEED[0], p=26.86, pc=1.21, pe=31.4, sjl=1.25),
    "600893": _row(WATCH_SEED[1], p=37.08, pc=-0.84, pe=62.7, sjl=2.46),
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
    inst.code6: _row(
        inst,
        holders=f"{inst.name}控股股东、香港中央结算",
        holders_detail=[
            {"Pm": 1, "Gdmc": f"{inst.name}控股股东", "Cgsl": 48000000, "Cgbl": 48.2},
            {"Pm": 2, "Gdmc": "香港中央结算", "Cgsl": 3100000, "Cgbl": 3.1},
        ],
        top_holders_detail=[
            {"Pm": 1, "Gdmc": f"{inst.name}控股股东", "Cgsl": 48000000, "Cgbl": 48.2},
            {"Pm": 2, "Gdmc": "香港中央结算", "Cgsl": 3100000, "Cgbl": 3.1},
        ],
    )
    for inst in WATCH_SEED
}
HOLDERS["600038"]["holders_detail"] = [
    {"Pm": 1, "Gdmc": "中直股份控股股东", "Cgsl": 48000000, "Cgbl": 48.2},
    {"Pm": 2, "Gdmc": "挪威政府全球养老基金", "Cgsl": 2100000, "Cgbl": 2.1},
    {"Pm": 3, "Gdmc": "香港中央结算", "Cgsl": 3100000, "Cgbl": 3.1},
]
HOLDERS["600038"]["holders"] = "中直股份控股股东、挪威政府全球养老基金"

FUNDS = {
    "600038": [{"name": "易方达瑞享", "shares": 1200000, "pct": 1.2, "value": 3200}],
    "002230": [{"name": "信澳新能源产业股票", "shares": 800000, "pct": 0.6, "value": 2100}],
    "300750": [{"name": "永赢景气精选主动管理ETF", "shares": 500000, "pct": 0.4, "value": 9800}],
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


def _make_bars(close: float, low: float, high: float, days: int = 320) -> list[dict]:
    end = date(2026, 9, 14)
    rows = []
    injected_low = False
    injected_high = False
    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        if d.weekday() >= 5:
            continue
        px = close
        lo, hi = round(px * 0.985, 2), round(px * 1.015, 2)
        if not injected_low and len(rows) > 40:
            lo, px = low, round(low * 1.01, 2)
            injected_low = True
        elif not injected_high and len(rows) > 90:
            hi, px = high, round(high * 0.99, 2)
            injected_high = True
        rows.append({"d": d.isoformat(), "o": px, "h": max(hi, px), "l": min(lo, px), "c": px, "v": 120000 + i})
    return rows


_BAR_SPEC = {
    "600038": (26.86, 24.6, 36.9),
    "600893": (37.08, 28.4, 48.2),
    "000725": (5.78, 3.42, 6.8),
    "002230": (41.25, 32.1, 55.0),
    "600129": (16.72, 12.8, 22.4),
    "601166": (18.02, 14.2, 21.5),
    "000001": (11.52, 9.8, 14.2),
    "600519": (1482.0, 1180.0, 1890.0),
    "300750": (198.4, 140.0, 260.0),
    "688001": (32.18, 22.5, 41.0),
    "000768": (27.65, 18.6, 34.0),
    "430017": (8.46, 6.2, 11.3),
    "830799": (12.08, 8.8, 15.4),
    "833533": (15.33, 11.0, 19.2),
}
BARS = {code: _make_bars(c, lo, hi) for code, (c, lo, hi) in _BAR_SPEC.items()}

FLOW = {}
for code, (close, _lo, _hi) in _BAR_SPEC.items():
    series = []
    base = abs(close) * 80000
    for i in range(25):
        d = date(2026, 9, 14) - timedelta(days=24 - i)
        if d.weekday() >= 5:
            continue
        net = base * (0.2 if i < 23 else 2.4)
        series.append({"d": d.isoformat(), "net_in": round(net, 2), "main_in": round(net * 0.7, 2)})
    FLOW[code] = series

EVENTS = {
    "600038": {
        "dividends": [{"date": "2026-09-10", "s": 0, "z": 0, "x": 3.2, "name": "每10股派3.2元"}],
        "seo": [],
        "unlock": [],
    },
    "000725": {
        "dividends": [],
        "seo": [{"date": "2026-09-08", "name": "定向增发"}],
        "unlock": [],
    },
}
