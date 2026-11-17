"""Part 10: the founder console. Page logic and HTML, tested without a browser
(tests/browser_check.py drives the real page in a headless browser)."""
import re
import shutil
from pathlib import Path

import pytest

from fake_model import FakeModel
from venturegate import views
from venturegate.app import LIVE, REPLAY, STRONG_SCENARIO, ConsoleApp, Session
from venturegate.brief import FounderBrief
from venturegate.events import Done, Reply, Request, Say
from venturegate.llm import LLM
from venturegate.logger import DecisionLogger
from venturegate.orchestrator import Pipeline
from venturegate.sources import SourceLibrary

ROOT = Path(__file__).resolve().parent.parent
SOURCE_TEXT = ("CV templates competitors pricing price graduates Egypt engineering students tech jobs hosting "
               "domain month cost trademark licence terms copyright fonts free alternatives market chatbot app")


@pytest.fixture
def app(tmp_path):
    src = tmp_path / "sources"
    src.mkdir()
    for i in range(1, 4):
        (src / f"s{i}.md").write_text(f"URL: https://example.org/s{i}\nTitle: Source {i}\n\n{SOURCE_TEXT} {i}",
                                      encoding="utf-8")
    shutil.copy(ROOT / "gates.yaml", tmp_path / "gates.yaml")

    def factory(brief, mode):
        logger = DecisionLogger(tmp_path / "decision_log.json")
        llm = LLM(mode=mode, model="qwen3:4b", logger=logger, replay_dir=tmp_path / "replay", transport=FakeModel())
        return Pipeline(brief, llm=llm, logger=logger, sources=SourceLibrary(src), out_dir=tmp_path / "outputs",
                        state_dir=tmp_path / "state", gates_path=tmp_path / "gates.yaml")
    return ConsoleApp(factory)


def form(app, name):
    ex = app.load_example(name)
    return {k: ex[k] for k in ("run", "idea", "market", "budget", "currency", "hours", "values",
                               "language", "scenario")}


def start(app, name, mode=LIVE):
    sid, view = None, None
    for sid, view in app.start(form(app, name), mode):
        pass
    return sid, view


def approve_until_done(app, sid, limit=80):
    view = None
    for _ in range(limit):
        session = app.get(sid)
        if session.done:
            return view
        action = "primary"
        text = "Fresh graduates in Egypt" if session.pending.kind == "question" else ""
        for view in app.respond(sid, action, text):
            pass
    raise AssertionError("the run did not finish")


# == runs through the page logic ==============================================
def test_the_weak_example_runs_to_a_stop_card(app):
    sid, view = start(app, "weak")
    assert view["screen"] == "run" and view["controls"]["primary"] == "Approve and continue"
    view = approve_until_done(app, sid)
    assert app.get(sid).done.outcome == "stopped"
    assert '<span class="vg-stamp">STOP</span>' in view["timeline"]
    assert "12</strong> sign-ups" in view["timeline"] and "What would change this decision" in view["timeline"]
    assert view["controls"] == {"visible": False} and view["finished"]
    assert 'class="stop"' in view["rail"] and view["rail"].count("Not reached") == 4


def test_the_strong_example_completes_and_every_phase_is_done(app):
    sid, _ = start(app, "strong")
    view = approve_until_done(app, sid)
    assert app.get(sid).done.outcome == "completed"
    assert view["rail"].count('class="done"') == 6
    assert "Run complete" in view["timeline"] and "payment_test_log.md" in view["files"]


def test_request_changes_needs_text_and_then_redoes_the_step(app):
    sid, _ = start(app, "strong")
    views_ = list(app.respond(sid, "secondary", "   "))
    assert "Write what should change" in views_[-1]["alert"]
    assert app.get(sid).pending.step_id.endswith("phase1_step1")              # still waiting, nothing sent
    list(app.respond(sid, "secondary", "Focus on data analyst roles."))
    assert app.get(sid).pipeline.llm.transport.calls.count("restate_idea") == 2


def test_stop_ends_the_run(app):
    sid, _ = start(app, "strong")
    view = list(app.respond(sid, "quiet"))[-1]
    assert app.get(sid).done.outcome == "stopped_by_founder" and "You stopped the run" in view["timeline"]


def test_a_question_needs_an_answer(app):
    f = form(app, "strong")
    f["market"] = ""
    sid = None
    for sid, _ in app.start(f, LIVE):
        pass
    while app.get(sid).pending.kind != "question":
        list(app.respond(sid, "primary"))
    view = list(app.respond(sid, "primary", ""))[-1]
    assert view["alert"] == "Type your answer first." and view["controls"]["primary"] == "Send answer"
    list(app.respond(sid, "primary", "Graduates in Alexandria"))
    assert app.get(sid).brief.target_market == "Graduates in Alexandria"


