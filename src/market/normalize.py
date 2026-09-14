from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    code6: str
    code_full: str
    name: str
    exchange: str
    market: str


def code6_of(code: str) -> str:
    return (code or "").split(".")[0].strip()


def infer_suffix(code6: str, jys: str = "") -> str:
    jys_u = (jys or "").upper()
    if jys_u in {"SH", "SZ", "BJ"}:
        return jys_u
    if code6.startswith(("5", "6", "9")):
        return "SH"
    if code6.startswith(("4", "8")):
        return "BJ"
    return "SZ"


def infer_market(code6: str, suffix: str) -> str:
    if suffix == "BJ" or code6.startswith(("4", "8")):
        return "bj"
    if code6.startswith(("688", "689")):
        return "kc"
    return "hs"


def normalize_instrument(dm: str, name: str = "", jys: str = "") -> Instrument:
    raw = (dm or "").strip()
    if "." in raw:
        code6, suffix = raw.split(".", 1)
        suffix = suffix.upper()
    else:
        code6 = raw
        suffix = infer_suffix(code6, jys)
    return Instrument(
        code6=code6,
        code_full=f"{code6}.{suffix}",
        name=name,
        exchange=suffix,
        market=infer_market(code6, suffix),
    )


def pick_code(inst: Instrument, style: str) -> str:
    return inst.code_full if style == "full" else inst.code6
