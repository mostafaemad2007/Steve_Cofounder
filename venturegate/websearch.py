"""Live web search for evidence. Free, no API key, no paid service.

For each research step Steve's agent asks for a few short search queries. This module:

1. searches the web: a SearXNG instance if SEARXNG_URL is set, otherwise DuckDuckGo's plain HTML
   results page, with Wikipedia's search API as a fallback when a search returns nothing;
2. downloads the top results (HTML or plain text only, robots.txt respected, size and time capped,
   login-walled social sites skipped) and extracts their readable text;
3. ranks excerpts from those pages (plus any pages saved in sources/) and returns them labelled
   [S1]..[Sn]. The model can only cite those labels; code maps them back to the URLs it fetched,
   so a link can never be invented;
4. keeps the excerpts it showed the model in replay/search/, so a recorded run can be replayed
   exactly and anyone can check what each citation was based on. Whole pages are not kept.

Every search is logged to decision_log.json with the URLs that were actually read.
"""
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from . import config
from .logger import DecisionLogger, is_url, now_iso
from .sources import Excerpt, Source, SourceLibrary, html_to_text

USER_AGENT = ("Mozilla/5.0 (compatible; VentureGate-Steve/0.1; open-source research assistant; "
              "+https://github.com/mostafaemad2007/Steve_Cofounder)")
MAX_BYTES = 2_000_000
MIN_PAGE_CHARS = 200
SKIP_DOMAINS = ("youtube.com", "youtu.be", "facebook.com", "instagram.com", "tiktok.com", "twitter.com", "x.com",
                "pinterest.com", "linkedin.com", "reddit.com/login", "duckduckgo.com", "google.com/search")

Getter = Callable[..., tuple[int, str, str]]


def http_get(url: str, *, data: dict | None = None, timeout: float = 15.0) -> tuple[int, str, str]:
    """(status, content type, text). Raises OSError / URLError on network failure."""
    body = urllib.parse.urlencode(data).encode() if data else None
    request = urllib.request.Request(url, data=body, headers={
        "User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9,application/json;q=0.8",
        "Accept-Language": "en,ar;q=0.8"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES)
            ctype = response.headers.get("Content-Type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, ctype, raw.decode(charset, "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", ""


# == search providers =========================================================
class _DuckDuckGoParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results, self._href, self._title = [], None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and "result__a" in (a.get("class") or ""):
            self._href, self._title = a.get("href", ""), []

    def handle_data(self, data):
        if self._href is not None:
            self._title.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.results.append((self._href, " ".join("".join(self._title).split())))
            self._href = None


def _real_url(href: str) -> str | None:
    href = (href or "").strip()
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if "duckduckgo.com" in parsed.netloc:
        if parsed.path.startswith("/y.js"):                       # sponsored result
            return None
        target = urllib.parse.parse_qs(parsed.query).get("uddg", [None])[0]
        return target if target and is_url(target) else None
    return href if is_url(href) else None


def parse_duckduckgo(html: str) -> list[tuple[str, str]]:
    parser = _DuckDuckGoParser()
    parser.feed(html)
    out = []
    for href, title in parser.results:
        url = _real_url(href)
        if url and url not in [u for u, _ in out]:
            out.append((url, title or url))
    return out


def search_duckduckgo(query: str, n: int, get: Getter) -> list[tuple[str, str]]:
    status, _, text = get("https://html.duckduckgo.com/html/", data={"q": query, "kl": "wt-wt"}, timeout=15)
    return parse_duckduckgo(text)[:n] if status == 200 else []


def search_searxng(base: str, query: str, n: int, get: Getter) -> list[tuple[str, str]]:
    url = f"{base.rstrip('/')}/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
    status, _, text = get(url, timeout=15)
    if status != 200:
        return []
    data = json.loads(text or "{}")
    return [(r["url"], r.get("title") or r["url"]) for r in data.get("results", []) if is_url(r.get("url"))][:n]


def search_wikipedia(query: str, n: int, get: Getter) -> list[tuple[str, str]]:
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "list": "search", "srsearch": query, "srlimit": n, "format": "json"})
    status, _, text = get(url, timeout=15)
    if status != 200:
        return []
    hits = json.loads(text or "{}").get("query", {}).get("search", [])
    return [("https://en.wikipedia.org/wiki/" + urllib.parse.quote(h["title"].replace(" ", "_")), h["title"])
            for h in hits]


# == the library ==============================================================
def _key(queries: list[str], k: int) -> str:
    return hashlib.sha256(json.dumps([queries, k]).encode()).hexdigest()[:16]