def test_a_bad_brief_stays_on_the_start_screen(app):
    f = form(app, "strong")
    f["idea"] = "app"
    results = list(app.start(f, LIVE))
    assert results == [("", {"alert": "The brief could not be used: describe the idea in at least one full sentence",
                             "screen": "start"})]


def test_an_unknown_or_finished_session_is_handled(app):
    assert list(app.respond("nope", "primary"))[0]["screen"] == "start"
    sid, _ = start(app, "strong")
    list(app.respond(sid, "quiet"))
    assert list(app.respond(sid, "primary"))[0]["finished"]                    # nothing more happens


def test_replay_with_nothing_recorded_ends_with_a_clear_error(app):
    sid, view = start(app, "strong", REPLAY)
    assert app.get(sid).done.outcome == "error"
    assert "The run could not continue" in view["timeline"] and "docker compose up" in view["timeline"]


def test_an_unexpected_crash_does_not_freeze_the_page():
    class Broken:
        def run(self):
            yield Say("Starting")
            raise KeyError("boom")
    session = Session.__new__(Session)
    session.brief, session.pipeline, session.events, session.pending, session.done = None, Broken(), [], None, None
    session.started, session.generator, session.transcript = False, Broken().run(), []
    list(session.advance())
    assert session.done.outcome == "error" and "KeyError" in session.done.summary


def test_old_sessions_are_dropped(app, monkeypatch):
    monkeypatch.setattr("venturegate.app.MAX_SESSIONS", 2)
    sids = [start(app, "strong")[0] for _ in range(3)]
    assert app.get(sids[0]) is None and app.get(sids[2]) is not None


@pytest.mark.parametrize("kind, step, action, text, expected", [
    ("confirm", "x:phase1_step1", "primary", "", Reply(True, "")),
    ("confirm", "x:phase1_step1", "secondary", "shorter", Reply(False, "shorter")),
    ("confirm", "x:phase1_step1", "quiet", "ignored", Reply(False, "")),
    ("gate", "x:gate1_pivot", "primary", "A bilingual cover letter pack for graduates", Reply(True, "A bilingual cover letter pack for graduates")),
    ("gate", "x:gate1", "primary", "", Reply(True, "")),
    ("publish", "x:phase5_open_store", "quiet", "", Reply(False, "")),
    ("question", "x:phase1_target_market", "primary", "Cairo graduates", Reply(None, "Cairo graduates")),
])
def test_reply_for_each_kind(kind, step, action, text, expected):
    reply, problem = ConsoleApp.reply_for(Request(step, kind, "?"), action, text)
    assert problem is None and reply == expected


def test_a_pivot_needs_a_real_idea():
    reply, problem = ConsoleApp.reply_for(Request("x:gate1_pivot", "gate", "?"), "primary", "idk")
    assert reply is None and "full sentence" in problem


# == HTML =====================================================================
HOSTILE = '<script>alert(1)</script><img src=x onerror=alert(2)>'


def test_model_and_founder_text_is_escaped_everywhere():
    events = [Say("Phase 1: Discover", kind="phase", phase=1),
              Say(f"Idea intake: {HOSTILE}", ["/tmp/a<b>.md"], kind="step", phase=1),
              Say(f"Gate 1: STOP. {HOSTILE}", kind="gate", phase=1, outcome="stop",
                  data={"reasons": [HOSTILE], "metrics": {HOSTILE: HOSTILE}, "what_would_change": [HOSTILE]}),
              Say(HOSTILE, kind="refusal")]
    page = views.timeline_html(events, Request("x:y", "confirm", HOSTILE), Done("stopped", HOSTILE))
    page += views.decision_html(Request("x:y", "confirm", HOSTILE))
    page += views.evidence_html([{"claim": HOSTILE, "source_url": "https://e.org/\"><script>", "confidence": "low"}], 5, 1)
    brief = FounderBrief.from_dict({"run": "x", "idea": f"A real idea for people {HOSTILE}", "skills": [HOSTILE],
                                    "budget": 1, "hours_per_week": 1, "target_market": HOSTILE})
    page += views.brief_html(brief) + views.header_html(model=HOSTILE, mode="live", ready=True, run="x", idea=HOSTILE)
    assert "<script>" not in page and "<img src=x" not in page and 'onerror=alert' not in page.replace("onerror=alert(2)&gt;", "")
    assert "&lt;script&gt;" in page


