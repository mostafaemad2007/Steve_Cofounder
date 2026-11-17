"""The orchestrator: six phases, founder confirmations, gates, and the STOP decision.

It is a generator, so the web UI, the command line and the tests drive the same code:

    events = Pipeline(brief).run()     # yields Say and Request, returns Done
    done = drive(events, handler)      # handler(event) must return a Reply for each Request

Rules enforced here
- The brief, every founder answer and every piece of founder feedback pass guard.pre_check first.
- After each step the founder approves it, or rejects it with changes (the step is redone with that
  feedback), or rejects it with no text, which stops the run.
- Each phase ends with a gate (gates.py, thresholds locked from gates.yaml). go continues; repeat
  redoes the phase; pivot asks the founder for a revised idea or stops; stop ends the run with a
  plain STOP report.
- Opening the store, publishing posts and sending replies need explicit approval and are MOCKED:
  nothing leaves this machine.
"""
import json
import time
from pathlib import Path
from typing import Callable, Generator

from . import config
from .agents import (BuildAgent, CommercialAgent, DiscoverAgent, LaunchAgent, OperateAgent, OutputRejected,
                     RunContext, ValidateAgent)
from .approval import Approvals
from .brief import FounderBrief
from .delivery import AccessStore
from .events import Done, Reply, Request, Say
from .gates import GateDecision, Gates, ThresholdLocked
from .guard import Guard
from .ledger import EvidenceLedger
from .llm import LLM, REPLAY_TAG, BadModelOutput, ModelUnavailable
from .logger import DecisionLogger, now_iso
from .mock_flow import run_mock_flow
from .outputs import OutputWriter
from .sources import SourceLibrary
from .websearch import default_library

Events = Generator[object, object, object]

PHASE_TITLES = {1: "Discover", 2: "Validate", 3: "Build", 4: "Commercial setup", 5: "Launch",
                6: "Operate and learn"}
GATE_NAMES = {1: "evidence", 2: "demand", 3: "tests", 4: "commercial", 5: "sale-to-cash", 6: "memo"}
WHAT_WOULD_CHANGE = {
    1: ["More real sources supporting demand, and a clear gap against competitors.",
        "A budget that covers the planning period, or a cheaper way to build and run the product.",
        "Enough weekly time, or a partner who covers the blocking skill gap."],
    2: ["Real sign-ups reaching the pre-set target in a fresh test with a sharper offer or segment.",
        "Interview notes showing people already spend time or money on this problem."],
    3: ["An MVP whose automatic tests all pass, with complete user docs."],
    4: ["Policies labelled as drafts and a price the founder approves."],
    5: ["A mock sale-to-delivery flow that passes every check."],
    6: ["Demand signals at or above target, and a budget covering the planning period."],
}
RUN_ERRORS = (ModelUnavailable, BadModelOutput, OutputRejected, ThresholdLocked)


class FounderStopped(Exception):
    """The founder chose to stop the run."""


def drive(events: Events, handler: Callable[[object], Reply | None]) -> Done:
    """Run a pipeline to the end. handler receives every Say and Request; it must return a Reply for
    each Request (its return value for a Say is ignored)."""
    try:
        event = next(events)
        while True:
            reply = handler(event)
            event = events.send(reply if isinstance(event, Request) else None)
    except StopIteration as stop:
        return stop.value


