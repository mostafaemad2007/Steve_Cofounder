"""MVP builder for content-type digital products: template packs, guides, checklists, toolkits.

The build agent writes the product content; this module turns it into a working, self-contained
HTML product page with a downloadable Markdown bundle and user docs, then runs automatic tests on
the result (Gate 3 needs them all to pass).

All model text is HTML-escaped before rendering, so content containing <script> or other markup is
shown as text and can never run. Software MVPs beyond a static page are STUBBED: the plan describes
them, nothing is generated.
"""
import base64
import html
import re
from html.parser import HTMLParser

from .guard import Guard

PLACEHOLDERS = re.compile(
    r"\b(lorem ipsum|todo|tbd|tbc|xxx+|fixme)\b|\[(insert|your|placeholder|add|name|company)[^\]]*\]|"
    r"<(insert|your|placeholder)[^>]*>", re.I)
MAX_PAGE_BYTES = 400_000
MIN_ITEM_WORDS = 25


def md_to_html(text: str) -> str:
    """A safe Markdown subset: #-headings, bullet and numbered lists, **bold**, paragraphs."""
    out, list_tag = [], None

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    def inline(raw: str) -> str:
        escaped = html.escape(raw, quote=True)
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)

    for line in (text or "").splitlines():
        line = line.rstrip()
        if not line.strip():
            close_list()
            continue
        if m := re.match(r"^(#{1,6})\s+(.*)", line):
            close_list()
            level = min(len(m.group(1)) + 2, 6)
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
        elif m := re.match(r"^\s*[-*•]\s+(.*)", line):
            if list_tag != "ul":
                close_list()
                out.append("<ul>")
                list_tag = "ul"
            out.append(f"<li>{inline(m.group(1))}</li>")
        elif m := re.match(r"^\s*\d+[.)]\s+(.*)", line):
            if list_tag != "ol":
                close_list()
                out.append("<ol>")
                list_tag = "ol"
            out.append(f"<li>{inline(m.group(1))}</li>")
        else:
            close_list()
            out.append(f"<p>{inline(line)}</p>")
    close_list()
    return "\n".join(out)


def bundle_markdown(spec: dict) -> str:
    parts = [f"# {spec['product_name']}", "", spec["tagline"], ""]
    for item in spec["items"]:
        parts += [f"## {item['title']}", "", item["description"], "", item["content"], ""]
    return "\n".join(parts).strip() + "\n"


def render_mvp_html(spec: dict, lang: str = "en") -> str:
    e = lambda s: html.escape(str(s), quote=True)          # noqa: E731
    bundle = base64.b64encode(bundle_markdown(spec).encode("utf-8")).decode("ascii")
    toc = "".join(f'<li><a href="#item-{i}">{e(item["title"])}</a></li>'
                  for i, item in enumerate(spec["items"]))
    items = "".join(
        f'<section class="item" id="item-{i}"><h2>{e(item["title"])}</h2>'
        f'<p class="desc">{e(item["description"])}</p>{md_to_html(item["content"])}</section>'
        for i, item in enumerate(spec["items"]))
    steps = "".join(f"<li>{e(step)}</li>" for step in spec["user_docs"]["quick_start"])
    direction = "rtl" if lang == "ar" else "ltr"
    return f"""<!DOCTYPE html>
<html lang="{e(lang)}" dir="{direction}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(spec['product_name'])}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:860px;margin:0 auto;padding:24px;line-height:1.55;color:#1d1d1f}}
header{{border-bottom:2px solid #eee;margin-bottom:16px}} .tagline{{color:#555}}
.item{{border:1px solid #e5e5e5;border-radius:10px;padding:16px 20px;margin:16px 0}}
.desc{{color:#555;font-style:italic}}
button{{padding:10px 16px;border-radius:8px;border:0;background:#1f6feb;color:#fff;cursor:pointer}}
</style></head>
<body>
<header><h1>{e(spec['product_name'])}</h1><p class="tagline">{e(spec['tagline'])}</p>
<p>For: {e(spec['audience'])}</p>
<button id="download" type="button">Download the full pack (.md)</button></header>
<nav><h2>Contents</h2><ul>{toc}</ul></nav>
{items}
<section id="quick-start"><h2>Quick start</h2><ol>{steps}</ol></section>
<script>
document.getElementById('download').addEventListener('click', function () {{
  var bytes = Uint8Array.from(atob('{bundle}'), function (c) {{ return c.charCodeAt(0); }});
  var blob = new Blob([bytes], {{type: 'text/markdown;charset=utf-8'}});
  var link = document.createElement('a');
  link.href = URL.createObjectURL(blob); link.download = 'product-pack.md'; link.click();
}});
</script>
</body></html>
"""