def test_honesty_labels_become_tags():
    html = views.timeline_html([Say("Demand: 12 sign-ups [SIMULATED], store MOCKED, claim ASSUMPTION", kind="info")],
                               None, None)
    assert '<span class="vg-tag sim">[SIMULATED]</span>' in html and '<span class="vg-tag sim">MOCKED</span>' in html
    assert '<span class="vg-tag asm">ASSUMPTION</span>' in html


def test_only_the_step_awaiting_a_decision_is_highlighted():
    events = [Say("A: one", kind="step"), Say("B: two", kind="step")]
    html = views.timeline_html(events, Request("x:b", "confirm", "?"), None)
    assert html.count("vg-step current") == 1 and html.index("vg-step current") > html.index("one")
    assert "vg-step current" not in views.timeline_html(events, Request("x:g", "gate", "?"), None)


def test_rail_states_across_a_run():
    events = [Say("", kind="phase", phase=1), Say("", kind="gate", phase=1, outcome="go"),
              Say("", kind="phase", phase=2)]
    assert [s["state"] for s in views.rail_state(events, Request("x:y", "confirm", "?"), None)] == \
        ["done", "active", "todo", "todo", "todo", "todo"]
    events.append(Say("", kind="gate", phase=2, outcome="stop"))
    assert [s["state"] for s in views.rail_state(events, None, Done("stopped", ""))] == \
        ["done", "stop", "skipped", "skipped", "skipped", "skipped"]


def test_the_stop_meter_shows_the_count_against_the_stop_line():
    ev = Say("Gate 2: STOP.", kind="gate", phase=2, outcome="stop",
             data={"reasons": ["12 of 100."], "metrics": {"sign-ups [SIMULATED]": 12, "pre-set target": 100,
                                                          "stop below": "50%"}})
    html = views.gate_html(ev)
    meter = html.split('class="vg-meter"', 1)[1].split("</div>", 1)[0]
    assert meter.count("<span") == 20                      # 20 blocks, 5 sign-ups each
    assert meter.count("fill") == 3                        # 12% rounds UP to 3 blocks: never hidden
    assert meter.count("mark") == 1 and 'aria-label="12 of 100; stop line at 50%"' in html
    assert "Steve:" in html and '<span class="vg-stamp">STOP</span>' in html


@pytest.mark.parametrize("count, filled", [(0, 0), (1, 1), (50, 10), (100, 20), (134, 20)])
def test_the_meter_never_overflows_or_hides_a_small_count(count, filled):
    meter = views.meter_html(count, 100, 50).split('class="vg-meter"', 1)[1].split("</div>", 1)[0]
    assert meter.count("fill") == filled


def test_decision_controls_by_kind():
    assert views.decision_controls(None) == {"visible": False}
    confirm = views.decision_controls(Request("x:a", "confirm", "?"))
    assert (confirm["primary"], confirm["secondary"], confirm["quiet"]) == ("Approve and continue", "Request changes", "Stop the run")
    publish = views.decision_controls(Request("x:phase5_open_store", "publish", "?"))
    assert "MOCKED" in publish["primary"] and not publish["text_visible"]
    assert views.decision_controls(Request("x:gate1_pivot", "gate", "?"))["primary"] == "Pivot with this idea"
    assert views.decision_controls(Request("x:q", "question", "?"))["secondary"] is None
    assert '<span class="vg-tag sim">MOCKED</span>' in views.decision_html(Request("x:s", "send", "Send?"))


def test_evidence_counts_distinct_sourced_claims():
    records = [{"claim": "A", "source_url": "https://www.canva.com/x"}, {"claim": "a", "source_url": "https://www.canva.com/x"},
               {"claim": "B", "source_url": None, "confidence": "low"}]
    html = views.evidence_html(records, 5, 3)
    blocks = html.split('class="vg-blocks"', 1)[1].split("</div>", 1)[0]
    assert blocks.count("<span") == 5 and blocks.count('class="fill"') == 1
    assert "canva.com" in html and "<b>1</b>with a source" in html and "<b>1</b>assumptions" in html


def test_steve_appears_where_the_founder_decides():
    assert "Steve is waiting for your decision" in views.decision_html(Request("x:a", "confirm", "?"))
    html = views.timeline_html([Say("Idea intake: ok", kind="step")], Request("x:a", "confirm", "?"), None)
    assert "<b>Steve</b> · waiting for your decision" in html
    header = views.header_html(model="qwen3:4b", mode="live", ready=True)
    assert "with Steve, your honest AI cofounder" in header and 'aria-label="Steve"' in header


