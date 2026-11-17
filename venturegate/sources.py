"""Evidence sources, offline-first.

The team saves real pages into sources/ (one page per file) with a header:

    URL: https://example.com/page
    Title: Page title
    Retrieved: 2026-11-17

    ...page text...

Agents are shown the most relevant excerpts, labelled [S1], [S2], ..., and may only cite those
labels. The code maps a label back to the URL in the file, so the model can never invent a link,
and a label it makes up simply does not resolve.

`python -m venturegate fetch-source <url>` saves one public page (needs internet, no API key).
"""
import html
import math
import re
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from . import config
from .logger import is_url

# Two-letter terms matter here ("CV", "AI", "UX"), so tokens start at 2 characters and the
# common two-letter English words are handled as stop words instead.
WORD = re.compile(r"[a-zA-Z؀-ۿ0-9]{2,}")
STOP_WORDS = set(
    "the and for with that this from are was were you your our not but have has can will about into "
    "their they them what when which who how all any more most other some such only than too very "
    "also its it's out use used using per just "
    "is an of to in on at by or as be we it if no so do up me my he us am".split())
MAX_SOURCE_CHARS = 40_000


@dataclass(frozen=True)
class Source:
    url: str
    title: str
    text: str
    file: str


@dataclass(frozen=True)
class Excerpt:
    sid: str          # "S1", "S2", ... valid only within one agent call
    source: Source
    text: str


def tokens(text: str) -> list[str]:
    return [w.lower() for w in WORD.findall(text or "") if w.lower() not in STOP_WORDS]


def parse_source_file(path: Path) -> Source | None:
    """Return a Source, or None when the file has no valid URL header or no body."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    except OSError:
        return None
    head, _, body = raw.lstrip("﻿").partition("\n\n")
    meta = {}
    for line in head.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip().lower()] = value.strip()
    url = meta.get("url", "")
    body = body.strip()
    if not is_url(url) or not body:
        return None
    return Source(url=url, title=meta.get("title") or url, text=body[:MAX_SOURCE_CHARS], file=path.name)


class SourceLibrary:
    """Pages saved in sources/ (or a given list of Source objects), searchable by TF-IDF."""

    live = False

    def __init__(self, folder: Path | None = None, chunk_chars: int = 700, sources: list[Source] | None = None):
        self.folder = Path(folder) if folder else config.path("SOURCES_DIR", "sources")
        self.sources: list[Source] = []
        self.skipped: list[str] = []
        self.notices: list[str] = []
        if sources is not None:
            for source in sources:
                if source.url not in {s.url for s in self.sources}:
                    self.sources.append(source)
        elif self.folder.is_dir():
            for path in sorted(self.folder.iterdir()):
                if not path.is_file() or path.suffix.lower() not in (".md", ".txt"):
                    continue
                if path.name.lower().startswith("readme"):
                    continue
                source = parse_source_file(path)
                if source is None:
                    self.skipped.append(path.name)
                elif source.url not in {s.url for s in self.sources}:
                    self.sources.append(source)

        self.chunks: list[tuple[Source, str]] = []
        for source in self.sources:
            for chunk in _chunk(source.text, chunk_chars):
                self.chunks.append((source, chunk))

        document_frequency = Counter()
        self._chunk_counts: list[Counter] = []
        for _, text in self.chunks:
            counts = Counter(tokens(text))
            self._chunk_counts.append(counts)
            document_frequency.update(set(counts))
        n = max(len(self.chunks), 1)
        self._idf = {term: math.log(1 + n / df) for term, df in document_frequency.items()}

    def __len__(self) -> int:
        return len(self.sources)

    def relevant(self, query: str, k: int = 6, per_source: int = 2) -> list[Excerpt]:
        """Top-k excerpts by TF-IDF overlap with the query. Deterministic, so a replayed run sees
        exactly the same excerpts. At most `per_source` excerpts come from any one page, so a single
        long page cannot crowd out the rest of the evidence."""
        if isinstance(query, (list, tuple)):
            query = " ".join(query)
        query_terms = set(tokens(query))
        if not query_terms or not self.chunks:
            return []
        scored = []
        for index, ((source, text), counts) in enumerate(zip(self.chunks, self._chunk_counts)):
            score = sum((1 + math.log(counts[t])) * self._idf.get(t, 0.0) for t in query_terms if counts.get(t))
            title_bonus = 0.5 * len(query_terms & set(tokens(source.title)))
            if score > 0:
                scored.append((-(score + title_bonus), index, source, text))
        scored.sort(key=lambda item: (item[0], item[1]))
        picked, per = [], Counter()
        for _, _, source, text in scored:
            if per[source.url] >= per_source:
                continue
            per[source.url] += 1
            picked.append((source, text))
            if len(picked) == k:
                break
        return [Excerpt(f"S{i}", source, text) for i, (source, text) in enumerate(picked, 1)]


def _chunk(text: str, size: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buffer = [], ""
    for paragraph in paragraphs:
        while len(paragraph) > size * 2:               # split very long paragraphs
            cut = paragraph.rfind(" ", 0, size * 2)
            cut = cut if cut > size // 2 else size * 2
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if buffer and len(buffer) + len(paragraph) > size:
            chunks.append(buffer)
            buffer = ""
        buffer = f"{buffer}\n{paragraph}".strip()
    if buffer:
        chunks.append(buffer)
    return chunks


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"}
    BREAKS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "tr", "br", "div", "section", "article"}

    def __init__(self):
        super().__init__()
        self.parts, self.title, self._skip, self._in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BREAKS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(raw: str) -> tuple[str, str]:
    """(title, readable text) from an HTML page, without scripts, styles or navigation."""
    parser = _TextExtractor()
    parser.feed(raw)
    text = html.unescape("".join(parser.parts))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text).strip()
    return " ".join(parser.title.split()), text


def source_filename(url: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", url.lower().split("//", 1)[-1]).strip("-")[:70].strip("-")
    return f"{stem or 'source'}.md"


def save_source(url: str, title: str, text: str, folder: Path | None = None) -> Path:
    if not is_url(url):
        raise ValueError("not an http(s) URL")
    if not text.strip():
        raise ValueError("the page has no readable text")
    folder = Path(folder) if folder else config.path("SOURCES_DIR", "sources")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / source_filename(url)
    path.write_text(f"URL: {url}\nTitle: {' '.join((title or url).split())}\n"
                    f"Retrieved: {date.today().isoformat()}\n\n{text.strip()[:MAX_SOURCE_CHARS]}\n",
                    encoding="utf-8")
    return path


def fetch_source(url: str, folder: Path | None = None) -> Path:
    """Download one public page and save it as a source file. A manual team step; no API key."""
    if not is_url(url):
        raise ValueError("not an http(s) URL")
    request = urllib.request.Request(url, headers={"User-Agent": "VentureGate/0.1 (evidence collection)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(3_000_000).decode(response.headers.get_content_charset() or "utf-8", "replace")
    title, text = html_to_text(raw) if "<" in raw[:3000] else ("", raw)
    return save_source(url, title, text, folder)
