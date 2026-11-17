"""Live web search, tested against a simulated internet (tests/fake_web.py)."""
import json

import pytest

from fake_web import FakeWeb, ddg_page
from venturegate.logger import DecisionLogger, validate_entry
from venturegate.sources import SourceLibrary
from venturegate.websearch import WebSourceLibrary, default_library, parse_duckduckgo


def make(tmp_path, web=None, mode="live", saved=None, **kw):
    web = web or FakeWeb()
    lib = WebSourceLibrary(mode=mode, logger=DecisionLogger(tmp_path / "log.json"), cache_dir=tmp_path / "cache",
                           saved=saved if saved is not None else SourceLibrary(tmp_path / "none"), get=web,
                           searxng_url=kw.pop("searxng_url", ""), **kw)
    return lib, web


# == parsing search results ===================================================
def test_duckduckgo_results_are_decoded_and_ads_dropped():
    html = ddg_page(["https://a.test/x?y=1", "https://b.test/"]) + \
        '<a class="result__a" href="https://c.test/direct">Direct link</a>' + \
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.test%2Fx%3Fy%3D1">Duplicate</a>'
    assert [u for u, _ in parse_duckduckgo(html)] == ["https://a.test/x?y=1", "https://b.test/", "https://c.test/direct"]
    assert parse_duckduckgo("<html>captcha</html>") == []


# == searching and reading ====================================================
def test_relevant_searches_reads_pages_and_labels_excerpts(tmp_path):
    lib, web = make(tmp_path)
    excerpts = lib.relevant(["CV templates Egypt"], k=6)
    assert excerpts and [e.sid for e in excerpts] == [f"S{i}" for i in range(1, len(excerpts) + 1)]
    assert all(e.source.url.startswith("https://site") for e in excerpts)
    assert "Menu" not in excerpts[0].text and "x()" not in excerpts[0].text      # navigation and scripts dropped
    assert len(lib) == 4 and lib.searches == 1


def test_every_search_is_logged_with_the_urls_actually_read(tmp_path):
    lib, _ = make(tmp_path)
    lib.relevant(["CV templates Egypt", "resume pricing"])
    entry = [e for e in lib.logger.read() if e["action"] == "web_search"][0]
    validate_entry(entry)
    assert entry["agent"] == "research" and entry["model"] is None and entry["provider"] == "duckduckgo"
    assert sorted(entry["sources"]) == [f"https://site{i}.test/page" for i in range(1, 5)]
    assert entry["queries"] == ["CV templates Egypt", "resume pricing"]


def test_pages_are_read_once_per_run(tmp_path):
    lib, web = make(tmp_path)
    lib.relevant("CV templates")
    lib.relevant("CV pricing")
    assert sum(c == "https://site1.test/page" for c in web.calls) == 1


def test_searxng_is_used_first_when_configured(tmp_path):
    searx = {"https://searx.local/search?q=cv&format=json":
             (200, "application/json", '{"results": [{"url": "https://site9.test/page", "title": "S9"}]}')}
    lib, web = make(tmp_path, FakeWeb(extra=searx), searxng_url="https://searx.local")
    assert lib.search("cv") == ("searxng", [("https://site9.test/page", "S9")])
    assert not any("duckduckgo" in c for c in web.calls)


def test_blocked_duckduckgo_falls_back_to_wikipedia(tmp_path):
    lib, _ = make(tmp_path, FakeWeb(ddg=False))
    provider, results = lib.search("curriculum vitae")
    assert provider == "wikipedia" and results[0][0] == "https://en.wikipedia.org/wiki/Curriculum_vitae"
    assert lib.relevant("curriculum vitae templates")


def test_no_internet_gives_a_notice_and_uses_saved_pages(tmp_path):
    saved_dir = tmp_path / "saved"
    saved_dir.mkdir()
    (saved_dir / "a.md").write_text("URL: https://saved.test/a\nTitle: Saved\n\nCV templates pricing in Egypt",
                                    encoding="utf-8")
    lib, _ = make(tmp_path, FakeWeb(down=True), saved=SourceLibrary(saved_dir))
    excerpts = lib.relevant("CV templates pricing")
    assert [e.source.url for e in excerpts] == ["https://saved.test/a"]
    assert lib.notices and "no readable pages" in lib.notices[0]
    assert any(e["action"] == "search_provider_failed" for e in lib.logger.read())


@pytest.mark.parametrize("response", [
    (200, "application/pdf", "%PDF-1.4"), (200, "image/png", "\x89PNG"), (404, "text/html", ""),
    (200, "text/html", "<html><body><p>Too short.</p></body></html>")])
def test_unusable_pages_are_skipped(tmp_path, response):
    lib, _ = make(tmp_path, FakeWeb(pages=1, extra={"https://site1.test/page": response}))
    assert lib.relevant("cv templates") == [] and lib.pages == {}


def test_robots_txt_is_respected(tmp_path):
    lib, web = make(tmp_path, FakeWeb(pages=2, blocked_robots={"site1.test"}))
    lib.relevant("cv templates")
    assert list(lib.pages) == ["https://site2.test/page"]
    assert "https://site1.test/page" not in web.calls


def test_social_sites_are_skipped(tmp_path):
    social = {"https://html.duckduckgo.com/html/": (200, "text/html", ddg_page(
        ["https://www.youtube.com/watch?v=1", "https://www.linkedin.com/in/x", "https://site1.test/page"]))}
    lib, _ = make(tmp_path, FakeWeb(extra=social))
    assert [u for u, _ in lib.search("cv")[1]] == ["https://site1.test/page"]


# == replay =====================================================================
def test_a_live_search_is_replayed_exactly_without_network(tmp_path):
    live, _ = make(tmp_path)
    first = [(e.sid, e.source.url, e.text) for e in live.relevant(["CV templates Egypt"])]
    replay, web = make(tmp_path, FakeWeb(down=True), mode="replay")
    second = [(e.sid, e.source.url, e.text) for e in replay.relevant(["CV templates Egypt"])]
    assert first == second and web.calls == []


def test_the_cache_keeps_excerpts_not_whole_pages(tmp_path):
    lib, _ = make(tmp_path)
    lib.relevant("CV templates")
    data = json.loads(next((tmp_path / "cache").glob("*.json")).read_text(encoding="utf-8"))
    assert data["queries"] == ["CV templates"] and data["excerpts"]
    assert all(len(x["text"]) <= 1400 for x in data["excerpts"])


def test_replay_without_a_recording_says_so(tmp_path):
    lib, web = make(tmp_path, mode="replay")
    assert lib.relevant("never searched") == [] and "[REPLAY MODE]" in lib.notices[0] and web.calls == []


def test_web_search_can_be_switched_off(monkeypatch, tmp_path):
    monkeypatch.setenv("WEB_SEARCH", "false")
    assert type(default_library("live", DecisionLogger(tmp_path / "l.json"))).__name__ == "SourceLibrary"
    monkeypatch.setenv("WEB_SEARCH", "true")
    assert default_library("live", DecisionLogger(tmp_path / "l.json")).live is True