def test_steve_emblem_is_original_pixel_art():
    svg = views.emblem(30)
    assert svg.startswith("<svg") and 'shape-rendering="crispEdges"' in svg and svg.count("<rect") >= 10


def test_file_links_point_at_the_served_outputs():
    html = views.files_html(["/repo/outputs/phase1_step1_weak-intake.md", ""])
    assert 'href="/gradio_api/file=/repo/outputs/phase1_step1_weak-intake.md"' in html and html.count("<a ") == 1


def test_start_panel_reflects_model_and_sources(app):
    html = views.start_side_html(model="qwen3:4b", ready=False, recorded=7, sources_loaded=2, thresholds=app.thresholds)
    assert "still starting up" in html and "replay a recorded run" in html and "2 evidence page(s)" in html
    assert "Fewer than 50% of the 100 waitlist sign-ups aimed for in 14 days" in html
    web = views.start_side_html(model="qwen3:4b", ready=True, recorded=0, sources_loaded=0, thresholds=app.thresholds,
                                web_search=True)
    assert "Steve researches the web" in web and "Steve is ready" in web and "gates.yaml" not in web


def test_file_chips_use_readable_names_and_keep_the_file_name_in_the_tooltip():
    html = views.files_html(["/o/phase2_gate_weak-demand-stop.md", "/o/phase3_step1_strong-mvp.html",
                             "/o/payment_test_log.md"])
    assert ">Gate report: demand stop</a>" in html and ">MVP (preview)</a>" in html
    assert ">Sale and delivery test</a>" in html and 'title="phase2_gate_weak-demand-stop.md"' in html


def test_header_is_plain_but_still_says_replay():
    live = views.header_html(model="qwen3:4b", mode="live", ready=True, run="weak", idea="An idea for graduates")
    assert "Steve is ready" in live and "Working on:" in live and 'title="Local model: qwen3:4b"' in live
    assert "[REPLAY MODE]" in views.header_html(model="qwen3:4b", mode="replay", ready=False, run="weak")


def test_examples_load_into_the_form(app):
    weak = app.load_example("weak")
    assert weak["run"] == "weak" and weak["scenario"] == "weak" and weak["language"] == "English"
    brief = app.brief_from_form(**form(app, "weak"))
    assert brief.mock_scenario == "weak" and brief.run == "weak"
    assert app.brief_from_form(**{**form(app, "weak"), "scenario": STRONG_SCENARIO,
                                  "language": "Arabic", "run": ""}).run == "my-idea"


def test_the_gradio_page_builds(app):
    demo = __import__("venturegate.app", fromlist=["build_ui"]).build_ui(app)
    assert type(demo).__name__ == "Blocks"


def test_the_form_does_not_ask_for_skills():
    from venturegate.app import build_ui
    blocks = build_ui(ConsoleApp(lambda *a, **k: None))
    labels = [getattr(c, "label", None) for c in blocks.blocks.values()]
    assert "Your skills" not in labels and "Your idea (a digital product)" in labels


def test_reports_can_be_read_inside_the_page(tmp_path):
    from venturegate.views import reports_html
    report = tmp_path / "phase1_step1_weak-intake.md"
    report.write_text("# Idea intake\n\nA CV pack.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n<script>alert(1)</script>",
                      encoding="utf-8")
    shown = reports_html([str(report)], open_first=True)
    assert "<details class=\"vg-report\" open>" in shown and "<h1>Idea intake</h1>" in shown and "<table>" in shown
    assert "<script>" not in shown and "Download" in shown                      # report HTML is never run
    assert " open>" not in reports_html([str(report)])


# == the chat ===================================================================
from venturegate import chat   # noqa: E402


