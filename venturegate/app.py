"""The founder console: a local web page at http://localhost:7860 (Gradio).

It drives the same orchestrator as the command line. The founder writes a brief (or loads an
example), then answers each Request with the decision panel: approve, request changes, or stop.
Nothing continues until the founder chooses, and nothing is published, sent or spent without them.

The page logic lives in ConsoleApp (plain Python, tested without a browser); build_ui() only lays
out the components and connects them to it.
"""
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from . import config, views
from .brief import BriefError, FounderBrief
from .events import Done, Reply, Request, Say
from .llm import LLM
from .orchestrator import Pipeline
from .sources import SourceLibrary

EXAMPLES = config.ROOT / "examples"
MODES = {"Live: Steve thinks it through now": "live", "Replay a recorded run (instant)": "replay"}
LIVE, REPLAY = list(MODES)
WEAK_SCENARIO = "Weak: 12 of 100 sign-ups"
STRONG_SCENARIO = "Strong: 134 of 100 sign-ups"
MAX_SESSIONS = 20


def default_factory(brief: FounderBrief, mode: str) -> Pipeline:
    return Pipeline(brief, llm=LLM(mode=mode))


@dataclass
class Session:
    brief: FounderBrief
    pipeline: Pipeline
    events: list = field(default_factory=list)
    pending: Request | None = None
    done: Done | None = None
    started: bool = False

    def __post_init__(self):
        self.generator = self.pipeline.run()

    def advance(self, reply: Reply | None = None):
        """Run until the next Request or the end. Yields after every event so the page can stream."""
        if self.done is not None:
            return
        try:
            if not self.started:
                self.started = True
                event = next(self.generator)
            else:
                if self.pending is None:
                    return
                self.pending = None
                event = self.generator.send(reply)
            while True:
                if isinstance(event, Request):
                    self.pending = event
                    yield
                    return
                self.events.append(event)
                yield
                event = self.generator.send(None)
        except StopIteration as stop:
            self.done = stop.value
            self.pending = None
            yield
        except Exception as exc:                      # anything unexpected must not freeze the page
            self.done = Done("error", f"Unexpected error: {type(exc).__name__}: {exc}")
            self.pending = None
            yield


class ConsoleApp:
    def __init__(self, factory: Callable[[FounderBrief, str], Pipeline] = default_factory):
        self.factory = factory
        self.sessions: "OrderedDict[str, Session]" = OrderedDict()
        self.lock = threading.Lock()
        self.thresholds = yaml.safe_load((config.ROOT / "gates.yaml").read_text(encoding="utf-8"))

    # -- sessions ---------------------------------------------------------
    def _store(self, session: Session) -> str:
        sid = uuid.uuid4().hex
        with self.lock:
            self.sessions[sid] = session
            while len(self.sessions) > MAX_SESSIONS:
                self.sessions.popitem(last=False)
        return sid

    def get(self, sid: str) -> Session | None:
        return self.sessions.get(sid or "")

    # -- the start screen ---------------------------------------------------
    def model_status(self) -> dict:
        llm = LLM()
        return {"model": llm.model, "ready": llm.is_available(), "recorded": llm.recorded_steps()}

    def start_side(self) -> str:
        st = self.model_status()
        web = config.get("WEB_SEARCH", "true").lower() not in ("0", "false", "no", "off")
        return views.start_side_html(model=st["model"], ready=st["ready"], recorded=st["recorded"],
                                     sources_loaded=len(SourceLibrary()), thresholds=self.thresholds, web_search=web)

    def initial_header(self) -> str:
        st = self.model_status()
        return views.header_html(model=st["model"], mode="live", ready=st["ready"])

    def default_mode(self) -> str:
        st = self.model_status()
        return REPLAY if not st["ready"] and st["recorded"] else LIVE

    @staticmethod
    def load_example(name: str) -> dict:
        data = yaml.safe_load((EXAMPLES / f"{name}_idea.yaml").read_text(encoding="utf-8"))
        return {"run": data["run"], "idea": " ".join(str(data["idea"]).split()),
                "skills": ", ".join(data["skills"]), "market": data.get("target_market") or "",
                "budget": data["budget"], "currency": data.get("currency", "USD"),
                "hours": data["hours_per_week"], "values": ", ".join(data.get("values") or []),
                "language": "Arabic" if data.get("language") == "ar" else "English",
                "scenario": data.get("mock_scenario", "strong")}

    def brief_from_form(self, run, idea, skills, market, budget, currency, hours, values, language, scenario):
        return FounderBrief.from_dict({
            "run": run or "my-idea", "idea": idea, "skills": skills, "target_market": market,
            "budget": budget, "currency": currency, "hours_per_week": hours, "values": values,
            "language": "ar" if str(language).startswith("Arab") else "en",
            "mock_scenario": "weak" if str(scenario).lower().startswith("weak") else "strong"})

    # -- running ----------------------------------------------------------
    def start(self, form: dict, mode_label: str):
        """Yields (sid, view) pairs while the run moves forward."""
        try:
            brief = self.brief_from_form(**form)
        except BriefError as exc:
            yield "", {"alert": f"The brief could not be used: {exc}", "screen": "start"}
            return
        session = Session(brief, self.factory(brief, MODES.get(mode_label, "live")))
        sid = self._store(session)
        for _ in session.advance():
            yield sid, self.view(session)

    def respond(self, sid: str, action: str, text: str = ""):
        """action: primary, secondary or quiet. Yields views as the run moves forward."""
        session = self.get(sid)
        if session is None:
            yield {"alert": "This run is no longer available. Start a new brief.", "screen": "start"}
            return
        request = session.pending
        if request is None:
            yield self.view(session)
            return
        text = " ".join((text or "").split())
        reply, problem = self.reply_for(request, action, text)
        if problem:
            yield {**self.view(session), "alert": problem}
            return
        for _ in session.advance(reply):
            yield self.view(session)

    @staticmethod
    def reply_for(request: Request, action: str, text: str) -> tuple[Reply | None, str | None]:
        pivot = request.step_id.endswith("_pivot")
        if request.kind == "question":
            return (Reply(None, text), None) if text else (None, "Type your answer first.")
        if action == "primary":
            if pivot and len(text) < 15:
                return None, "Write the revised idea in one full sentence, or choose Stop here."
            return Reply(True, text), None
        if action == "secondary":
            if not text:
                return None, "Write what should change, or use Stop the run."
            return Reply(False, text), None
        return Reply(False, ""), None

    # -- what the page shows ----------------------------------------------
    def view(self, session: Session) -> dict:
        p = session.pipeline
        min_sourced = self.thresholds["G1_discover"]["min_sourced_claims"]
        files = [str(f) for f in p.ctx.writer.written]
        return {
            "screen": "run",
            "header": views.header_html(model=p.llm.model, mode="replay" if p.llm.used_replay else "live",
                                        ready=True, run=session.brief.run, idea=session.brief.idea,
                                        cost=p.llm.totals["cost"], finished=session.done is not None),
            "rail": views.rail_html(views.rail_state(session.events, session.pending, session.done)),
            "brief": views.brief_html(session.brief),
            "timeline": views.timeline_html(session.events, session.pending, session.done),
            "decision": views.decision_html(session.pending),
            "controls": views.decision_controls(session.pending),
            "evidence": views.evidence_html(p.ctx.ledger.records(session.brief.run), min_sourced,
                                            len(p.ctx.sources)),
            "files": views.records_html(files),
            "finished": session.done is not None,
            "alert": "",
        }


