"""Whitelist URL fetch for monitor news/policy. No full-web search, no LLM."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
import socket
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree as ET

from src.config import settings

MAX_BYTES = 512 * 1024
TIMEOUT_SEC = 12
MAX_SOURCES = 20
MAX_FEED_ITEMS = 30
MAX_TEXT = 20_000
USER_AGENT = "Stock-Analyzer/local"

_BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal"}


@dataclass
class Document:
    url: str
    content_type: str
    body: bytes


@dataclass
class PageItem:
    title: str
    url: str
    text: str


@dataclass
class Hit:
    code6: str
    name: str
    source_name: str
    title: str
    url: str
    snippet: str
    needles: list[str] = field(default_factory=list)


class GuardRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(url: str) -> str:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("只支持 http/https 地址")
    if parsed.username or parsed.password:
        raise ValueError("地址不能带账号密码")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or host in _BLOCKED_HOSTS or host.endswith(".local"):
        raise ValueError("不允许的主机")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and _bad_ip(ip):
        raise ValueError("不允许访问内网地址")
    return raw


def _resolve_host(host: str, port: int) -> None:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("无法解析主机") from exc
    for item in infos:
        sockaddr = item[4]
        ip = ipaddress.ip_address(sockaddr[0])
        if _bad_ip(ip):
            raise ValueError("不允许访问内网地址")


def _bad_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def fetch_document(url: str) -> Document:
    checked = check_url(url)
    parsed = urlparse(checked)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    _resolve_host(parsed.hostname or "", port)
    req = Request(checked, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/rss+xml,application/xml,application/json,text/xml,*/*"})
    opener = build_opener(GuardRedirect)
    try:
        with opener.open(req, timeout=TIMEOUT_SEC) as resp:
            final = check_url(resp.geturl() or checked)
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            length = resp.headers.get("Content-Length")
            if length and int(length) > MAX_BYTES:
                raise ValueError("页面超过大小上限")
            chunks: list[bytes] = []
            total = 0
            while True:
                piece = resp.read(64 * 1024)
                if not piece:
                    break
                total += len(piece)
                if total > MAX_BYTES:
                    raise ValueError("页面超过大小上限")
                chunks.append(piece)
    except HTTPError as exc:
        raise ValueError(f"抓取失败 HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError("抓取失败") from exc
    except TimeoutError as exc:
        raise ValueError("抓取超时") from exc
    return Document(url=final, content_type=ctype, body=b"".join(chunks))


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._title = 0
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        elif tag == "title":
            self._title += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        elif tag == "title" and self._title:
            self._title -= 1

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._title:
            self.title_parts.append(text)
        elif not self._skip:
            self.body_parts.append(text)


def _decode(body: bytes) -> str:
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def _clip(text: str, n: int = MAX_TEXT) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    return cleaned[:n]


def _local(tag: str) -> str:
    return tag.split("}")[-1] if tag else ""


def _child_text(node: ET.Element, names: set[str]) -> str:
    for child in list(node):
        if _local(child.tag) in names:
            if child.text and child.text.strip():
                return html.unescape(child.text.strip())
            href = child.attrib.get("href") or child.attrib.get("url")
            if href:
                return href
    return ""


def parse_items(doc: Document, fmt: str = "auto") -> list[PageItem]:
    text = _decode(doc.body)
    kind = (fmt or "auto").lower()
    sniff = kind
    if sniff == "auto":
        ctype = doc.content_type
        head = text.lstrip()[:200].lower()
        if "json" in ctype or head.startswith("{") or head.startswith("["):
            sniff = "json"
        elif "rss" in ctype or "xml" in ctype or "<rss" in head or "<feed" in head:
            sniff = "rss"
        else:
            sniff = "html"
    if sniff == "json":
        return _parse_json(text, doc.url)
    if sniff == "rss":
        return _parse_rss(text, doc.url)
    parser = _HTMLText()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        pass
    title = _clip(" ".join(parser.title_parts), 180) or doc.url
    body = _clip(" ".join(parser.body_parts))
    return [PageItem(title=title, url=doc.url, text=body)]


def _parse_rss(text: str, base: str) -> list[PageItem]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [PageItem(title=base, url=base, text=_clip(re.sub(r"<[^>]+>", " ", text)))]
    nodes = [n for n in root.iter() if _local(n.tag) in {"item", "entry"}]
    out: list[PageItem] = []
    for node in nodes[:MAX_FEED_ITEMS]:
        title = _child_text(node, {"title"}) or base
        link = _child_text(node, {"link", "id", "guid"})
        try:
            href = check_url(urljoin(base, link or base))
        except ValueError:
            href = base
        summary = _child_text(node, {"description", "summary", "content"})
        summary = _clip(re.sub(r"<[^>]+>", " ", html.unescape(summary)))
        out.append(PageItem(title=_clip(title, 180), url=href, text=summary))
    return out or [PageItem(title=base, url=base, text=_clip(re.sub(r"<[^>]+>", " ", text)))]


def _parse_json(text: str, base: str) -> list[PageItem]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [PageItem(title=base, url=base, text=_clip(text))]
    rows: list
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("items") or data.get("data") or data.get("entries") or [data]
        if not isinstance(rows, list):
            rows = [data]
    else:
        return [PageItem(title=base, url=base, text=_clip(text))]
    out: list[PageItem] = []
    for row in rows[:MAX_FEED_ITEMS]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("name") or base)
        link = str(row.get("url") or row.get("link") or row.get("href") or base)
        try:
            href = check_url(urljoin(base, link))
        except ValueError:
            href = base
        body = str(row.get("content") or row.get("summary") or row.get("description") or row.get("text") or "")
        out.append(PageItem(title=_clip(title, 180), url=href, text=_clip(body)))
    return out or [PageItem(title=base, url=base, text=_clip(text))]


def split_keywords(raw: str | list | None) -> list[str]:
    if isinstance(raw, list):
        parts = [str(x) for x in raw]
    else:
        parts = re.split(r"[,，、\s]+", str(raw or ""))
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        token = part.strip()
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def normalize_sources(raw, *, strict: bool = True) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    seen_url: set[str] = set()
    for item in raw[:MAX_SOURCES]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:64]
        url = str(item.get("url") or "").strip()[:512]
        if not name or not url:
            continue
        try:
            check_url(url)
        except ValueError:
            if strict:
                raise
            continue
        if url in seen_url:
            continue
        seen_url.add(url)
        kind = str(item.get("kind") or "news").strip().lower()
        if kind not in {"news", "policy", "both"}:
            kind = "news"
        fmt = str(item.get("format") or item.get("fetch") or "auto").strip().lower()
        if fmt not in {"auto", "html", "rss", "json"}:
            fmt = "auto"
        keywords = split_keywords(item.get("keywords"))
        enabled = item.get("enabled")
        sid = str(item.get("id") or hashlib.sha1(url.encode("utf-8")).hexdigest()[:12])
        out.append(
            {
                "id": sid[:24],
                "name": name,
                "url": url,
                "kind": kind,
                "format": fmt,
                "keywords": keywords,
                "enabled": False if enabled in {0, False, "0", "false"} else True,
            }
        )
    return out


def enabled_kinds(sources: list[dict]) -> set[str]:
    kinds: set[str] = set()
    for src in sources:
        if not src.get("enabled"):
            continue
        kind = src.get("kind") or "news"
        if kind == "policy":
            kinds.add("policy")
        elif kind == "both":
            kinds.add("news")
            kinds.add("policy")
        else:
            kinds.add("news")
    return kinds


def evidence_dir(user_id: int) -> Path:
    path = settings.data_dir / "web_sources" / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_evidence(user_id: int, url: str, title: str, text: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    path = evidence_dir(user_id) / f"{date.today().isoformat()}_{digest}.json"
    path.write_text(
        json.dumps({"url": url, "title": title, "text": text[:4000]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def snippet_around(text: str, needles: list[str], width: int = 80) -> str:
    hay = text or ""
    for needle in needles:
        idx = hay.find(needle)
        if idx >= 0:
            start = max(0, idx - width // 2)
            end = min(len(hay), idx + len(needle) + width // 2)
            return hay[start:end].strip()
    return hay[:width].strip()


def watch_needles(name: str, code6: str, industry: str = "", hot: str = "") -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in [name, code6, *(split_keywords(hot)), industry]:
        token = (token or "").strip()
        if token == code6:
            if len(token) == 6 and token not in seen:
                seen.add(token)
                out.append(token)
            continue
        if len(token) < 2 or token in seen:
            continue
        if token == industry and len(token) < 3:
            continue
        seen.add(token)
        out.append(token)
    return out


def match_item(item: PageItem, extra_kw: list[str], watches: list[tuple[str, str, list[str]]]) -> list[Hit]:
    hay = f"{item.title} {item.text}"
    if extra_kw and not any(k in hay for k in extra_kw):
        return []
    hits: list[Hit] = []
    for code6, name, needles in watches:
        found = [n for n in needles if n and n in hay]
        strong = [n for n in found if n == name or n == code6]
        weak = [n for n in found if n not in strong]
        if not strong and not weak:
            continue
        chosen = strong or weak
        hits.append(
            Hit(
                code6=code6,
                name=name,
                source_name="",
                title=item.title,
                url=item.url,
                snippet=snippet_around(hay, chosen),
                needles=chosen,
            )
        )
    if any(h.needles and (h.name in h.needles or h.code6 in h.needles) for h in hits):
        return [h for h in hits if h.name in h.needles or h.code6 in h.needles]
    return hits


def scan_sources(
    sources: list[dict],
    job_key: str,
    watches: list[tuple[str, str, list[str]]],
    user_id: int,
    fetch: Callable[[str], Document] | None = None,
) -> list[Hit]:
    getter = fetch or fetch_document
    out: list[Hit] = []
    for src in sources:
        if not src.get("enabled"):
            continue
        kind = src.get("kind") or "news"
        if job_key == "news" and kind == "policy":
            continue
        if job_key == "policy" and kind == "news":
            continue
        try:
            doc = getter(src["url"])
            pages = parse_items(doc, str(src.get("format") or "auto"))
        except (ValueError, OSError):
            continue
        for page in pages:
            try:
                write_evidence(user_id, page.url, page.title, page.text)
            except OSError:
                pass
            matched = match_item(page, src.get("keywords") or [], watches)
            for hit in matched:
                hit.source_name = str(src.get("name") or "")
                out.append(hit)
    return out
