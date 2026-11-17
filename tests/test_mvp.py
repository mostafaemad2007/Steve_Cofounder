"""Part 7e: the MVP builder renders a working, safe page and its tests catch real problems."""
import copy

import pytest

from venturegate.guard import Guard
from venturegate.logger import DecisionLogger
from venturegate.mvp import bundle_markdown, md_to_html, render_mvp_html, render_user_docs, verify_mvp

CONTENT = ("Use this checklist before every application. List the role, the company and the deadline. "
           "Match three skills from the job post to three finished projects, with one line of proof "
           "for each. Keep the CV to one page and export it as a PDF named after you.")

SPEC = {
    "product_name": "Bilingual Tech CV Pack",
    "tagline": "Arabic and English CV templates for junior tech roles.",
    "audience": "Egyptian fresh graduates",
    "items": [{"title": title, "description": "A practical template with guidance.", "content": CONTENT}
              for title in ("One-page developer CV", "Project proof checklist", "Arabic layout guide")],
    "user_docs": {"quick_start": ["Open the pack", "Pick a template", "Export to PDF"],
                  "faq": [{"q": "Can I edit it?", "a": "Yes, every template is editable in Google Docs."},
                          {"q": "Is Arabic supported?", "a": "Yes, right-to-left layouts are included."}]},
}


@pytest.fixture
def guard(tmp_path):
    return Guard(DecisionLogger(tmp_path / "log.json"))


def run_checks(spec, guard, lang="en"):
    page, docs = render_mvp_html(spec, lang), render_user_docs(spec)
    return {c["name"]: c for c in verify_mvp(page, spec, docs, guard)}, page


def failing(checks):
    return [name for name, c in checks.items() if not c["passed"]]


def test_a_good_spec_passes_every_check(guard):
    checks, _ = run_checks(SPEC, guard)
    assert failing(checks) == []


def test_model_markup_is_escaped_and_cannot_run(guard):
    spec = copy.deepcopy(SPEC)
    spec["items"][0]["content"] = CONTENT + "\n\n<script>alert('x')</script> <img src=x onerror=alert(1)>"
    spec["product_name"] = "Pack <b>bold</b>"
    checks, page = run_checks(spec, guard)
    assert "<script>alert" not in page and "<img src=x" not in page
    assert "&lt;script&gt;" in page
    assert checks["no injected scripts (only the download script)"]["passed"]


def test_placeholder_text_fails(guard):
    for placeholder in ("[insert your name]", "TODO", "Lorem ipsum dolor", "<your company>"):
        spec = copy.deepcopy(SPEC)
        spec["items"][1]["content"] = CONTENT + " " + placeholder
        assert "no placeholder text" in failing(run_checks(spec, guard)[0]), placeholder


def test_thin_content_fails(guard):
    spec = copy.deepcopy(SPEC)
    spec["items"][2]["content"] = "Too short."
    assert any("words of real content" in name for name in failing(run_checks(spec, guard)[0]))


def test_too_few_or_duplicate_items_fail(guard):
    two = copy.deepcopy(SPEC)
    two["items"] = two["items"][:2]
    assert "at least 3 product items" in failing(run_checks(two, guard)[0])
    dup = copy.deepcopy(SPEC)
    dup["items"][1]["title"] = dup["items"][0]["title"]
    assert "item titles are distinct" in failing(run_checks(dup, guard)[0])


def test_income_promises_in_content_fail_the_guard_check(guard):
    spec = copy.deepcopy(SPEC)
    spec["items"][0]["content"] = CONTENT + " You will earn back the price in a week."
    assert any("passes the guard" in name for name in failing(run_checks(spec, guard)[0]))


def test_thin_user_docs_fail(guard):
    spec = copy.deepcopy(SPEC)
    spec["user_docs"]["quick_start"] = ["Open it"]
    spec["user_docs"]["faq"] = []
    names = failing(run_checks(spec, guard)[0])
    assert "user docs: quick start has 3 or more steps" in names
    assert "user docs: FAQ has 2 or more answers" in names


def test_arabic_pages_are_right_to_left(guard):
    _, page = run_checks(SPEC, guard, lang="ar")
    assert 'dir="rtl"' in page and 'lang="ar"' in page


def test_the_download_bundle_round_trips_unicode():
    import base64
    import re
    spec = copy.deepcopy(SPEC)
    spec["items"][0]["content"] = CONTENT + " قالب عربي"
    encoded = re.search(r"atob\('([A-Za-z0-9+/=]+)'\)", render_mvp_html(spec)).group(1)
    assert base64.b64decode(encoded).decode("utf-8") == bundle_markdown(spec)


def test_markdown_subset():
    out = md_to_html("# Title\n\n- one\n- **two**\n\n1. first\n2) second\n\nplain & <tag>")
    assert "<h3>Title</h3>" in out
    assert "<ul>\n<li>one</li>\n<li><strong>two</strong></li>\n</ul>" in out
    assert "<ol>\n<li>first</li>\n<li>second</li>\n</ol>" in out
    assert "<p>plain &amp; &lt;tag&gt;</p>" in out
    assert md_to_html("") == ""


def test_user_docs_list_every_item():
    docs = render_user_docs(SPEC)
    for item in SPEC["items"]:
        assert item["title"] in docs
    assert "## Quick start" in docs and "## Frequently asked questions" in docs
