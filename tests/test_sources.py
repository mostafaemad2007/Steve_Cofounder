"""Part 7b: evidence sources. Only real saved pages count, and the ranking is deterministic."""
import pytest

from venturegate.sources import (SourceLibrary, html_to_text, parse_source_file, save_source,
                                 source_filename, tokens)


def write(folder, name, url, body, title="A page"):
    head = f"URL: {url}\n" if url is not None else ""
    (folder / name).write_text(f"{head}Title: {title}\nRetrieved: 2026-11-17\n\n{body}", encoding="utf-8")


@pytest.fixture
def library(tmp_path):
    write(tmp_path, "canva.md", "https://www.canva.com/resumes/templates/",
          "Canva offers free resume templates and CV templates for every job.", "Canva CV templates")
    write(tmp_path, "hosting.md", "https://example.org/hosting",
          "Static hosting costs five dollars per month. Domain names cost twelve dollars per year.",
          "Hosting prices")
    write(tmp_path, "egypt.md", "https://example.org/egypt",
          "Egypt graduates thousands of engineering students each year who apply for tech jobs.",
          "Egypt graduates")
    return SourceLibrary(tmp_path)


def test_valid_pages_load(library):
    assert len(library) == 3


def test_invalid_files_are_skipped_and_reported(tmp_path):
    write(tmp_path, "no_url.md", None, "Some text")
    write(tmp_path, "bad_url.md", "www.example.com", "Some text")
    write(tmp_path, "empty.md", "https://example.org/empty", "   ")
    write(tmp_path, "ok.md", "https://example.org/ok", "Real text here")
    (tmp_path / "README.md").write_text("URL: https://example.org/readme\n\nignored", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    lib = SourceLibrary(tmp_path)
    assert [s.url for s in lib.sources] == ["https://example.org/ok"]
    assert sorted(lib.skipped) == ["bad_url.md", "empty.md", "no_url.md"]


def test_duplicate_urls_count_once(tmp_path):
    write(tmp_path, "a.md", "https://example.org/same", "first copy")
    write(tmp_path, "b.md", "https://example.org/same", "second copy")
    assert len(SourceLibrary(tmp_path)) == 1


def test_a_missing_or_empty_folder_gives_no_sources(tmp_path):
    assert len(SourceLibrary(tmp_path / "nope")) == 0
    assert SourceLibrary(tmp_path / "nope").relevant("anything") == []


def test_windows_line_endings_and_bom_are_handled(tmp_path):
    (tmp_path / "win.md").write_bytes(
        "﻿URL: https://example.org/win\r\nTitle: Win\r\n\r\nBody text here\r\n".encode("utf-8"))
    assert parse_source_file(tmp_path / "win.md").url == "https://example.org/win"


def test_relevant_ranks_by_the_query_and_labels_from_s1(library):
    excerpts = library.relevant("free CV resume templates competitors")
    assert excerpts[0].source.url == "https://www.canva.com/resumes/templates/"
    assert [e.sid for e in excerpts] == [f"S{i}" for i in range(1, len(excerpts) + 1)]


def test_relevant_is_deterministic(library):
    first = [(e.sid, e.source.url) for e in library.relevant("hosting domain price per month")]
    second = [(e.sid, e.source.url) for e in library.relevant("hosting domain price per month")]
    assert first == second and first[0][1] == "https://example.org/hosting"


def test_no_match_and_empty_queries_return_nothing(library):
    assert library.relevant("zebra quantum") == []
    assert library.relevant("") == []
    assert library.relevant("the and of") == []          # stop words only


def test_one_long_page_cannot_crowd_out_the_others(tmp_path):
    long_body = "\n\n".join(["templates pricing competitors " * 30] * 10)
    write(tmp_path, "long.md", "https://example.org/long", long_body)
    write(tmp_path, "short.md", "https://example.org/short", "templates pricing competitors")
    excerpts = SourceLibrary(tmp_path).relevant("templates pricing competitors", k=6, per_source=2)
    urls = [e.source.url for e in excerpts]
    assert urls.count("https://example.org/long") == 2 and "https://example.org/short" in urls


def test_arabic_text_is_searchable(tmp_path):
    write(tmp_path, "ar.md", "https://example.org/ar", "قوالب السيرة الذاتية للخريجين في مصر")
    assert SourceLibrary(tmp_path).relevant("السيرة الذاتية")[0].source.url == "https://example.org/ar"


def test_tokens_keep_meaningful_short_terms_and_drop_stop_words():
    assert tokens("The CV is for an AI job") == ["cv", "ai", "job"]
    assert tokens("Templates for graduates") == ["templates", "graduates"]
    assert tokens("a") == []


def test_a_two_letter_term_drives_ranking(tmp_path):
    write(tmp_path, "cv.md", "https://example.org/cv", "CV builder for students")
    write(tmp_path, "other.md", "https://example.org/other", "Template builder for students")
    assert SourceLibrary(tmp_path).relevant("CV")[0].source.url == "https://example.org/cv"


def test_html_to_text_drops_scripts_styles_and_navigation():
    raw = ("<html><head><title> Pricing  page </title><style>p{}</style></head><body>"
           "<nav>Menu</nav><script>alert(1)</script><p>Plans start at &pound;9.</p><p>Second</p>"
           "<footer>Footer</footer></body></html>")
    title, text = html_to_text(raw)
    assert title == "Pricing page"
    assert "Plans start at £9." in text and "Second" in text
    assert "alert" not in text and "Menu" not in text and "Footer" not in text


def test_save_source_writes_a_loadable_file(tmp_path):
    path = save_source("https://example.org/a?b=1", "Title", "Body text", tmp_path)
    assert path.name == source_filename("https://example.org/a?b=1")
    assert parse_source_file(path).url == "https://example.org/a?b=1"
    with pytest.raises(ValueError):
        save_source("ftp://example.org", "t", "body", tmp_path)
    with pytest.raises(ValueError):
        save_source("https://example.org", "t", "   ", tmp_path)