class Pipeline:
    max_revisions = 3       # founder change requests per step
    max_pivots = 1          # times the founder may revise the idea after a pivot recommendation

    def __init__(self, brief: FounderBrief, *, llm: LLM | None = None, logger: DecisionLogger | None = None,
                 ledger: EvidenceLedger | None = None, sources: SourceLibrary | None = None,
                 out_dir: Path | None = None, state_dir: Path | None = None, gates_path: Path | None = None):
        self.brief = brief
        self.logger = (logger or DecisionLogger()).for_run(brief.run)
        self.llm = llm or LLM(logger=self.logger)
        self.llm.logger = self.logger
        self.out_dir = Path(out_dir) if out_dir else config.path("OUTPUT_DIR", "outputs")
        state_dir = Path(state_dir) if state_dir else config.path("STATE_DIR", ".state")
        self.approvals = Approvals(state_dir / "approvals.json", self.logger)
        self.access = AccessStore(state_dir / f"access-{brief.run}.json")
        self.gates_path = gates_path
        self.gates: Gates | None = None
        writer = OutputWriter(brief.run, self.out_dir,
                              status=lambda: {"model": self.llm.model, "replay": self.llm.used_replay})
        self.ctx = RunContext(
            brief=brief, llm=self.llm, guard=Guard(self.logger), logger=self.logger, writer=writer,
            ledger=(ledger or EvidenceLedger(self.out_dir / "evidence_ledger.json")).for_run(brief.run),
            sources=sources if sources is not None else default_library(self.llm.mode, self.logger))
        self.pivots = 0
        self._notices_seen: set[str] = set()
        self.phase = 0

    # == entry point ==========================================================
    def run(self) -> Events:
        started = time.monotonic()
        b = self.brief
        self.approvals.clear(f"{b.run}:")
        self.ctx.ledger.reset_run(b.run)
        try:
            self.gates = Gates(self.gates_path, self.logger) if self.gates_path else Gates(logger=self.logger)
            self.logger.log("orchestrator", "start_run", run_mode=self.llm.mode, llm_model=self.llm.model,
                            web_search=getattr(self.ctx.sources, "live", False),
                            sources_loaded=len(self.ctx.sources), simulated_scenario=b.mock_scenario)
            done = yield from self._run()
        except FounderStopped as exc:
            done = Done("stopped_by_founder", str(exc))
        except RUN_ERRORS as exc:
            self.logger.log("orchestrator", "run_error", error=f"{type(exc).__name__}: {str(exc)[:300]}")
            done = Done("error", f"The run could not continue: {exc}")
        done.files = [str(p) for p in self.ctx.writer.written]
        self._cost_report(done, time.monotonic() - started)
        self.logger.log("orchestrator", "end_run", result=done.outcome, last_gate=done.last_gate)
        yield Say(f"Run finished: {done.outcome.replace('_', ' ').upper()}. {done.summary}", kind="done",
                  outcome=done.outcome)
        return done

    def _run(self) -> Events:
        b = self.brief
        mode = f" ({REPLAY_TAG}, replaying a recorded real run)" if self.llm.mode == "replay" else ""
        live_web = getattr(self.ctx.sources, "live", False)
        evidence = ("Steve searches the web for evidence at each research step" if live_web
                    else f"Steve uses the {len(self.ctx.sources)} evidence page(s) saved in sources/")
        yield Say(f"Steve is starting{mode}. {evidence}. The waitlist numbers in this run are [SIMULATED] sample "
                  f"data ('{b.mock_scenario}').")
        if self.llm.mode == "live" and self.llm.uses_ollama:
            ok, why = self.llm.model_listed()
            if ok:
                yield Say("Steve is waking up: loading his model. The first time can take a minute or two.", kind="info")
                ok, why, seconds = self.llm.warm_up()
                self.logger.log("orchestrator", "warm_up_model", llm_model=self.llm.model, ok=ok,
                                seconds=round(seconds, 1))
            if not ok:
                self.logger.log("orchestrator", "model_not_ready", reason=why[:200])
                return Done("error", why)
        if not live_web and len(self.ctx.sources) < self.gates.thresholds["G1_discover"]["min_sourced_claims"]:
            yield Say(f"Only {len(self.ctx.sources)} page(s) are saved in sources/. Gate 1 needs "
                      f"{self.gates.thresholds['G1_discover']['min_sourced_claims']} claims backed by real "
                      "sources, so this run may stop at Gate 1.", kind="notice")
        refused = self.ctx.guard.pre_check(b.as_text(), agent="orchestrator")
        if not refused.allowed:
            path = self.ctx.writer.write(1, 1, "refusal", f"# Request refused\n\n{refused.reason}\n\n"
                                         f"Category: `{refused.category}`. Nothing else was run.")
            yield Say(f"Refused: {refused.reason}", [str(path)], kind="refusal")
            return Done("refused", refused.reason or "")

        while True:
            result = yield from self.phase1()
            if result == "restart":
                continue
            if isinstance(result, Done):
                return result
            result = yield from self.phase2()
            if result == "restart":
                continue
            if isinstance(result, Done):
                return result
            break
        for phase in (self.phase3, self.phase4, self.phase5, self.phase6):
            result = yield from phase()
            if isinstance(result, Done):
                return result
        return result

    # == talking to the founder ===============================================
    def _sid(self, key: str) -> str:
        return f"{self.brief.run}:{key}"

    def _notices(self) -> Events:
        for notice in self.llm.notices + list(getattr(self.ctx.sources, "notices", [])):
            if notice not in self._notices_seen:
                self._notices_seen.add(notice)
                yield Say(notice, kind="notice")

    def _start_phase(self, number: int, note: str = "") -> Say:
        self.phase = number
        return Say(f"Phase {number}: {PHASE_TITLES[number]}{note}", kind="phase", phase=number)

    def ask(self, key: str, kind: str, prompt: str, files=()) -> Events:
        """An approve/reject decision. Recorded in approvals.json and the log (approved_by: founder)."""
        sid = self._sid(key)
        self.approvals.request(sid, kind=kind, summary=prompt)
        reply = yield Request(sid, kind, prompt, [str(f) for f in files])
        if not isinstance(reply, Reply) or reply.approve is None:
            reply = Reply(False, reply.text if isinstance(reply, Reply) else "")
        if reply.approve:
            self.approvals.approve(sid)
        else:
            self.approvals.reject(sid, reply.text)
        return reply

    def question(self, key: str, prompt: str) -> Events:
        """A free-text answer, checked by the guard. Asked again until it is usable."""
        while True:
            reply = yield Request(self._sid(key), "question", prompt)
            answer = " ".join((reply.text if isinstance(reply, Reply) else "").split())
            if not answer:
                yield Say("An answer is needed to continue.", kind="notice")
                continue
            verdict = self.ctx.guard.pre_check(answer, agent="orchestrator")
            if verdict.allowed:
                self.logger.log("founder", f"answer:{key}", answer=answer[:200])
                return answer
            yield Say(f"That answer was refused: {verdict.reason}", kind="refusal")

    def step(self, key: str, title: str, fn, *, confirm: bool = True, prompt: str | None = None,
             feedback: str | None = None) -> Events:
        """Run fn(feedback) -> StepResult, show it, then get the founder's confirmation or changes."""
        for _ in range(self.max_revisions + 1):
            result = fn(feedback)
            yield from self._notices()
            yield Say(f"{title}: {result.summary}", [str(p) for p in result.files], kind="step", phase=self.phase)
            if not confirm:
                return result
            while True:
                reply = yield from self.ask(key, "confirm", prompt or (
                    f"{title}: is this right? Approve to continue, or reject and say what to change. "
                    "Rejecting with no text stops the run."), result.files)
                if reply.approve:
                    return result
                text = " ".join(reply.text.split())
                if not text:
                    raise FounderStopped(f"The founder stopped the run at: {title}.")
                verdict = self.ctx.guard.pre_check(text, agent="orchestrator")
                if verdict.allowed:
                    feedback = text
                    self.logger.log("orchestrator", f"revise:{key}", feedback=text[:200])
                    yield Say(f"Revising '{title}' with your changes.", kind="info")
                    break
                yield Say(f"That change request was refused: {verdict.reason}", kind="refusal")
        raise FounderStopped(f"'{title}' was revised {self.max_revisions} times without agreement, so the run stopped.")

    # == gates ================================================================
    def gate_report(self, phase: int, decision: GateDecision) -> Path:
        title = f"Gate {phase} ({GATE_NAMES[phase]}): {decision.outcome.upper()}"
        md = decision.to_markdown(title)
        if decision.outcome == "stop":
            md += ("\n## What this means\n\nThe system recommends **STOP**. This is the pre-registered rule applied "
                   "to the evidence, not an opinion, and it is not softened. Continuing would mean spending time "
                   "and money without the evidence the plan needs.\n\n## What would change this decision\n\n"
                   + "\n".join(f"- {item}" for item in WHAT_WOULD_CHANGE[phase]) + "\n")
        elif decision.outcome == "pivot":
            md += ("\n## What this means\n\nThe evidence does not support continuing as it stands. The system "
                   "recommends **PIVOT**: change the segment, the offer or the idea and run Phase 1 again, or stop.\n")
        return self.ctx.writer.gate(phase, f"{GATE_NAMES[phase]}-{decision.outcome}", md)

    def _say_gate(self, phase: int, decision: GateDecision, path: Path) -> Say:
        data = {"metrics": dict(decision.metrics), "reasons": list(decision.reasons), "name": GATE_NAMES[phase]}
        if decision.outcome == "stop":
            data["what_would_change"] = list(WHAT_WOULD_CHANGE[phase])
        return Say(f"Gate {phase}: {decision.outcome.upper()}. " + " ".join(decision.reasons), [str(path)],
                   kind="gate", phase=phase, outcome=decision.outcome, data=data)

    def handle_gate(self, phase: int, decision: GateDecision, *, approve_go: bool = True) -> Events:
        """None to continue, "restart" to pivot back to Phase 1, "repeat", or a Done."""
        path = self.gate_report(phase, decision)
        yield self._say_gate(phase, decision, path)
        if decision.outcome == "go":
            if approve_go:
                reply = yield from self.ask(f"gate{phase}", "gate",
                                            f"Gate {phase} passed. Continue to Phase {phase + 1}?", [path])
                if not reply.approve:
                    raise FounderStopped(f"The founder chose not to continue after Gate {phase}.")
            return None
        if decision.outcome == "repeat":
            return "repeat"
        if decision.outcome == "pivot" and self.pivots < self.max_pivots:
            reply = yield from self.ask(
                f"gate{phase}_pivot", "gate",
                "The gate recommends PIVOT. To pivot, approve and write the revised idea in the text box: the run "
                "goes back to Phase 1. To stop here, reject.", [path])
            revised = " ".join(reply.text.split())
            if reply.approve and len(revised) >= 15:
                verdict = self.ctx.guard.pre_check(revised, agent="orchestrator")
                if verdict.allowed:
                    self.pivots += 1
                    self.brief.idea = revised
                    self.ctx.state.clear()
                    self.ctx.ledger.reset_run(self.brief.run)
                    self.logger.log("orchestrator", "pivot_back", to_phase=1, revised_idea=revised[:200])
                    yield Say("Pivoting: Phase 1 runs again with the revised idea.", kind="info")
                    return "restart"
                yield Say(f"The revised idea was refused: {verdict.reason}", kind="refusal")
            elif reply.approve:
                yield Say("A pivot needs the revised idea in one full sentence.", kind="notice")
        if decision.outcome == "pivot":
            reasons = decision.reasons + ["No pivot was made, so the recommendation becomes STOP."]
            decision = GateDecision(decision.gate, "stop", reasons, decision.metrics)
            self.logger.log("gate", f"{decision.gate}_decision", outcome="stop", reasons=reasons[:6])
            path = self.gate_report(phase, decision)
            yield self._say_gate(phase, decision, path)
        return Done("stopped", " ".join(decision.reasons), last_gate=decision.gate)

    # == the phases ===========================================================
    def phase1(self) -> Events:
        b, agent = self.brief, DiscoverAgent(self.ctx)
        yield self._start_phase(1)
        intake = yield from self.step("phase1_step1", "Idea intake", agent.intake)
        if not intake.data["in_scope"]:
            reason = intake.data["excluded_category"] or "not a digital product"
            path = self.ctx.writer.write(1, 1, "refusal", f"# Out of scope\n\nThis idea is out of scope: {reason}.\n\n"
                                         "VentureGate works only on digital products. Physical goods; financial, "
                                         "investment or crypto products; and health or legal advice products are excluded.")
            self.logger.log("guard", "refuse_request", category="excluded_product", detail=reason)
            yield Say(f"Refused: the idea is out of scope ({reason}).", [str(path)], kind="refusal")
            return Done("refused", f"Out of scope: {reason}.")
        yield from self.step("phase1_step2", "Opportunities and honest verdict", agent.opportunities)
        if not b.target_market:
            b.target_market = yield from self.question(
                "phase1_target_market", "Who is your target market? Name the place, the kind of customer and their language.")
        yield from self.step("phase1_step3", "Target market fit", agent.market)
        yield from self.step("phase1_step4", "Improvements and IP check", agent.improvements_ip)
        yield from self.step("phase1_step5", "Costs and runway", agent.costs)
        yield from self.step("phase1_step6", "Customer interview script", agent.interview_script)
        st = self.ctx.state
        decision = self.gates.g1_discover(
            alternatives=st.get("alternatives", 0), sourced_claims=self.ctx.ledger.sourced_count(b.run),
            runway_months=st["costs"]["runway_months"], hours_per_week=b.hours_per_week,
            skills_blocking=st.get("skills_blocking", False))
        return (yield from self.handle_gate(1, decision))

    def phase2(self) -> Events:
        agent = ValidateAgent(self.ctx)
        yield self._start_phase(2)
        yield from self.step("phase2_step1", "Lean Canvas", agent.lean_canvas)
        yield from self.step("phase2_step2", "Landing page draft", agent.landing_page)
        demand = yield from self.step("phase2_step3", "Demand signals [SIMULATED]", lambda fb: agent.demand(),
                                      confirm=False)
        signups = demand.data["signups"]
        target = self.gates.thresholds["G2_validate"]["signup_target"]
        approved = False
        if signups["count"] >= target:
            reply = yield from self.ask("gate2_approval", "gate",
                                        f"{signups['count']} of {target} sign-ups [SIMULATED]: the target is met. "
                                        "Continue to the build phase?", demand.files)
            approved = bool(reply.approve)
        decision = self.gates.g2_validate(signups=signups, founder_approved=approved)
        result = yield from self.handle_gate(2, decision, approve_go=False)
        if result is not None:
            return result
        yield from self.step("phase2_step4", "Detailed plan", agent.plan, prompt=(
            "Final confirmation: this is the detailed plan for the agreed idea. Approve to start building, or "
            "reject with changes."))
        return None

    def phase3(self) -> Events:
        agent = BuildAgent(self.ctx)
        yield self._start_phase(3)
        feedback, revisions = None, 0
        while True:
            result = yield from self.step("phase3_step1", "MVP build and tests", agent.mvp, confirm=False,
                                          feedback=feedback)
            decision = self.gates.g3_build(tests_passed=result.data["tests_passed"],
                                           user_docs_exist=result.data["user_docs_exist"])
            outcome = yield from self.handle_gate(3, decision, approve_go=False)
            if outcome == "repeat":
                feedback = "Fix these failing MVP tests: " + "; ".join(result.data.get("failing_details") or result.data["failing"])
                continue
            if isinstance(outcome, Done):
                return outcome
            # Every change the founder asks for goes back through Gate 3.
            reply = yield from self.ask("phase3_review", "confirm",
                                        "The MVP passed its automatic tests. Approve it, or reject and say what to "
                                        "change. Rejecting with no text stops the run.", result.files)
            if reply.approve:
                return None
            text = " ".join(reply.text.split())
            if not text or revisions >= self.max_revisions:
                raise FounderStopped("The founder stopped the run at the MVP review.")
            verdict = self.ctx.guard.pre_check(text, agent="orchestrator")
            if not verdict.allowed:
                yield Say(f"That change request was refused: {verdict.reason}", kind="refusal")
                feedback = None
                continue
            feedback, revisions = text, revisions + 1

    def phase4(self) -> Events:
        agent = CommercialAgent(self.ctx)
        yield self._start_phase(4, " (no payments of any kind)")
        yield from self.step("phase4_step1_price", "Pricing", agent.pricing, prompt=(
            "Do you approve this price? Approve, or reject and write the price or changes you want."))
        feedback = None
        while True:
            yield from self.step("phase4_step2", "Draft policies", agent.policies, feedback=feedback)
            decision = self.gates.g4_commercial(drafts=self.ctx.state["policies"], price_approved=True)
            outcome = yield from self.handle_gate(4, decision, approve_go=False)
            if outcome != "repeat":
                return outcome
            feedback = "Fix: " + " ".join(decision.reasons)

    def phase5(self) -> Events:
        agent = LaunchAgent(self.ctx)
        yield self._start_phase(5, " (store and delivery are MOCKED)")
        store = yield from self.step("phase5_step1", "Store page", agent.store_page)
        reply = yield from self.ask("phase5_open_store", "publish",
                                    "Open the MOCKED store? Nothing goes online: this only lets simulated orders "
                                    "be delivered.", store.files)
        if not reply.approve:
            raise FounderStopped("The founder chose not to open the store.")
        posts = yield from self.step("phase5_step2", "Launch post drafts", agent.launch_posts)
        reply = yield from self.ask("phase5_publish_posts", "publish",
                                    "Publish the launch posts? (MOCKED: they are marked approved; nothing is posted.)",
                                    posts.files)
        if reply.approve:
            self.approvals.run_approved(self._sid("phase5_publish_posts"), lambda: None, agent="launch",
                                        action_name="publish_launch_posts_MOCKED")
            yield Say("Launch posts approved. MOCKED publish: nothing was posted anywhere.", kind="info")
        else:
            yield Say("Launch posts were not approved, so they stay as drafts.", kind="info")
        log_path = self.out_dir / "payment_test_log.md"
        while True:
            flow = run_mock_flow(approvals=self.approvals, store=self.access, logger=self.logger,
                                 report_path=log_path, store_step_id=self._sid("phase5_open_store"),
                                 run=self.brief.run)
            if log_path not in self.ctx.writer.written:
                self.ctx.writer.written.append(log_path)
            yield Say("Automatic delivery (MOCKED): payment triggers delivery, a refund revokes access, a repeated "
                      "event delivers once, and orders reconcile by ID.", [str(log_path)], kind="step", phase=5)
            decision = self.gates.g5_launch(mock_flow=flow)
            outcome = yield from self.handle_gate(5, decision, approve_go=False)
            if outcome != "repeat":
                return outcome

    def phase6(self) -> Events:
        agent = OperateAgent(self.ctx)
        yield self._start_phase(6)
        support = yield from self.step("phase6_step1", "Support reply drafts", agent.support)
        reply = yield from self.ask("phase6_send_replies", "send",
                                    "Send these support replies? (MOCKED: nothing is sent.)", support.files)
        if reply.approve:
            self.approvals.run_approved(self._sid("phase6_send_replies"), lambda: None, agent="operate",
                                        action_name="send_support_replies_MOCKED")
        metrics = yield from self.step("phase6_step2", "Metrics", lambda fb: agent.metrics(), confirm=False)
        outcome, reasons, _ = self.gates.g6_outcome(signups=metrics.data["signups"],
                                                     runway_months=metrics.data["runway_months"])
        feedback = None
        while True:
            memo = yield from self.step("phase6_step3", "Persevere-or-pivot memo",
                                        lambda fb: agent.memo(outcome, reasons, fb), feedback=feedback)
            decision = self.gates.g6_operate(memo=memo.data["memo"], signups=metrics.data["signups"],
                                             runway_months=metrics.data["runway_months"])
            if decision.outcome == "repeat":
                feedback = " ".join(decision.reasons)
                continue
            path = self.gate_report(6, decision)
            yield self._say_gate(6, decision, path)
            label = {"go": "PERSEVERE", "pivot": "PIVOT", "stop": "STOP"}[decision.outcome]
            return Done("completed", f"All six phases are complete. Final recommendation: {label}.", last_gate="G6")

    # == reporting ============================================================
    def _cost_report(self, done: Done, wall_seconds: float) -> None:
        path = self.out_dir / "cost_report.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except json.JSONDecodeError:
            data = {}
        runs = data.get("runs", {})
        totals = self.llm.totals
        runs[self.brief.run] = {
            "finished_at": now_iso(), "outcome": done.outcome, "last_gate": done.last_gate,
            "model": self.llm.model, "mode": "replay" if self.llm.used_replay else "live",
            "model_calls": totals["calls"], "tokens": totals["tokens"], "cost_usd": round(totals["cost"], 4),
            "model_seconds": round(totals["seconds"], 1), "wall_seconds": round(wall_seconds, 1),
        }
        report = {"currency": "USD",
                  "note": "Local open-weight model: $0 per token. Each run's cost is the sum of the cost fields "
                          "in decision_log.json for that run.",
                  "runs": runs, "total_cost_usd": round(sum(r["cost_usd"] for r in runs.values()), 4)}
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