# == the page ==================================================================
START_INTRO = ('<div class="vg" style="display:flex;align-items:center;gap:14px">{emblem}<div>'
               '<h1 style="font-size:25px">Hi, I\'m Steve. What do you want to build?</h1>'
               '<p style="color:#5A5248">I check your idea against evidence, ask you before every step, and tell you '
               'plainly when the evidence says stop.</p></div></div>')


def build_ui(app: ConsoleApp | None = None):
    from functools import partial

    import gradio as gr

    HTML = partial(gr.HTML, padding=False)   # the design sets its own spacing
    app = app or ConsoleApp()
    theme = gr.themes.Base(primary_hue="green", neutral_hue="stone", radius_size="sm",
                           font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"])
    with gr.Blocks(css=views.CSS, head=views.HEAD, title="VentureGate · Steve", theme=theme,
                   analytics_enabled=False) as demo:
        sid = gr.State("")
        run_label = gr.State("my-idea")
        header = HTML(app.initial_header())
        alert = HTML("", elem_classes="vg-message")

        with gr.Row(elem_id="vg-main", equal_height=False):
            with gr.Column(elem_id="vg-left", scale=0, min_width=248):
                rail = HTML(views.rail_html(views.rail_state([], None, None)))
                brief = HTML(views.how_steve_works_html())
            with gr.Column(elem_id="vg-center", scale=1, min_width=420):
                with gr.Column(elem_id="vg-start", visible=True) as start_view:
                    HTML(START_INTRO.format(emblem=views.emblem(44)))
                    with gr.Row():
                        weak_btn = gr.Button("Weak idea: ends in STOP", elem_classes="vg-btn-secondary", size="md")
                        strong_btn = gr.Button("Strong idea: all six phases", elem_classes="vg-btn-secondary", size="md")
                    idea = gr.Textbox(label="Your idea (a digital product)", lines=3,
                                      placeholder="What would you build, and for whom?")
                    with gr.Row():
                        skills = gr.Textbox(label="Your skills", placeholder="writing, web development")
                        market = gr.Textbox(label="Who it is for (optional, Steve will ask)")
                        values = gr.Textbox(label="Your values (optional)", placeholder="honesty, accessibility")
                    with gr.Row():
                        budget = gr.Number(label="Total budget", value=300, minimum=0)
                        currency = gr.Dropdown(["USD", "EGP", "EUR"], value="USD", label="Currency")
                        hours = gr.Number(label="Hours per week", value=10, minimum=0, maximum=168)
                        language = gr.Dropdown(["English", "Arabic"], value="English", label="Language")
                    scenario = gr.Radio([WEAK_SCENARIO, STRONG_SCENARIO], value=STRONG_SCENARIO,
                                        label="Waitlist numbers to test with [SIMULATED]: sample numbers, since there is "
                                              "no real waitlist yet")
                    mode = gr.Radio(list(MODES), value=app.default_mode(), label="How Steve runs")
                    start_btn = gr.Button("Start with Steve", elem_classes="vg-btn-primary")
                with gr.Column(elem_id="vg-run", visible=False) as run_view:
                    timeline = HTML("", elem_id="vg-timeline")
                    with gr.Column(elem_id="vg-dock", visible=False) as dock:
                        decision = HTML("")
                        with gr.Row(equal_height=True):
                            feedback = gr.Textbox(label="What should change?", lines=1, scale=3, min_width=220)
                            primary = gr.Button("Approve and continue", elem_classes="vg-btn-primary", scale=0, min_width=180)
                            secondary = gr.Button("Request changes", elem_classes="vg-btn-secondary", scale=0, min_width=150)
                            quiet = gr.Button("Stop the run", elem_classes="vg-btn-quiet", scale=0, min_width=110)
                    new_btn = gr.Button("Start a new brief", elem_id="vg-new", elem_classes="vg-btn-primary", visible=False)
            with gr.Column(elem_id="vg-right", scale=0, min_width=300):
                side = HTML(app.start_side())
                files = HTML("")
                HTML(views.legend_html())

        form_fields = [idea, skills, market, budget, currency, hours, values, language, scenario]
        outputs = [header, rail, brief, timeline, dock, decision, feedback, primary, secondary, quiet,
                   side, files, start_view, run_view, new_btn, alert]

        def to_updates(view: dict):
            if view.get("screen") == "start":
                return [gr.update()] * (len(outputs) - 1) + [views.alert_html(view.get("alert"))]
            c = view["controls"]
            visible = c.get("visible", False)
            return [view["header"], view["rail"], view["brief"], view["timeline"],
                    gr.update(visible=visible), view["decision"],
                    gr.update(visible=bool(visible and c.get("text_visible")), label=c.get("text_label") or "Text",
                              value=""),
                    gr.update(visible=visible and bool(c.get("primary")), value=c.get("primary") or "OK"),
                    gr.update(visible=visible and bool(c.get("secondary")), value=c.get("secondary") or "Change"),
                    gr.update(visible=visible and bool(c.get("quiet")), value=c.get("quiet") or "Stop"),
                    view["evidence"], view["files"], gr.update(visible=False), gr.update(visible=True),
                    gr.update(visible=view["finished"]), views.alert_html(view.get("alert"))]

        def on_example(name):
            ex = app.load_example(name)
            return (ex["run"], ex["idea"], ex["skills"], ex["market"], ex["budget"], ex["currency"], ex["hours"],
                    ex["values"], ex["language"],
                    WEAK_SCENARIO if ex["scenario"] == "weak" else STRONG_SCENARIO)

        example_outputs = [run_label] + form_fields
        weak_btn.click(lambda: on_example("weak"), None, example_outputs)
        strong_btn.click(lambda: on_example("strong"), None, example_outputs)

        def on_start(label, *values):
            *form_values, mode_label = values
            form = dict(zip(["idea", "skills", "market", "budget", "currency", "hours", "values", "language",
                             "scenario"], form_values), run=label)
            for new_sid, view in app.start(form, mode_label):
                yield [new_sid] + to_updates(view)

        start_btn.click(on_start, [run_label] + form_fields + [mode], [sid] + outputs)

        def on_action(action):
            def handler(current_sid, text):
                for view in app.respond(current_sid, action, text):
                    yield to_updates(view)
            return handler

        primary.click(on_action("primary"), [sid, feedback], outputs)
        secondary.click(on_action("secondary"), [sid, feedback], outputs)
        quiet.click(on_action("quiet"), [sid, feedback], outputs)
        feedback.submit(on_action("primary"), [sid, feedback], outputs)

        def on_new():
            return ["", "my-idea", app.initial_header(), views.rail_html(views.rail_state([], None, None)),
                    views.how_steve_works_html(), "", gr.update(visible=False), "", app.start_side(), "",
                    gr.update(visible=True), gr.update(visible=False), gr.update(visible=False), ""]

        new_btn.click(on_new, None, [sid, run_label, header, rail, brief, timeline, dock, decision, side, files,
                                     start_view, run_view, new_btn, alert])
    return demo


def launch(port: int = 7860) -> None:
    demo = build_ui()
    out_dir = config.path("OUTPUT_DIR", "outputs")
    out_dir.mkdir(parents=True, exist_ok=True)
    demo.queue(default_concurrency_limit=4).launch(
        server_name="0.0.0.0", server_port=port, allowed_paths=[str(out_dir.resolve())], show_api=False)
