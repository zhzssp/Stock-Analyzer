from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    group: str
    requires: tuple[str, ...] = ()


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
        return [s.key for s in self._items.values()]


registry = FieldRegistry()

NAME = registry.register(FieldSpec("name", "名称", "meta"))
CODE = registry.register(FieldSpec("code", "代码", "meta"))
PRICE = registry.register(FieldSpec("price", "最新价", "quote", ("quote",)))
PCT = registry.register(FieldSpec("pct", "涨跌幅", "quote", ("quote",)))
INDUSTRY = registry.register(FieldSpec("industry", "所属行业", "profile", ("profile",)))
CONCEPT = registry.register(FieldSpec("concept", "所属概念/板块", "profile", ("profile",)))
BUSINESS = registry.register(FieldSpec("business", "主营业务/经营范围", "profile", ("profile",)))
HOLDERS = registry.register(FieldSpec("holders", "前十大流通股东", "holders", ("holders",)))
ZGB = registry.register(FieldSpec("zgb", "总股本", "finance", ("finance",)))
LTGB = registry.register(FieldSpec("ltgb", "流通股本", "finance", ("finance",)))
MGWFPLR = registry.register(FieldSpec("mgwfplr", "每股未分配利润", "finance", ("finance",)))
YFFY = registry.register(FieldSpec("yffy", "研发费用", "finance", ("finance",)))
MGJZC = registry.register(FieldSpec("mgjzc", "每股净资产", "finance", ("finance",)))
EPS = registry.register(FieldSpec("eps", "每股收益", "finance", ("finance",)))
PE = registry.register(FieldSpec("pe", "市盈率", "quote", ("quote",)))
GROSS = registry.register(FieldSpec("gross", "毛利率", "finance", ("finance",)))
NET = registry.register(FieldSpec("net", "净利率", "finance", ("finance",)))