class WebSourceLibrary:
    """Same interface as SourceLibrary (relevant, __len__, notices), backed by live search."""

    live = True

    def __init__(self, *, mode: str = "live", logger: DecisionLogger | None = None, cache_dir: Path | None = None,
                 saved: SourceLibrary | None = None, results_per_query: int | None = None, get: Getter = http_get,
                 searxng_url: str | None = None, check_robots: bool = True):
        self.mode = mode
        self.logger = logger or DecisionLogger()
        self.cache_dir = Path(cache_dir) if cache_dir else config.path("REPLAY_DIR", "replay") / "search"
        self.saved = saved if saved is not None else SourceLibrary()
        self.n = results_per_query or int(config.get("SEARCH_RESULTS_PER_QUERY", "4"))
        self.get = get
        self.searxng_url = searxng_url if searxng_url is not None else config.get("SEARXNG_URL", "")
        self.check_robots = check_robots
        self.notices: list[str] = []
        self.pages: dict[str, Source] = {}       # url -> page read in this run
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.searches = 0

    def __len__(self) -> int:
        return len(self.saved) + len(self.pages)

    def _notice(self, text: str) -> None:
        if text not in self.notices:
            self.notices.append(text)

    # -- searching ----------------------------------------------------------
    def search(self, query: str) -> tuple[str, list[tuple[str, str]]]:
        providers = []
        if self.searxng_url:
            providers.append(("searxng", lambda q: search_searxng(self.searxng_url, q, self.n, self.get)))
        providers += [("duckduckgo", lambda q: search_duckduckgo(q, self.n, self.get)),
                      ("wikipedia", lambda q: search_wikipedia(q, self.n, self.get))]
        for name, provider in providers:
            try:
                results = [(u, t) for u, t in provider(query) if not any(d in u for d in SKIP_DOMAINS)]
            except (OSError, urllib.error.URLError, ValueError) as exc:
                self.logger.log("research", "search_provider_failed", provider=name, error=str(exc)[:160])
                continue
            if results:
                return name, results
        return "none", []

    # -- reading pages --------------------------------------------------------
    def _allowed(self, url: str) -> bool:
        if not self.check_robots:
            return True
        parts = urllib.parse.urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = None
            try:
                status, _, text = self.get(origin + "/robots.txt", timeout=5)
                if status == 200 and text:
                    parser = urllib.robotparser.RobotFileParser()
                    parser.parse(text.splitlines())
            except (OSError, urllib.error.URLError, ValueError):
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        return parser is None or parser.can_fetch("VentureGate-Steve", url)

    def fetch(self, url: str, title: str) -> Source | None:
        if url in self.pages:
            return self.pages[url]
        if not self._allowed(url):
            return None
        try:
            status, ctype, text = self.get(url, timeout=12)
        except (OSError, urllib.error.URLError, ValueError):
            return None
        if status != 200 or not text:
            return None
        if "html" in ctype or "<html" in text[:2000].lower():
            page_title, body = html_to_text(text)
        elif ctype.startswith("text/plain"):
            page_title, body = "", text
        else:
            return None                                             # PDFs, images, binaries
        body = body.strip()
        if len(body) < MIN_PAGE_CHARS:
            return None
        source = Source(url=url, title=(page_title or title or url)[:160], text=body[:40_000], file="web")
        self.pages[url] = source
        return source

    # -- the interface agents use ---------------------------------------------
    def relevant(self, query, k: int = 6, per_source: int = 2) -> list[Excerpt]:
        queries = [q for q in ([query] if isinstance(query, str) else list(query)) if q and q.strip()]
        if not queries:
            return []
        path = self.cache_dir / f"{_key(queries, k)}.json"
        if self.mode == "replay":
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                return [Excerpt(x["sid"], Source(x["url"], x["title"], "", "web"), x["text"]) for x in data["excerpts"]]
            self._notice("[REPLAY MODE] no recorded web search for this step, so only saved pages are used.")
            return self.saved.relevant(queries, k=k, per_source=per_source)

        found, providers = [], set()
        for q in queries:
            provider, results = self.search(q)
            providers.add(provider)
            self.searches += 1
            for url, title in results:
                if url not in [u for u, _ in found]:
                    found.append((url, title))
        with ThreadPoolExecutor(max_workers=6) as pool:
            pages = [p for p in pool.map(lambda r: self.fetch(*r), found) if p]
        if not pages:
            self._notice("Web search returned no readable pages (no internet, or the search was blocked). "
                         "Claims from these steps are labelled ASSUMPTION unless saved pages cover them.")
        library = SourceLibrary(sources=pages + self.saved.sources)
        excerpts = library.relevant(queries, k=k, per_source=per_source)
        read = [p.url for p in pages]
        self.logger.log("research", "web_search", sources=read, queries=queries,
                        provider="+".join(sorted(providers)), results=len(found), pages_read=len(pages))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"queries": queries, "searched_at": now_iso(), "excerpts": [
            {"sid": x.sid, "url": x.source.url, "title": x.source.title, "text": x.text} for x in excerpts]},
            indent=1, ensure_ascii=False), encoding="utf-8")
        return excerpts


def default_library(mode: str, logger: DecisionLogger):
    """The evidence source for a run: live web search (default) or saved pages only (WEB_SEARCH=false)."""
    if config.get("WEB_SEARCH", "true").lower() in ("0", "false", "no", "off"):
        return SourceLibrary()
    return WebSourceLibrary(mode=mode, logger=logger)
