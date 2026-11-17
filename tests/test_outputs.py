"""Part 7d: output files carry the exact names TEAM_CLAUDE.md requires and an honest status line."""
import re

import pytest

from venturegate.outputs import OutputWriter, slug

NAME = re.compile(r"^phase[1-6]_(step\d+|gate)_[a-z0-9-]+-[a-z0-9-]+\.(md|json|csv|txt|html)$")


@pytest.fixture
def writer(tmp_path):
    return OutputWriter("weak", tmp_path, status=lambda: {"model": "qwen3:4b", "replay": False})


def test_step_and_gate_names_follow_the_convention(writer):
    assert writer.name(1, 2, "Opportunities & Verdict") == "phase1_step2_weak-opportunities-verdict.md"
    assert writer.name(2, None, "demand-stop") == "phase2_gate_weak-demand-stop.md"
    assert NAME.match(writer.name(3, 1, "MVP", "html"))


@pytest.mark.parametrize("args", [(0, 1, "x"), (7, 1, "x"), (1, 0, "x"), ("1", 1, "x")])
def test_bad_phase_or_step_is_refused(writer, args):
    with pytest.raises(ValueError):
        writer.name(*args)


@pytest.mark.parametrize("ext", ["pdf", "png", "zip", "docx"])
def test_only_text_formats_are_allowed(writer, ext):
    with pytest.raises(ValueError, match="text"):
        writer.name(1, 1, "x", ext)


def test_slug_handles_odd_input():
    assert slug("") == "output" and slug("!!!") == "output"
    assert slug("Café / Plan  2") == "caf-plan-2"
    assert len(slug("x" * 200)) <= 40


def test_markdown_gets_a_status_line(writer):
    path = writer.write(1, 1, "intake", "# Intake\n\nText")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("> Run: weak · Model: qwen3:4b · Mode: live")
    assert "# Intake" in text


def test_replayed_output_says_so(tmp_path):
    writer = OutputWriter("strong", tmp_path, status=lambda: {"model": "qwen3:4b", "replay": True})
    text = writer.write(1, 1, "intake", "x").read_text(encoding="utf-8")
    assert "[REPLAY MODE]" in text.splitlines()[0]


def test_labels_are_included(writer):
    text = writer.write(2, 3, "demand", "x", labels=["[SIMULATED]"]).read_text(encoding="utf-8")
    assert "[SIMULATED]" in text.splitlines()[0]


def test_html_banner_goes_inside_body_and_is_escaped(tmp_path):
    writer = OutputWriter("weak", tmp_path, status=lambda: {"model": "<b>m</b>"})
    page = writer.write(2, 2, "landing", "<html><BODY class='x'><h1>Hi</h1></body></html>", ext="html")
    text = page.read_text(encoding="utf-8")
    assert re.search(r"<BODY class='x'><div", text)
    assert "&lt;b&gt;m&lt;/b&gt;" in text and "<b>m</b>" not in text


def test_rewriting_a_file_does_not_duplicate_it_in_the_list(writer):
    writer.write(1, 1, "intake", "a")
    writer.write(1, 1, "intake", "b")
    assert len(writer.written) == 1
    assert writer.written[0].read_text(encoding="utf-8").endswith("b\n")


def test_run_label_is_slugged(tmp_path):
    assert OutputWriter("My Run!", tmp_path).name(1, 1, "x") == "phase1_step1_my-run-x.md"
