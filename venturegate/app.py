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

from . import chat, config, views
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
    transcript: list = field(default_factory=list)   # Say, Request and ("founder", text), in order: the chat
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
                    self.transcript.append(event)
                    yield
                    return
                self.events.append(event)
                self.transcript.append(event)
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

    def welcome(self) -> str:
        llm = LLM()
        ready, why = llm.model_listed() if llm.mode == "live" else (True, "")
        return views.welcome_html(thresholds=self.thresholds, ready=ready, why=why, recorded=llm.recorded_steps())

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
                "market": data.get("target_market") or "",
                "budget": data["budget"], "currency": data.get("currency", "USD"),
                "hours": data["hours_per_week"], "values": ", ".join(data.get("values") or []),
                "language": "Arabic" if data.get("language") == "ar" else "English",
                "scenario": data.get("mock_scenario", "strong")}

    def brief_from_form(self, run, idea, market, budget, currency, hours, values, language, scenario="strong"):
        return FounderBrief.from_dict({
            "run": run or "my-idea", "idea": idea, "target_market": market,
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
        if action in ("yes", "no", "send"):                     # the chat: buttons or a typed message
            reply, problem, said = chat.reply_for(request, action, text)
        else:                                                   # the older decision panel (kept for the CLI tests)
            reply, problem = self.reply_for(request, action, text)
            said = text or {"primary": "Approve", "secondary": "Request changes", "quiet": "Stop"}.get(action, action)
        if problem:
            yield {**self.view(session), "alert": problem}
            return
        session.transcript.append(("founder", said))
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
            "chat": chat.messages(session.transcript, session.pending, session.done),
            "quick": chat.quick_replies(session.pending, finished=session.done is not None),
            "progress": views.progress_html(p.ctx.ledger.records(session.brief.run), min_sourced),
            "alert": "",
        }


# == the page ==================================================================
START_INTRO = ('<div class="vg" style="display:flex;align-items:center;gap:14px">{emblem}<div>'
               '<h1 style="font-size:25px">What do you want to build?</h1>'
               '<p style="color:#5A5248">Describe your idea in a sentence or two. Steve takes it from there and '
               'asks you before every step.</p></div></div>')
STEVE_AVATAR = Path(__file__).resolve().parent / "static" / "steve.svg"


def build_ui(app: ConsoleApp | None = None):
    import warnings

    with warnings.catch_warnings():
        # Gradio 5 prints notices about its next version; they are not errors and only confuse the log.
        warnings.simplefilter("ignore", DeprecationWarning)
        warnings.simplefilter("ignore", UserWarning)
        return _build_ui(app)


def _build_ui(app: ConsoleApp | None = None):
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

        # 1. welcome: what Steve does, then one button to begin
        with gr.Column(elem_id="vg-welcome", visible=True) as welcome_view:
            welcome = HTML(app.welcome())
            with gr.Row():
                begin_btn = gr.Button("Get started: tell Steve your idea", elem_classes="vg-btn-primary")
                replay_btn = gr.Button("Watch a recorded example (instant)", elem_classes="vg-btn-secondary",
                                       visible=app.model_status()["recorded"] > 0)

        # 2. the idea, in a few fields
        with gr.Column(elem_id="vg-start", visible=False) as form_view:
            HTML(START_INTRO.format(emblem=views.emblem(44)))
            example_btn = gr.Button("Fill in an example idea for me", elem_classes="vg-btn-secondary", size="md")
            idea = gr.Textbox(label="Your idea (a digital product)", lines=3,
                              placeholder="What would you like to build, and who is it for?")
            with gr.Row():
                budget = gr.Number(label="Money you can spend in total", value=300, minimum=0)
                currency = gr.Dropdown(["USD", "EGP", "EUR"], value="USD", label="Currency")
                hours = gr.Number(label="Hours you can give each week", value=10, minimum=0, maximum=168)
                language = gr.Dropdown(["English", "Arabic"], value="English", label="Language of the reports")
            with gr.Accordion("More about you and your idea (optional)", open=False):
                with gr.Row():
                    market = gr.Textbox(label="Who is it for?", placeholder="Steve will ask if you leave this empty")
                    values = gr.Textbox(label="What matters to you?", placeholder="honesty, accessibility")
            with gr.Row():
                back_btn = gr.Button("Back to the introduction", elem_classes="vg-btn-quiet", scale=0, min_width=200)
                start_btn = gr.Button("Start working with Steve", elem_classes="vg-btn-primary")

        # 3. the chat with Steve
        with gr.Row(elem_id="vg-main", equal_height=False, visible=False) as run_view:
            with gr.Column(elem_id="vg-left", scale=0, min_width=248):
                rail = HTML(views.rail_html(views.rail_state([], None, None)))
                progress = HTML("", visible=False)       # drawn inside the rail block (see to_updates)
            with gr.Column(elem_id="vg-center", scale=1, min_width=420):
                chatbot = gr.Chatbot(type="messages", elem_id="vg-chat", show_label=False, height="calc(100vh - 250px)",
                                     latex_delimiters=[], avatar_images=(None, str(STEVE_AVATAR)),
                                     placeholder="Steve is getting ready…")
                with gr.Row(elem_id="vg-quick"):
                    yes_btn = gr.Button("Yes", elem_classes="vg-btn-primary", visible=False)
                    no_btn = gr.Button("Stop", elem_classes="vg-btn-secondary", visible=False)
                with gr.Row(equal_height=True):
                    msg = gr.Textbox(show_label=False, lines=1, max_lines=4, scale=5, container=False,
                                     placeholder="Steve is working. You can reply when he asks you something.",
                                     interactive=False)
                    send_btn = gr.Button("Send", elem_classes="vg-btn-primary", scale=0, min_width=110,
                                         interactive=False)
                    new_btn = gr.Button("Start over with a new idea", elem_id="vg-new", elem_classes="vg-btn-secondary",
                                        scale=0, min_width=230)

        form_fields = [idea, market, budget, currency, hours, values, language]
        outputs = [header, rail, progress, chatbot, yes_btn, no_btn, msg, send_btn,
                   welcome_view, form_view, run_view, alert]

        def to_updates(view: dict):
            if view.get("screen") == "start":
                return [gr.update()] * 8 + [gr.update(visible=False), gr.update(visible=True),
                                            gr.update(visible=False), views.alert_html(view.get("alert"))]
            q = view["quick"]
            keep_text = bool(view.get("alert"))             # a problem with the message: let the founder fix it
            return [view["header"], view["rail"] + view["progress"], "", view["chat"],
                    gr.update(visible=bool(q["yes"]), value=q["yes"] or "Yes"),
                    gr.update(visible=bool(q["no"]), value=q["no"] or "Stop"),
                    gr.update(placeholder=q["placeholder"], interactive=q["can_type"],
                              **({} if keep_text else {"value": ""})),
                    gr.update(interactive=q["can_type"]),
                    gr.update(visible=False), gr.update(visible=False), gr.update(visible=True),
                    views.alert_html(view.get("alert"))]

        begin_btn.click(lambda: (gr.update(visible=False), gr.update(visible=True), ""), None,
                        [welcome_view, form_view, alert])
        back_btn.click(lambda: (gr.update(visible=True), gr.update(visible=False), ""), None,
                       [welcome_view, form_view, alert])

        def on_example():
            ex = app.load_example("strong")
            return (ex["run"], ex["idea"], ex["market"], ex["budget"], ex["currency"], ex["hours"],
                    ex["values"], ex["language"])

        example_btn.click(on_example, None, [run_label] + form_fields)

        def on_start(label, *form_values):
            form = dict(zip(["idea", "market", "budget", "currency", "hours", "values", "language"], form_values),
                        run=label)
            for new_sid, view in app.start(form, LIVE):
                yield [new_sid] + to_updates(view)

        start_btn.click(on_start, [run_label] + form_fields, [sid] + outputs)

        def on_replay():
            ex = app.load_example("strong")
            form = {k: ex[k] for k in ("idea", "market", "budget", "currency", "hours", "values", "language")}
            for new_sid, view in app.start({**form, "run": ex["run"]}, REPLAY):
                yield [new_sid] + to_updates(view)

        replay_btn.click(on_replay, None, [sid] + outputs)

        def on_action(action):
            def handler(current_sid, text):
                for view in app.respond(current_sid, action, text):
                    yield to_updates(view)
            return handler

        yes_btn.click(on_action("yes"), [sid, msg], outputs)
        no_btn.click(on_action("no"), [sid, msg], outputs)
        send_btn.click(on_action("send"), [sid, msg], outputs)
        msg.submit(on_action("send"), [sid, msg], outputs)

        def on_new():
            return ["", "my-idea", app.initial_header(), views.rail_html(views.rail_state([], None, None)), "", [],
                    gr.update(visible=False), gr.update(visible=False), gr.update(value="", interactive=False),
                    gr.update(interactive=False), gr.update(visible=False), gr.update(visible=True),
                    gr.update(visible=False), ""]

        new_btn.click(on_new, None, [sid, run_label, header, rail, progress, chatbot, yes_btn, no_btn, msg, send_btn,
                                     welcome_view, form_view, run_view, alert])
    return demo


def launch(port: int = 7860) -> None:
    demo = build_ui()
    out_dir = config.path("OUTPUT_DIR", "outputs")
    out_dir.mkdir(parents=True, exist_ok=True)
    demo.queue(default_concurrency_limit=4).launch(
        server_name="0.0.0.0", server_port=port, allowed_paths=[str(out_dir.resolve())], show_api=False)
