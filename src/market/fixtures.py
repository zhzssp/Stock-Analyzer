"""Offline fixtures so the workbench can be verified without a live licence.

Rows are marked source=offline and must never be written as live cache.
The slice is intentionally small versus a real listing, but it covers the
attribute and alert paths used before paying for MAIRUI.
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
    normalize_instrument("601012.SH", "隆基绿能", "SH"),
    normalize_instrument("002415.SZ", "海康威视", "SZ"),
    normalize_instrument("300274.SZ", "阳光电源", "SZ"),
    normalize_instrument("601899.SH", "紫金矿业", "SH"),
]

# Offline screening universe (S3). Live mode uses hslt/list + bj/list/all.
UNIVERSE_HS = WATCH_SEED + [
    normalize_instrument("000001.SZ", "平安银行", "SZ"),
    normalize_instrument("600519.SH", "贵州茅台", "SH"),
    normalize_instrument("300750.SZ", "宁德时代", "SZ"),
    normalize_instrument("688001.SH", "华兴源创", "SH"),
    normalize_instrument("000768.SZ", "中航西飞", "SZ"),
    normalize_instrument("000858.SZ", "五粮液", "SZ"),
    normalize_instrument("601318.SH", "中国平安", "SH"),
    normalize_instrument("688981.SH", "中芯国际", "SH"),
    normalize_instrument("300760.SZ", "迈瑞医疗", "SZ"),
    normalize_instrument("002594.SZ", "比亚迪", "SZ"),
    normalize_instrument("000063.SZ", "中兴通讯", "SZ"),
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
    "601012": "电力设备",
    "002415": "电子",
    "300274": "电力设备",
    "601899": "有色金属",
    "000001": "银行",
    "600519": "食品饮料",
    "300750": "电力设备",
    "688001": "机械设备",
    "000768": "国防军工",
    "000858": "食品饮料",
    "601318": "非银金融",
    "688981": "电子",
    "300760": "医药生物",
    "002594": "汽车",
    "000063": "通信",
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


def _i(code6: str) -> Instrument:
    return _INST[code6]


QUOTE = {
    "600038": _row(_i("600038"), p=26.86, pc=1.21, pe=31.4, sjl=1.25, hs=0.86, sz=412.5, lt=318.2, zdf60=8.4, zdfnc=12.1),
    "600893": _row(_i("600893"), p=37.08, pc=-0.84, pe=62.7, sjl=2.46),
    "000725": _row(_i("000725"), p=5.78, pc=2.12, pe=22.1, sjl=1.27),
    "002230": _row(_i("002230"), p=41.25, pc=-1.06, pe=48.6, sjl=4.34),
    "600129": _row(_i("600129"), p=16.72, pc=0.54, pe=18.9, sjl=2.57),
    "601166": _row(_i("601166"), p=18.02, pc=-0.33, pe=6.2, sjl=0.88),
    "601012": _row(_i("601012"), p=15.20, pc=-1.44, pe=18.2, sjl=1.62),
    "002415": _row(_i("002415"), p=28.35, pc=-10.0, pe=16.8, sjl=3.12),
    "300274": _row(_i("300274"), p=88.60, pc=20.0, pe=24.5, sjl=4.88),
    "601899": _row(_i("601899"), p=18.46, pc=2.88, pe=12.4, sjl=2.05),
    "000001": _row(_i("000001"), p=11.52, pc=0.26, pe=5.8, sjl=0.68),
    "600519": _row(_i("600519"), p=1482.0, pc=-0.41, pe=28.3, sjl=8.81),
    "300750": _row(_i("300750"), p=198.4, pc=1.15, pe=22.6, sjl=6.12),
    "688001": _row(_i("688001"), p=32.18, pc=0.72, pe=45.1, sjl=3.96),
    "000768": _row(_i("000768"), p=27.65, pc=1.88, pe=38.2, sjl=2.83),
    "000858": _row(_i("000858"), p=128.40, pc=9.97, pe=16.4, sjl=3.55),
    "601318": _row(_i("601318"), p=48.16, pc=-1.22, pe=11.8, sjl=1.15),
    "688981": _row(_i("688981"), p=86.20, pc=19.85, pe=58.0, sjl=3.40),
    "300760": _row(_i("300760"), p=228.00, pc=0.88, pe=32.4, sjl=6.80),
    "002594": _row(_i("002594"), p=268.50, pc=8.60, pe=21.7, sjl=4.10),
    "000063": _row(_i("000063"), p=32.46, pc=-3.21, pe=19.6, sjl=2.22),
    "430017": _row(_i("430017"), p=8.46, pc=2.31, pe=None, sjl=None),
    "830799": _row(_i("830799"), p=12.08, pc=-0.55, pe=28.4, sjl=2.18),
    "833533": _row(_i("833533"), p=15.33, pc=0.18, pe=36.2, sjl=2.64),
}

PROFILE = {
    "600038": _row(_i("600038"), industry="国防军工", concept="航空装备,直升机", business="直升机整机及零部件研制、生产与销售"),
    "600893": _row(_i("600893"), industry="国防军工", concept="航空发动机", business="航空发动机及燃气轮机研制"),
    "000725": _row(_i("000725"), industry="电子", concept="面板,半导体显示", business="半导体显示器件、智慧系统及健康服务"),
    "002230": _row(_i("002230"), industry="计算机", concept="人工智能,智能语音", business="智能语音及人工智能技术和产品"),
    "600129": _row(_i("600129"), industry="医药生物", concept="中药", business="中成药研发、生产与销售"),
    "601166": _row(_i("601166"), industry="银行", concept="银行", business="商业银行业务"),
    "601012": _row(_i("601012"), industry="电力设备", concept="光伏,新能源", business="单晶硅棒、硅片、电池及组件"),
    "002415": _row(_i("002415"), industry="电子", concept="消费电子,安防", business="安防视频产品及智慧物联"),
    "300274": _row(_i("300274"), industry="电力设备", concept="光伏,储能,新能源", business="光伏逆变器及储能系统"),
    "601899": _row(_i("601899"), industry="有色金属", concept="铜,黄金", business="铜金锌等矿产资源开发"),
    "000001": _row(_i("000001"), industry="银行", concept="银行", business="商业银行业务"),
    "600519": _row(_i("600519"), industry="食品饮料", concept="白酒", business="白酒生产与销售"),
    "300750": _row(_i("300750"), industry="电力设备", concept="锂电池,新能源", business="动力电池及储能系统"),
    "688001": _row(_i("688001"), industry="机械设备", concept="科创板,半导体设备", business="半导体检测设备"),
    "000768": _row(_i("000768"), industry="国防军工", concept="航空装备,低空经济", business="军民用飞机研制"),
    "000858": _row(_i("000858"), industry="食品饮料", concept="白酒", business="白酒生产与销售"),
    "601318": _row(_i("601318"), industry="非银金融", concept="保险", business="保险、银行与投资业务"),
    "688981": _row(_i("688981"), industry="电子", concept="半导体国产替代,先进封装", business="集成电路晶圆制造"),
    "300760": _row(_i("300760"), industry="医药生物", concept="医疗器械", business="医疗器械研发与销售"),
    "002594": _row(_i("002594"), industry="汽车", concept="新能源车,锂电池", business="新能源汽车及电池"),
    "000063": _row(_i("000063"), industry="通信", concept="通信设备,光模块", business="通信设备与算力基础设施"),
    "430017": _row(_i("430017"), industry="医药生物", concept="北交所,化学药", business="化学制剂研发与生产"),
    "830799": _row(_i("830799"), industry="计算机", concept="北交所,金融科技", business="银行软件与金融科技服务"),
    "833533": _row(_i("833533"), industry="电子", concept="北交所,电子材料", business="电子材料研发与销售"),
}


def _holder_lines(inst: Instrument, extras: list[dict] | None = None) -> list[dict]:
    rows = [
        {"Pm": 1, "Gdmc": f"{inst.name}控股股东", "Cgsl": 48000000, "Cgbl": 48.2},
        {"Pm": 2, "Gdmc": "香港中央结算", "Cgsl": 3100000, "Cgbl": 3.1},
    ]
    for offset, extra in enumerate(extras or [], start=3):
        item = dict(extra)
        item.setdefault("Pm", offset)
        rows.append(item)
    return rows


def _holders_pack(inst: Instrument, details: list[dict], top: list[dict] | None = None) -> dict:
    top = top if top is not None else details
    return _row(
        inst,
        holders="、".join(x["Gdmc"] for x in details[:3]),
        holders_detail=details,
        top_holders_detail=top,
    )


HOLDERS = {}
for _inst in UNIVERSE:
    if _inst.code6 == "430017":
        continue
    HOLDERS[_inst.code6] = _holders_pack(_inst, _holder_lines(_inst))
HOLDERS["600038"] = _holders_pack(
    _i("600038"),
    [
        {"Pm": 1, "Gdmc": "中直股份控股股东", "Cgsl": 48000000, "Cgbl": 48.2},
        {"Pm": 2, "Gdmc": "挪威政府全球养老基金", "Cgsl": 2100000, "Cgbl": 2.1},
        {"Pm": 3, "Gdmc": "香港中央结算", "Cgsl": 3100000, "Cgbl": 3.1},
    ],
    [
        {"Pm": 1, "Gdmc": "中直股份控股股东", "Cgsl": 48000000, "Cgbl": 48.2},
        {"Pm": 2, "Gdmc": "挪威政府全球养老基金", "Cgsl": 2100000, "Cgbl": 2.1},
        {"Pm": 3, "Gdmc": "香港中央结算", "Cgsl": 3100000, "Cgbl": 3.1},
        {"Pm": 4, "Gdmc": "中直股份员工持股", "Cgsl": 900000, "Cgbl": 0.9},
    ],
)
HOLDERS["600038"]["holders"] = "中直股份控股股东、挪威政府全球养老基金"
HOLDERS["601166"] = _holders_pack(_i("601166"), _holder_lines(_i("601166"), [{"Gdmc": "中央汇金", "Cgsl": 8600000, "Cgbl": 8.6}]))
HOLDERS["000001"] = _holders_pack(_i("000001"), _holder_lines(_i("000001"), [{"Gdmc": "中国证券金融", "Cgsl": 5400000, "Cgbl": 5.4}]))
HOLDERS["600519"] = _holders_pack(_i("600519"), _holder_lines(_i("600519"), [{"Gdmc": "高盛", "Cgsl": 1200000, "Cgbl": 1.1}]))
HOLDERS["601318"] = _holders_pack(_i("601318"), _holder_lines(_i("601318"), [{"Gdmc": "摩根士丹利", "Cgsl": 2100000, "Cgbl": 1.6}]))
HOLDERS["002415"] = _holders_pack(_i("002415"), _holder_lines(_i("002415"), [{"Gdmc": "花旗集团", "Cgsl": 1800000, "Cgbl": 1.4}]))
HOLDERS["601899"] = _holders_pack(_i("601899"), _holder_lines(_i("601899"), [{"Gdmc": "新加坡政府投资公司", "Cgsl": 3300000, "Cgbl": 2.4}]))
HOLDERS["601012"] = _holders_pack(_i("601012"), _holder_lines(_i("601012"), [{"Gdmc": "瑞银集团", "Cgsl": 1500000, "Cgbl": 1.2}]))

FUNDS = {
    "600038": [{"name": "易方达瑞享", "shares": 1200000, "pct": 1.2, "value": 3200}],
    "002230": [{"name": "信澳新能源产业股票", "shares": 800000, "pct": 0.6, "value": 2100}],
    "300750": [{"name": "永赢景气精选主动管理ETF", "shares": 500000, "pct": 0.4, "value": 9800}],
    "601012": [{"name": "易方达品质未来主动管理ETF", "shares": 2100000, "pct": 1.8, "value": 3200}],
    "300274": [{"name": "华夏质量价值甄选主动管理ETF", "shares": 640000, "pct": 0.7, "value": 5600}],
    "601899": [{"name": "国泰金鹰增长", "shares": 900000, "pct": 0.5, "value": 1660}],
    "002594": [{"name": "鹏华优质回报两年定开混合", "shares": 430000, "pct": 0.3, "value": 11500}],
}

FINANCE = {
    "600038": _row(_i("600038"), mgwfplr=3.21, yffy=19.4, mgjzc=21.43, jbmgsy=0.86, xsmlv=18.2, jlv=6.1, zgb=59.0, ysltag=48.2),
    "600893": _row(_i("600893"), mgwfplr=2.04, yffy=32.3, mgjzc=15.07, jbmgsy=0.59, xsmlv=16.8, jlv=4.2, zgb=266.4, ysltag=266.4),
    "000725": _row(_i("000725"), mgwfplr=1.12, yffy=110.5, mgjzc=4.55, jbmgsy=0.26, xsmlv=15.0, jlv=3.3, zgb=3769.0, ysltag=3769.0),
    "002230": _row(_i("002230"), mgwfplr=4.88, yffy=38.9, mgjzc=9.51, jbmgsy=0.85, xsmlv=41.2, jlv=8.7, zgb=232.5, ysltag=212.0),
    "600129": _row(_i("600129"), mgwfplr=2.66, yffy=3.4, mgjzc=6.51, jbmgsy=0.88, xsmlv=52.0, jlv=11.4, zgb=55.7, ysltag=55.7),
    "601166": _row(_i("601166"), mgwfplr=8.12, yffy=0.0, mgjzc=20.47, jbmgsy=3.21, xsmlv=None, jlv=28.1, zgb=2077.0, ysltag=2077.0),
    "601012": _row(_i("601012"), mgwfplr=2.18, yffy=12.6, mgjzc=9.38, jbmgsy=0.84, xsmlv=14.2, jlv=5.1, zgb=757.0, ysltag=757.0),
    "002415": _row(_i("002415"), mgwfplr=6.44, yffy=82.1, mgjzc=9.08, jbmgsy=1.69, xsmlv=44.6, jlv=18.2, zgb=934.0, ysltag=870.0),
    "300274": _row(_i("300274"), mgwfplr=8.12, yffy=21.8, mgjzc=18.16, jbmgsy=3.62, xsmlv=28.4, jlv=12.6, zgb=207.0, ysltag=168.0),
    "601899": _row(_i("601899"), mgwfplr=4.02, yffy=6.8, mgjzc=9.01, jbmgsy=1.49, xsmlv=18.8, jlv=14.6, zgb=2636.0, ysltag=2636.0),
    "000001": _row(_i("000001"), mgwfplr=7.02, yffy=0.0, mgjzc=16.88, jbmgsy=1.98, xsmlv=None, jlv=24.6, zgb=1941.0, ysltag=1941.0),
    "600519": _row(_i("600519"), mgwfplr=82.4, yffy=3.1, mgjzc=168.2, jbmgsy=52.4, xsmlv=91.6, jlv=52.1, zgb=125.6, ysltag=125.6),
    "300750": _row(_i("300750"), mgwfplr=18.6, yffy=86.2, mgjzc=32.4, jbmgsy=8.76, xsmlv=22.4, jlv=12.8, zgb=440.0, ysltag=380.0),
    "688001": _row(_i("688001"), mgwfplr=1.88, yffy=2.4, mgjzc=8.12, jbmgsy=0.71, xsmlv=38.5, jlv=9.2, zgb=44.1, ysltag=18.6),
    "000768": _row(_i("000768"), mgwfplr=2.44, yffy=21.8, mgjzc=9.76, jbmgsy=0.72, xsmlv=14.6, jlv=4.8, zgb=277.0, ysltag=277.0),
    "000858": _row(_i("000858"), mgwfplr=22.8, yffy=1.6, mgjzc=36.2, jbmgsy=7.82, xsmlv=74.2, jlv=36.8, zgb=388.0, ysltag=388.0),
    "601318": _row(_i("601318"), mgwfplr=18.6, yffy=0.0, mgjzc=41.8, jbmgsy=4.08, xsmlv=None, jlv=16.4, zgb=1821.0, ysltag=1083.0),
    "688981": _row(_i("688981"), mgwfplr=1.12, yffy=48.6, mgjzc=25.4, jbmgsy=1.48, xsmlv=21.8, jlv=8.6, zgb=797.0, ysltag=196.0),
    "300760": _row(_i("300760"), mgwfplr=14.8, yffy=26.4, mgjzc=33.5, jbmgsy=7.04, xsmlv=64.2, jlv=32.1, zgb=121.0, ysltag=90.0),
    "002594": _row(_i("002594"), mgwfplr=22.4, yffy=262.0, mgjzc=65.4, jbmgsy=12.4, xsmlv=20.8, jlv=5.6, zgb=291.0, ysltag=174.0),
    "000063": _row(_i("000063"), mgwfplr=5.66, yffy=214.0, mgjzc=14.6, jbmgsy=1.66, xsmlv=36.2, jlv=7.8, zgb=478.0, ysltag=401.0),
    "830799": _row(_i("830799"), mgwfplr=1.48, yffy=1.2, mgjzc=5.54, jbmgsy=0.42, xsmlv=48.6, jlv=12.2, zgb=16.8, ysltag=8.4),
    "833533": _row(_i("833533"), mgwfplr=0.88, yffy=0.6, mgjzc=5.81, jbmgsy=0.42, xsmlv=22.4, jlv=8.8, zgb=12.4, ysltag=6.2),
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
    "601012": (15.20, 14.50, 22.0),
    "002415": (28.35, 22.4, 41.6),
    "300274": (88.60, 42.0, 96.0),
    "601899": (18.46, 12.2, 21.8),
    "000001": (11.52, 9.8, 14.2),
    "600519": (1482.0, 1180.0, 1890.0),
    "300750": (198.4, 140.0, 260.0),
    "688001": (32.18, 22.5, 41.0),
    "000768": (27.65, 18.6, 34.0),
    "000858": (128.40, 96.0, 168.0),
    "601318": (48.16, 36.4, 58.2),
    "688981": (86.20, 48.6, 92.0),
    "300760": (228.00, 180.0, 310.0),
    "002594": (268.50, 190.0, 340.0),
    "000063": (32.46, 22.8, 44.0),
    "430017": (8.46, 6.2, 11.3),
    "830799": (12.08, 8.8, 15.4),
    "833533": (15.33, 11.0, 19.2),
}
BARS = {code: _make_bars(c, lo, hi) for code, (c, lo, hi) in _BAR_SPEC.items()}


def _make_flow(close: float, kind: str) -> list[dict]:
    series = []
    base = abs(close) * 80000
    for i in range(25):
        d = date(2026, 9, 14) - timedelta(days=24 - i)
        if d.weekday() >= 5:
            continue
        if kind == "spike_in":
            net = base * (0.2 if i < 23 else 2.4)
        elif kind == "spike_out":
            net = -base * (0.2 if i < 23 else 2.8)
        else:
            net = base * 0.22
        inflow = net if net > 0 else 0
        outflow = -net if net < 0 else 0
        series.append(
            {
                "d": d.isoformat(),
                "net_in": round(net, 2),
                "main_in": round(abs(net) * 0.7, 2),
                "inflow": round(inflow, 2),
                "outflow": round(outflow, 2),
            }
        )
    return series


_FLOW_KIND = {
    "600038": "spike_in",
    "000725": "spike_in",
    "601012": "spike_in",
    "300274": "spike_in",
    "002415": "spike_out",
    "601166": "calm",
    "000001": "calm",
    "601318": "calm",
}
FLOW = {code: _make_flow(close, _FLOW_KIND.get(code, "calm")) for code, (close, _lo, _hi) in _BAR_SPEC.items()}

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
    "601899": {
        "dividends": [{"date": "2026-09-05", "s": 0, "z": 0, "x": 1.0, "name": "每10股派1.0元"}],
        "seo": [],
        "unlock": [{"date": "2026-09-12", "name": "首发解禁"}],
    },
    "300750": {
        "dividends": [{"date": "2026-09-03", "s": 0, "z": 0, "x": 12.0, "name": "每10股派12元"}],
        "seo": [],
        "unlock": [],
    },
    "688981": {
        "dividends": [],
        "seo": [{"date": "2026-09-09", "name": "科创板再融资"}],
        "unlock": [{"date": "2026-09-11", "name": "战略配售解禁"}],
    },
}

# Applied by bootstrap only when the watch row still has an empty card.
CARD_SEED = {
    "600038": {
        "group": "观察",
        "thesis": "直升机主机厂，现价靠近减仓区，用来验接近减仓提醒",
        "cost": 25.0,
        "shares": 2000,
        "buy_low": 24.0,
        "buy_high": 26.0,
        "reduce_price": 27.8,
        "invalid_if": "主机订单连续两季下滑",
    },
    "600129": {
        "group": "自选",
        "thesis": "中药主业，买区尚未触及",
        "cost": 15.8,
        "shares": 800,
        "buy_low": 14.2,
        "buy_high": 15.6,
        "reduce_price": 22.0,
        "invalid_if": "集采大幅降价",
    },
    "601012": {
        "group": "备选",
        "thesis": "光伏周期底部附近，用来验接近底部提醒",
        "cost": 16.5,
        "shares": 1500,
        "buy_low": 14.4,
        "buy_high": 15.8,
        "reduce_price": 21.0,
        "invalid_if": "产能出清失败",
    },
}

# Used when data/export_share.csv is missing. 600038 stays empty so the
# "no manual row" path remains testable.
EXPORT_SHARE = {
    "000725": {"export_pct": "18", "overseas_pct": "22", "note": "显示面板出口"},
    "300750": {"export_pct": "41", "overseas_pct": "55", "note": "动力电池出海"},
    "601899": {"export_pct": "36", "overseas_pct": "48", "note": "矿产贸易"},
    "002415": {"export_pct": "52", "overseas_pct": "60", "note": "安防设备出口"},
    "002594": {"export_pct": "28", "overseas_pct": "35", "note": "整车出口"},
}
