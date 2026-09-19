from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    group: str
    requires: tuple[str, ...] = ()
    alertable: str | None = None
    realtime: bool = False
    default: bool = True


class FieldRegistry:
    def __init__(self) -> None:
        self._items: dict[str, FieldSpec] = {}

    def register(self, spec: FieldSpec) -> FieldSpec:
        self._items[spec.key] = spec
        return spec

    def get(self, key: str) -> FieldSpec:
        return self._items[key]

    def all(self) -> list[FieldSpec]:
        return list(self._items.values())

    def default_keys(self) -> list[str]:
        return [s.key for s in self._items.values() if s.default]

    def alertable(self) -> list[FieldSpec]:
        return [s for s in self._items.values() if s.alertable]


registry = FieldRegistry()

NAME = registry.register(FieldSpec("name", "名称", "meta"))
CODE = registry.register(FieldSpec("code", "代码", "meta"))
PRICE = registry.register(FieldSpec("price", "最新价", "quote", ("quote",), alertable="threshold", realtime=True))
PCT = registry.register(FieldSpec("pct", "涨跌幅", "quote", ("quote",), alertable="threshold", realtime=True))
INDUSTRY = registry.register(FieldSpec("industry", "所属行业", "profile", ("profile",)))
SECTOR = registry.register(FieldSpec("sector", "七大板块", "profile", ("profile",)))
SW_L1 = registry.register(FieldSpec("sw_l1", "申万一级", "profile", ("profile",)))
HOT = registry.register(FieldSpec("hot_concepts", "2026概念", "profile", ("profile",)))
CONCEPT = registry.register(FieldSpec("concept", "所属概念/板块", "profile", ("profile",)))
BUSINESS = registry.register(FieldSpec("business", "主营业务/经营范围", "profile", ("profile",)))
HOLDERS = registry.register(FieldSpec("holders", "前十大流通股东", "holders", ("holders",)))
TOP_HOLDERS = registry.register(FieldSpec("top_holders", "前十大股东", "holders", ("holders",)))
ZGB = registry.register(FieldSpec("zgb", "总股本", "finance", ("finance",)))
LTGB = registry.register(FieldSpec("ltgb", "流通股本", "finance", ("finance",)))
MGWFPLR = registry.register(FieldSpec("mgwfplr", "每股未分配利润", "finance", ("finance",)))
YFFY = registry.register(FieldSpec("yffy", "研发费用", "finance", ("finance",)))
MGJZC = registry.register(FieldSpec("mgjzc", "每股净资产", "finance", ("finance",)))
EPS = registry.register(FieldSpec("eps", "每股收益", "finance", ("finance",)))
PE = registry.register(FieldSpec("pe", "市盈率", "quote", ("quote",), alertable="threshold"))
GROSS = registry.register(FieldSpec("gross", "毛利率", "finance", ("finance",)))
NET = registry.register(FieldSpec("net", "净利率", "finance", ("finance",)))
FLOW_IN = registry.register(FieldSpec("flow_in", "资金流入", "flow", ("flow",)))
FLOW_OUT = registry.register(FieldSpec("flow_out", "资金流出", "flow", ("flow",)))
FLOW_NET = registry.register(FieldSpec("flow_net", "净流入", "flow", ("flow",), alertable="threshold"))
NORTH = registry.register(FieldSpec("northbound", "北向资金", "flow", ()))
PB = registry.register(FieldSpec("pb", "市净率", "quote", ("quote",), alertable="threshold"))
LOW1Y = registry.register(FieldSpec("low1y", "近1年底", "bottom", ("quote", "bars")))
LOW_LONG = registry.register(FieldSpec("low_long", "长窗底", "bottom", ("quote", "bars")))
HIGH = registry.register(FieldSpec("high", "顶", "bottom", ("quote", "bars")))
OFF_LOW = registry.register(FieldSpec("off_low", "离底%", "bottom", ("quote", "bars"), alertable="threshold", realtime=True))
MULTIPLE = registry.register(FieldSpec("multiple", "顶底倍", "bottom", ("quote", "bars"), alertable="threshold"))
TARGET = registry.register(FieldSpec("target", "目标卖价", "bottom", ("quote", "bars"), alertable="threshold"))
LOW_NOTE = registry.register(FieldSpec("low_note", "底部口径", "bottom", ("quote", "bars")))
BUY_LOW = registry.register(FieldSpec("buy_low", "买区低", "card", default=False, alertable="card"))
BUY_HIGH = registry.register(FieldSpec("buy_high", "买区高", "card", default=False, alertable="card"))
REDUCE_AT = registry.register(FieldSpec("reduce_at", "减仓价", "card", default=False, alertable="card"))
COST = registry.register(FieldSpec("cost", "成本", "card", default=False, alertable="card"))
VS_COST = registry.register(FieldSpec("vs_cost", "相对成本%", "card", ("quote",), default=False, alertable="threshold", realtime=True))
DIST_BUY = registry.register(FieldSpec("dist_buy", "距买区%", "card", ("quote",), default=False, alertable="threshold", realtime=True))
DIST_REDUCE = registry.register(FieldSpec("dist_reduce", "距减仓区%", "card", ("quote", "bars"), default=False, alertable="threshold", realtime=True))
THESIS = registry.register(FieldSpec("thesis", "持有逻辑", "card", default=False))
