"""TEST-ONLY simulated internet for the web search tests. No real network is used."""
import urllib.parse

PAGE_TEXT = ("CV templates competitors pricing price graduates Egypt engineering students tech jobs hosting domain "
             "month cost trademark licence terms copyright fonts free alternatives market chatbot app. ") * 6


def ddg_page(urls):
    links = "".join(
        f'<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg='
        f'{urllib.parse.quote(u, safe="")}&amp;rut=abc">Result {i}</a></div>' for i, u in enumerate(urls))
    ad = '<a class="result__a" href="https://duckduckgo.com/y.js?ad_domain=x.com&amp;u3=1">Sponsored</a>'
    return f"<html><body>{ad}{links}</body></html>"


class FakeWeb:
    """get(url, data=None, timeout=...) like websearch.http_get. Pages live at https://site<N>.test/page."""

    def __init__(self, *, ddg=True, wikipedia=True, pages=4, blocked_robots=(), extra=None, down=False):
        self.ddg, self.wikipedia, self.n_pages, self.down = ddg, wikipedia, pages, down
        self.blocked_robots, self.extra = set(blocked_robots), dict(extra or {})
        self.calls: list[str] = []

    def __call__(self, url, data=None, timeout=15):
        self.calls.append(url)
        if self.down:
            raise OSError("network unreachable")
        if url in self.extra:
            return self.extra[url]
        if url.startswith("https://html.duckduckgo.com"):
            urls = [f"https://site{i}.test/page" for i in range(1, self.n_pages + 1)]
            return (200, "text/html", ddg_page(urls)) if self.ddg else (200, "text/html", "<html>no results</html>")
        if url.startswith("https://en.wikipedia.org/w/api.php"):
            hits = [{"title": "Curriculum vitae"}] if self.wikipedia else []
            return 200, "application/json", '{"query": {"search": %s}}' % str(hits).replace("'", '"')
        if url.endswith("/robots.txt"):
            host = urllib.parse.urlparse(url).netloc
            if host in self.blocked_robots:
                return 200, "text/plain", "User-agent: *\nDisallow: /"
            return 404, "", ""
        if url.startswith("https://en.wikipedia.org/wiki/") or ".test/" in url:
            title = url.rsplit("/", 2)[-2]
            return 200, "text/html; charset=utf-8", (f"<html><head><title>{title}</title><script>x()</script></head>"
                                                     f"<body><nav>Menu</nav><p>{PAGE_TEXT}</p></body></html>")
        return 404, "", ""
