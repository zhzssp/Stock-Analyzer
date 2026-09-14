from __future__ import annotations

import json
from typing import Any

import httpx

from src.config import settings
from src.market import fixtures
from src.market.normalize import Instrument, code6_of, normalize_instrument


class MarketError(RuntimeError):
    pass


class MarketClient:
    """Only module allowed to talk to Mairui.

    Demo licence responses are never persisted as live cache.
    """

    def __init__(self) -> None:
        self.offline = settings.mairui_offline or not settings.mairui_licence
        self.licence = settings.mairui_licence.strip()
        self.sample_only = False
        self.status = "offline" if self.offline else "unchecked"
        if not self.offline:
            self._probe()

    def _url(self, path: str) -> str:
        return f"{settings.mairui_base}{path}/{self.licence}"

    def _get(self, path: str) -> Any:
        if self.offline:
            raise MarketError("offline mode: live API disabled")
        try:
            resp = httpx.get(self._url(path), timeout=30.0)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            raise MarketError(str(exc)) from exc

    def _probe(self) -> None:
        if self.licence == settings.demo_licence:
            self.sample_only = True
            self.status = "demo-licence"
            return
        prices = []
        for code in ("000001", "600038", "002230"):
            try:
                data = httpx.get(self._url(f"/hsrl/ssjy/{code}"), timeout=20.0).json()
                row = data[0] if isinstance(data, list) else data
                prices.append(row.get("p"))
            except Exception:
                prices.append("ERR")
        distinct = {p for p in prices if p not in (None, "ERR")}
        if len(distinct) <= 1:
            self.sample_only = True
            self.status = "sample-only"
        else:
            self.status = "live"

    def _cache_get(self, key: str) -> Any | None:
        if self.sample_only:
            return None
        path = settings.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _cache_put(self, key: str, payload: Any) -> None:
        if self.sample_only or self.offline:
            return
        path = settings.cache_dir / f"{key}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def health(self) -> dict:
        return {
            "offline": self.offline,
            "sample_only": self.sample_only,
            "status": self.status,
            "has_licence": bool(self.licence),
        }

    def list_hs(self) -> list[Instrument]:
        if self.offline:
            return list(fixtures.UNIVERSE_HS)
        cached = self._cache_get("list_hs")
        if cached:
            return [normalize_instrument(x["dm"], x.get("mc", ""), x.get("jys", "")) for x in cached]
        data = self._get("/hslt/list")
        if isinstance(data, list) and not self.sample_only:
            self._cache_put("list_hs", data)
        return [normalize_instrument(x.get("dm", ""), x.get("mc", ""), x.get("jys", "")) for x in data]

    def search(self, q: str = "", market: str = "all", limit: int = 50) -> list[dict]:
        items = self.list_hs() + self.list_bj()
        market = (market or "all").lower()
        if market == "hs":
            items = [i for i in items if i.market == "hs"]
        elif market == "kc":
            items = [i for i in items if i.market == "kc"]
        elif market == "bj":
            items = [i for i in items if i.market == "bj"]
        elif market == "sh":
            items = [i for i in items if i.exchange == "SH"]
        elif market == "sz":
            items = [i for i in items if i.exchange == "SZ"]
        elif market == "cy":
            items = [i for i in items if i.code6.startswith("300")]
        needle = (q or "").strip().lower()
        out = []
        for inst in items:
            industry = fixtures.INDUSTRY.get(inst.code6, "")
            hay = f"{inst.name} {inst.code6} {inst.code_full} {industry}".lower()
            if needle and needle not in hay:
                continue
            out.append(
                {
                    "code6": inst.code6,
                    "code_full": inst.code_full,
                    "name": inst.name,
                    "market": inst.market,
                    "industry": industry,
                }
            )
            if len(out) >= limit:
                break
        return out

    def list_exchange(self, exchange: str) -> list[Instrument]:
        key = (exchange or "").lower()
        if key == "bj":
            return self.list_bj()
        items = self.list_hs()
        if key == "sh":
            return [i for i in items if i.exchange == "SH"]
        if key == "sz":
            return [i for i in items if i.exchange == "SZ"]
        raise MarketError(f"未知交易所: {exchange}")

    def list_board(self, board: str) -> list[Instrument]:
        key = (board or "").lower()
        items = self.list_hs()
        if key == "cy":
            return [i for i in items if i.code6.startswith("300")]
        if key == "kc":
            return [i for i in items if i.market == "kc"]
        raise MarketError(f"未知板块: {board}")

    def list_bj(self) -> list[Instrument]:
        if self.offline:
            return list(fixtures.UNIVERSE_BJ)
        cached = self._cache_get("list_bj")
        if cached:
            return [normalize_instrument(x["dm"], x.get("mc", ""), x.get("jys", "")) for x in cached]
        try:
            data = self._get("/bj/list/all")
        except MarketError:
            return []
        if isinstance(data, list) and not self.sample_only:
            self._cache_put("list_bj", data)
        return [normalize_instrument(x.get("dm", ""), x.get("mc", ""), x.get("jys", "")) for x in data]

    def quote(self, inst: Instrument) -> dict:
        if self.offline:
            return fixtures.QUOTE.get(inst.code6, {"source": "offline"})
        data = self._get(f"/hsrl/ssjy/{inst.code6}")
        row = data[0] if isinstance(data, list) else data
        return {"p": row.get("p"), "pc": row.get("pc"), "pe": row.get("pe"), "source": "live"}

    def profile(self, inst: Instrument) -> dict:
        if self.offline:
            return fixtures.PROFILE.get(inst.code6, {"source": "offline"})
        out = {"industry": "", "concept": "", "business": "", "source": "live"}
        try:
            zg = self._get(f"/hszg/zg/{inst.code6}")
            names = [x.get("name", "") for x in zg if isinstance(x, dict)]
            industries = [n for n in names if "申万" in n or "行业" in n]
            concepts = [n.split("-")[-1] for n in names if n]
            out["industry"] = industries[0].split("-")[-1] if industries else (concepts[0] if concepts else "")
            out["concept"] = ",".join(concepts[:6])
        except MarketError:
            pass
        try:
            info = self._get(f"/hscp/gsjj/{inst.code6}")
            row = info[0] if isinstance(info, list) else info
            out["business"] = row.get("bscope") or row.get("desc") or ""
            if row.get("idea"):
                out["concept"] = row["idea"]
        except MarketError:
            pass
        return out

    def holders(self, inst: Instrument) -> dict:
        if self.offline:
            return fixtures.HOLDERS.get(inst.code6, {"source": "offline"})
        try:
            data = self._get(f"/hsstock/financial/flowholder/{inst.code_full}")
        except MarketError:
            try:
                data = self._get(f"/hscp/ltgd/{inst.code6}")
            except MarketError:
                return {"holders": "", "holders_detail": [], "source": "live"}
        if not data:
            return {"holders": "", "holders_detail": [], "source": "live"}
        latest = data[0] if isinstance(data, list) else data
        detail = latest.get("sdgd") if isinstance(latest, dict) and "sdgd" in latest else data[:10]
        if not isinstance(detail, list):
            detail = []
        names = []
        for item in detail[:3]:
            names.append(str(item.get("Gdmc") or item.get("gdmc") or item.get("name") or ""))
        return {"holders": "、".join([n for n in names if n]) or "详见明细", "holders_detail": detail[:10], "source": "live"}

    def finance(self, inst: Instrument) -> dict:
        if self.offline:
            return fixtures.FINANCE.get(inst.code6, {"source": "offline"})
        out = {"source": "live"}
        try:
            psi = self._get(f"/hsstock/financial/pershareindex/{inst.code_full}")
            row = psi[0] if isinstance(psi, list) else psi
            for key in ("mgwfplr", "mgjzc", "jbmgsy", "xsmlv", "jlv"):
                out[key] = row.get(key)
        except MarketError:
            pass
        try:
            income = self._get(f"/hsstock/financial/income/{inst.code_full}")
            row = income[0] if isinstance(income, list) else income
            yffy = row.get("yffy")
            out["yffy"] = None if yffy in (None, "", "-", 0, "0") else yffy
        except MarketError:
            pass
        try:
            cap = self._get(f"/hsstock/financial/capital/{inst.code_full}")
            row = cap[0] if isinstance(cap, list) else cap
            out["zgb"] = row.get("zgb")
            out["ysltag"] = row.get("ysltag")
        except MarketError:
            try:
                inst_info = self._get(f"/hsstock/instrument/{inst.code_full}")
                row = inst_info[0] if isinstance(inst_info, list) else inst_info
                out["zgb"] = row.get("tv")
                out["ysltag"] = row.get("fv")
            except MarketError:
                pass
        return out


def resolve_instruments(codes: list[str], client: MarketClient) -> list[Instrument]:
    known = {i.code6: i for i in fixtures.WATCH_SEED}
    for item in client.list_hs() + client.list_bj():
        known[item.code6] = item
    out: list[Instrument] = []
    for raw in codes:
        key = code6_of(raw)
        if key in known:
            out.append(known[key])
        else:
            out.append(normalize_instrument(raw))
    return out