@pytest.mark.parametrize("kind, step, action, text, approve, said", [
    ("confirm", "x:s", "yes", "", True, "Yes, this is right. Continue"),
    ("confirm", "x:s", "no", "", False, "Stop working on this idea"),
    ("confirm", "x:s", "send", "looks good", True, "looks good"),
    ("confirm", "x:s", "send", "ok", True, "ok"),
    ("confirm", "x:s", "send", "Make it cheaper and focus on Cairo", False, "Make it cheaper and focus on Cairo"),
    ("confirm", "x:s", "send", "stop", False, "stop"),
    ("gate", "x:gate1", "send", "yes", True, "yes"),
    ("gate", "x:gate1", "yes", "", True, "Yes, move on to Phase 2: Validate"),
    ("publish", "x:p", "yes", "", True, "Approve (practice only)"),
    ("publish", "x:p", "send", "no", False, "no"),
    ("question", "x:q", "send", "Graduates in Alexandria", None, "Graduates in Alexandria"),
    ("gate", "x:gate2_pivot", "send", "A CV pack for nursing graduates in Egypt", True,
     "A CV pack for nursing graduates in Egypt"),
])
def test_chat_reply_for_each_step(kind, step, action, text, approve, said):
    prompt = "Gate 1 passed. Continue to Phase 2?" if step == "x:gate1" else "?"
    reply, problem, message = chat.reply_for(Request(step, kind, prompt), action, text)
    assert problem is None and reply.approve is approve and message == said
    if approve is False and len(text) > 20:
        assert reply.text == text                     # Steve redoes the step with these changes


@pytest.mark.parametrize("kind, step, action, text, problem", [
    ("confirm", "x:s", "send", "", "Type a message first"),
    ("question", "x:q", "send", "", "Type your answer first"),
    ("question", "x:q", "yes", "", "Choose one of the buttons"),
    ("gate", "x:gate2_pivot", "send", "idk", "one full sentence"),
    ("gate", "x:gate1", "send", "what does this mean exactly?", "press one of the buttons"),
    ("publish", "x:p", "send", "maybe later, after lunch", "press one of the buttons"),
])
def test_chat_refuses_unclear_answers_without_moving_on(kind, step, action, text, problem):
    reply, why, _ = chat.reply_for(Request(step, kind, "?"), action, text)
    assert reply is None and problem in why


def test_every_button_says_what_it_does():
    labels = {k: chat.quick_replies(Request("x:s", k, "Gate 3 passed. Continue to Phase 4?"))
              for k in ("confirm", "gate", "publish", "question")}
    assert labels["confirm"]["yes"] == "Yes, this is right. Continue"
    assert labels["gate"]["yes"] == "Yes, move on to Phase 4: Commercial setup"
    assert "practice only" in labels["publish"]["yes"]
    assert labels["question"]["yes"] is None and labels["question"]["can_type"]
    assert chat.quick_replies(None)["can_type"] is False
    assert "finished" in chat.quick_replies(None, finished=True)["placeholder"]


def test_the_chat_keeps_the_whole_conversation_and_shows_reports_in_it(tmp_path):
    report = tmp_path / "phase1_step1_strong-intake.md"
    report.write_text("# Idea intake\n\n> Run: strong · Model: qwen3:4b · Mode: live\n\nA CV pack.\n\n## Open questions\n\n- Which roles?",
                      encoding="utf-8")
    req = Request("strong:phase1_step1", "confirm", "Idea intake: is this right? Approve...", [str(report)])
    transcript = [Say("Phase 1: Discover", kind="phase", phase=1),
                  Say("Idea intake: A CV pack.", [str(report)], kind="step", phase=1), req,
                  ("founder", "Focus on Cairo"), Say("Revising 'Idea intake' with your changes.")]
    msgs = chat.messages(transcript, None, None)
    roles = [m["role"] for m in msgs]
    assert roles == ["assistant", "assistant", "assistant", "user", "assistant", "assistant"]
    step = msgs[1]["content"]
    assert "Which roles?" in step and "#### Open questions" in step       # the report itself, in the message
    assert "Run: strong" not in step and step.count("Idea intake") == 1  # no technical line, no repeated title
    assert "Does **Idea intake** look right to you?" in msgs[2]["content"]
    assert msgs[-1]["content"] == chat.WORKING                             # Steve is busy: say so
    done = chat.messages(transcript, None, Done("stopped", "12 of 100 sign-ups."))
    assert done[-1]["content"].startswith("**I'm sorry, but I don't think this idea is ready to build")
    assert "12 of 100 sign-ups." in done[-1]["content"] and chat.WORKING not in str(done)


def test_buttons_and_typed_messages_drive_a_whole_run_in_the_chat(app):
    sid, view = start(app, "strong")
    for _ in range(200):
        if view["finished"]:
            break
        q = view["quick"]
        if q["yes"]:
            view = list(app.respond(sid, "yes"))[-1]
        else:
            view = list(app.respond(sid, "send", "Fresh graduates in Cairo"))[-1]
    assert view["finished"] and app.get(sid).done.outcome == "completed"
    users = [m for m in view["chat"] if m["role"] == "user"]
    assert users and all(m["content"] for m in users)
    assert "All six phases are done" in view["chat"][-1]["content"]