def render_user_docs(spec: dict) -> str:
    docs = spec["user_docs"]
    lines = [f"# User guide: {spec['product_name']}", "", spec["tagline"], "", "## Quick start", ""]
    lines += [f"{i}. {step}" for i, step in enumerate(docs["quick_start"], 1)]
    lines += ["", "## What is inside", ""]
    lines += [f"- **{item['title']}**: {item['description']}" for item in spec["items"]]
    lines += ["", "## Frequently asked questions", ""]
    for qa in docs["faq"]:
        lines += [f"**{qa['q']}**", "", qa["a"], ""]
    return "\n".join(lines).strip() + "\n"


class _PageReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.hrefs, self.text = set(), [], []
        self.title, self.scripts, self._in_title = "", 0, False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.add(attributes["id"])
        if tag == "a" and attributes.get("href"):
            self.hrefs.append(attributes["href"])
        if tag == "script":
            self.scripts += 1
        self._in_title = tag == "title"

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        self.text.append(data)


def verify_mvp(page: str, spec: dict, docs: str, guard: Guard) -> list[dict]:
    """The automatic MVP tests. Returns [{name, passed, detail}]; Gate 3 needs every one to pass."""
    reader = _PageReader()
    reader.feed(page)
    visible = " ".join(" ".join(reader.text).split())
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(ok), "detail": detail})

    items = spec["items"]
    check("the page title is the product name", reader.title.strip() == spec["product_name"].strip(),
          reader.title.strip())
    check("at least 3 product items", len(items) >= 3, f"{len(items)} items")
    titles = [item["title"].strip().lower() for item in items]
    check("item titles are distinct", len(set(titles)) == len(titles))
    missing = [item["title"] for item in items if " ".join(item["title"].split()) not in visible]
    check("every item is rendered on the page", not missing, ", ".join(missing))
    thin = [item["title"] for item in items if len(item["content"].split()) < MIN_ITEM_WORDS]
    check(f"every item has at least {MIN_ITEM_WORDS} words of real content", not thin, ", ".join(thin))
    anchors = [href[1:] for href in reader.hrefs if href.startswith("#")]
    broken = [a for a in anchors if a not in reader.ids]
    check("every table-of-contents link resolves", len(anchors) == len(items) and not broken,
          ", ".join(broken))
    check("the download bundle is embedded", "atob('" in page and "product-pack.md" in page)
    check("no injected scripts (only the download script)", reader.scripts == 1, f"{reader.scripts} scripts")
    placeholder = PLACEHOLDERS.search(bundle_markdown(spec) + "\n" + docs)
    check("no placeholder text", placeholder is None, placeholder.group(0) if placeholder else "")
    size = len(page.encode("utf-8"))
    check(f"page is under {MAX_PAGE_BYTES // 1000} KB", size < MAX_PAGE_BYTES, f"{size} bytes")
    verdict = guard.post_check(bundle_markdown(spec), agent="build")
    check("content passes the guard (no income promises, fake proof or urgency)", verdict.allowed,
          verdict.reason or "")
    check("user docs: quick start has 3 or more steps", len(spec["user_docs"]["quick_start"]) >= 3)
    check("user docs: FAQ has 2 or more answers", len(spec["user_docs"]["faq"]) >= 2)
    check("user docs are written", len(docs.split()) >= 60, f"{len(docs.split())} words")
    return checks
