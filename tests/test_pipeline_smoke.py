"""Part 9: whole runs through the orchestrator, with a scripted fake model and a scripted founder.

The two demo runs (weak ends in STOP at Gate 2, strong completes all six phases) plus the paths a
real founder or a real failure can take: refusals, rejections, pivots, failing MVP tests, a model
that goes down, replay, and someone editing gates.yaml mid-run.
"""
import json
import re
import shutil
from pathlib import Path

import pytest

from fake_model import FakeModel, RESPONSES, variant
from venturegate.brief import FounderBrief
from venturegate.events import Done, Reply, Request, Say
from venturegate.llm import LLM, ModelUnavailable
from venturegate.logger import DecisionLogger, validate_entry
from venturegate.orchestrator import Pipeline, drive
from venturegate.sources import SourceLibrary

ROOT = Path(__file__).resolve().parent.parent
SOURCE_TEXT = ("CV templates competitors pricing price graduates Egypt engineering students tech jobs hosting "
               "domain month cost trademark licence terms copyright fonts free alternatives market chatbot app")
OUTPUT_NAME = re.compile(r"^phase[1-6]_(step\d+|gate)_[a-z0-9-]+\.(md|html)$")


class Founder:
    """Approves everything by default. `script` maps a step-id suffix to a list of Replies used in order."""

    def __init__(self, script=None, on_request=None):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.requests: list[Request] = []
        self.says: list[Say] = []
        self.on_request = on_request

    def __call__(self, event):
        if isinstance(event, Say):
            self.says.append(event)
            return None
        self.requests.append(event)
        if self.on_request:
            self.on_request(event)
        key = event.step_id.split(":", 1)[1]
        if self.script.get(key):
            return self.script[key].pop(0)
        return Reply(None, "Fresh graduates in Egypt") if event.needs_text else Reply(True, "")

    def asked(self, key):
        return [r for r in self.requests if r.step_id.endswith(":" + key)]


class Harness:
    def __init__(self, tmp_path, brief="strong", overrides=None, transport=None, mode="live", n_sources=3,
                 **changes):
        self.tmp = tmp_path
        self.sources = tmp_path / "sources"
        self.sources.mkdir(exist_ok=True)
        for i in range(1, n_sources + 1):
            (self.sources / f"s{i}.md").write_text(
                f"URL: https://example.org/source-{i}\nTitle: Source {i}\n\n{SOURCE_TEXT} page {i}", encoding="utf-8")
        self.gates_path = tmp_path / "gates.yaml"
        if not self.gates_path.exists():
            shutil.copy(ROOT / "gates.yaml", self.gates_path)
        self.logger = DecisionLogger(tmp_path / "decision_log.json")
        self.model = FakeModel(overrides)
        self.llm = LLM(mode=mode, model="qwen3:4b", logger=self.logger, replay_dir=tmp_path / "replay",
                       transport=transport or self.model)
        data = FounderBrief.load(ROOT / "examples" / f"{brief}_idea.yaml").to_dict()
        data.update(changes)
        self.brief = FounderBrief.from_dict(data)
        self.out = tmp_path / "outputs"

    def run(self, founder=None) -> Done:
        self.founder = founder or Founder()
        pipeline = Pipeline(self.brief, llm=self.llm, logger=self.logger, sources=SourceLibrary(self.sources),
                            out_dir=self.out, state_dir=self.tmp / "state", gates_path=self.gates_path)
        self.done = drive(pipeline.run(), self.founder)
        self.log = self.logger.read()
        return self.done

    def files(self):
        return sorted(p.name for p in self.out.glob("*") if p.is_file())

    def actions(self):
        return [e["action"] for e in self.log]

    def gates(self):
        return [(e["action"].split("_")[0], e["outcome"]) for e in self.log if e["agent"] == "gate"]


def assert_log_is_valid(log):
    for entry in log:
        validate_entry(entry)


# == the two demo runs ========================================================
def test_weak_idea_stops_at_gate_two_with_twelve_of_a_hundred(tmp_path):
    h = Harness(tmp_path, "weak")
    done = h.run()

    assert done.outcome == "stopped" and done.last_gate == "G2"
    assert h.gates() == [("G1", "go"), ("G2", "stop")]
    stop = (h.out / "phase2_gate_weak-demand-stop.md").read_text(encoding="utf-8")
    assert "12 of 100" in stop and "[SIMULATED]" in stop and "STOP" in stop
    assert "What would change this decision" in stop
    assert not any(n.startswith(("phase3", "phase4", "phase5", "phase6")) for n in h.files())
    assert "payment_test_log.md" not in h.files()
    assert_log_is_valid(h.log)


def test_strong_idea_completes_all_six_phases(tmp_path):
    h = Harness(tmp_path, "strong")
    done = h.run()

    assert done.outcome == "completed" and done.last_gate == "G6"
    assert h.gates() == [("G1", "go"), ("G2", "go"), ("G3", "go"), ("G4", "go"), ("G5", "go"), ("G6", "go")]
    files = h.files()
    for phase in range(1, 7):
        assert any(n.startswith(f"phase{phase}_step") for n in files), f"no step output for phase {phase}"
        assert any(n.startswith(f"phase{phase}_gate") for n in files), f"no gate output for phase {phase}"
    assert {"payment_test_log.md", "cost_report.json", "evidence_ledger.json"} <= set(files)
    assert all(OUTPUT_NAME.match(n) for n in files if n.startswith("phase")), files
    assert "PERSEVERE" in (h.out / "phase6_step3_strong-memo.md").read_text(encoding="utf-8")
    assert_log_is_valid(h.log)


def test_every_outward_action_follows_a_founder_approval(tmp_path):
    h = Harness(tmp_path, "strong")
    h.run()
    actions = h.actions()
    for outward, approval in (("publish_launch_posts_MOCKED", "approve:strong:phase5_publish_posts"),
                              ("send_support_replies_MOCKED", "approve:strong:phase6_send_replies"),
                              ("deliver_product", "approve:strong:phase5_open_store")):
        assert outward in actions and approval in actions
        assert actions.index(approval) < actions.index(outward), outward
    published = [e for e in h.log if e["action"].endswith("_MOCKED")]
    assert published and all(e["approved_by"] == "founder" for e in published)
    approvals = [e for e in h.log if e["action"].startswith("approve:")]
    assert approvals and all(e["approved_by"] == "founder" for e in approvals)
    assert not [e for e in h.log if e["approved_by"] == "founder" and e["agent"] not in ("founder", "launch", "operate")]


def test_the_founder_is_asked_after_every_step(tmp_path):
    h = Harness(tmp_path, "strong")
    h.run()
    confirmed = {r.step_id.split(":")[1] for r in h.founder.requests if r.kind == "confirm"}
    for key in ("phase1_step1", "phase1_step2", "phase1_step3", "phase1_step4", "phase1_step5", "phase1_step6",
                "phase2_step1", "phase2_step2", "phase2_step4", "phase3_review", "phase4_step1_price",
                "phase4_step2", "phase5_step1", "phase5_step2", "phase6_step1", "phase6_step3"):
        assert key in confirmed, key


def test_cost_report_covers_both_runs(tmp_path):
    weak = Harness(tmp_path, "weak")
    weak.run()
    strong = Harness(tmp_path, "strong")
    strong.run()
    report = json.loads((tmp_path / "outputs" / "cost_report.json").read_text(encoding="utf-8"))
    assert set(report["runs"]) == {"weak", "strong"}
    assert report["total_cost_usd"] == 0
    assert report["runs"]["weak"]["outcome"] == "stopped" and report["runs"]["strong"]["tokens"] > 0
    assert sum(e["cost"] for e in strong.logger.read()) == 0


# == refusals =================================================================
def test_a_refused_brief_never_reaches_the_model(tmp_path):
    h = Harness(tmp_path, "strong", idea="A crypto token project with a presale for my community members.")
    done = h.run()
    assert done.outcome == "refused" and "crypto" in done.summary.lower()
    assert h.model.calls == []
    assert "phase1_step1_strong-refusal.md" in h.files()
    assert any(e["action"] == "refuse_request" for e in h.log)


def test_an_out_of_scope_idea_found_at_intake_is_refused(tmp_path):
    h = Harness(tmp_path, "strong", overrides={
        "restate_idea": [variant("restate_idea", is_digital_product=False, excluded_category="physical goods")]})
    done = h.run()
    assert done.outcome == "refused" and "physical goods" in done.summary
    assert h.model.calls == ["restate_idea"]


# == founder decisions ========================================================
def test_a_missing_target_market_is_asked_for_and_checked(tmp_path):
    h = Harness(tmp_path, "strong", target_market=None)
    founder = Founder({"phase1_target_market": [Reply(None, "  "),
                                                Reply(None, "People who trade crypto tokens"),
                                                Reply(None, "Fresh graduates in Cairo")]})
    h.run(founder)
    assert len(founder.asked("phase1_target_market")) == 3
    assert h.brief.target_market == "Fresh graduates in Cairo"
    assert any(s.kind == "refusal" for s in founder.says)
    assert h.done.outcome == "completed"


def test_rejecting_a_step_with_changes_redoes_it_with_that_feedback(tmp_path):
    h = Harness(tmp_path, "strong")
    founder = Founder({"phase1_step1": [Reply(False, "Focus on data analyst roles only.")]})
    h.run(founder)
    assert h.model.calls.count("restate_idea") == 2
    assert "Focus on data analyst roles only." in h.model.prompts[1]
    assert "revise:phase1_step1" in h.actions()


def test_rule_breaking_feedback_is_refused_and_not_used(tmp_path):
    h = Harness(tmp_path, "strong")
    founder = Founder({"phase2_step2": [Reply(False, "Add a countdown timer to push people."), Reply(True)]})
    h.run(founder)
    assert h.model.calls.count("landing_page") == 1
    assert not any("countdown" in p for p in h.model.prompts)
    assert h.done.outcome == "completed"


def test_rejecting_with_no_text_stops_the_run(tmp_path):
    h = Harness(tmp_path, "strong")
    done = h.run(Founder({"phase1_step3": [Reply(False, "")]}))
    assert done.outcome == "stopped_by_founder" and "Target market fit" in done.summary
    assert not any(n.startswith("phase2") for n in h.files())


def test_endless_revisions_stop_the_run(tmp_path):
    h = Harness(tmp_path, "strong")
    done = h.run(Founder({"phase1_step1": [Reply(False, f"Change number {i} please.") for i in range(10)]}))
    assert done.outcome == "stopped_by_founder" and "revised 3 times" in done.summary
    assert h.model.calls.count("restate_idea") == 4


def test_a_handler_that_returns_nothing_is_treated_as_no(tmp_path):
    h = Harness(tmp_path, "strong")
    done = h.run(lambda event: None)
    assert done.outcome == "stopped_by_founder"
    assert h.model.calls == ["restate_idea"]


# == gates ====================================================================
def test_thin_evidence_pivots_then_stops_when_the_pivot_also_fails(tmp_path):
    h = Harness(tmp_path, "strong", n_sources=0)
    founder = Founder({"gate1_pivot": [Reply(True, "A bilingual cover letter template pack for graduates.")]})
    done = h.run(founder)
    assert h.model.calls.count("restate_idea") == 2                  # Phase 1 ran again after the pivot
    assert "pivot_back" in h.actions()
    assert h.brief.idea.startswith("A bilingual cover letter")
    assert done.outcome == "stopped" and done.last_gate == "G1"
    assert h.gates()[-1] == ("G1", "stop")
    assert "phase1_gate_strong-evidence-stop.md" in h.files()
    assert any(s.kind == "notice" and "sources/" in s.text for s in founder.says)


def test_declining_a_pivot_stops_at_once(tmp_path):
    h = Harness(tmp_path, "strong", n_sources=0)
    done = h.run(Founder({"gate1_pivot": [Reply(False, "")]}))
    assert done.outcome == "stopped" and h.model.calls.count("restate_idea") == 1
    assert [o for _, o in h.gates()] == ["pivot", "stop"]


def test_a_pivot_with_a_rule_breaking_idea_is_refused(tmp_path):
    h = Harness(tmp_path, "strong", n_sources=0)
    done = h.run(Founder({"gate1_pivot": [Reply(True, "An NFT marketplace for graduates and their CVs.")]}))
    assert done.outcome == "stopped" and "pivot_back" not in h.actions()


def test_founder_can_decline_even_when_demand_meets_the_target(tmp_path):
    h = Harness(tmp_path, "strong")
    done = h.run(Founder({"gate2_approval": [Reply(False, "")]}))
    assert done.outcome == "stopped" and done.last_gate == "G2"
    assert ("G2", "stop") in h.gates()


def test_failing_mvp_tests_repeat_with_the_failures_as_feedback(tmp_path):
    broken = variant("build_mvp")
    broken["items"][0]["content"] += " TODO add more"
    h = Harness(tmp_path, "strong", overrides={"build_mvp": [broken]})
    done = h.run()
    assert h.model.calls.count("build_mvp") == 2
    assert "Fix these failing MVP tests: no placeholder text" in h.model.prompts[h.model.calls.index("build_mvp", 
                                                                                 h.model.calls.index("build_mvp") + 1)]
    assert ("G3", "repeat") in h.gates() and done.outcome == "completed"


def test_mvp_tests_that_never_pass_stop_the_run(tmp_path):
    broken = variant("build_mvp")
    broken["items"][0]["content"] += " TODO add more"
    h = Harness(tmp_path, "strong", overrides={"build_mvp": [broken] * 5})
    done = h.run()
    assert done.outcome == "stopped" and done.last_gate == "G3"
    assert [o for g, o in h.gates() if g == "G3"] == ["repeat", "repeat", "repeat", "stop"]


def test_editing_gates_yaml_mid_run_ends_the_run(tmp_path):
    h = Harness(tmp_path, "strong")

    def tamper(request):
        if request.step_id.endswith("phase1_step3"):
            h.gates_path.write_text(h.gates_path.read_text().replace("signup_target: 100", "signup_target: 5"))
    done = h.run(Founder(on_request=tamper))
    assert done.outcome == "error" and "gates.yaml changed" in done.summary
    assert "run_error" in h.actions() and "end_run" in h.actions()


# == launch decisions =========================================================
def test_not_opening_the_store_means_nothing_is_delivered(tmp_path):
    h = Harness(tmp_path, "strong")
    done = h.run(Founder({"phase5_open_store": [Reply(False, "")]}))
    assert done.outcome == "stopped_by_founder"
    assert "deliver_product" not in h.actions() and "payment_test_log.md" not in h.files()


def test_rejected_posts_stay_drafts_and_the_run_continues(tmp_path):
    h = Harness(tmp_path, "strong")
    done = h.run(Founder({"phase5_publish_posts": [Reply(False, "Not yet.")]}))
    assert done.outcome == "completed"
    assert "publish_launch_posts_MOCKED" not in h.actions()


# == failures and replay ======================================================
def test_the_model_going_down_ends_the_run_cleanly(tmp_path):
    model = FakeModel()

    def flaky(url, payload, timeout):
        if len(model.calls) >= 3:
            raise ModelUnavailable("connection refused")
        return model(url, payload, timeout)
    h = Harness(tmp_path, "strong", transport=flaky)
    done = h.run()
    assert done.outcome == "error" and "Ollama) is not running" in done.summary and "docker compose up" in done.summary
    assert "model_error" in h.actions() and "end_run" in h.actions()
    assert "fallback_to_replay" not in h.actions()         # nothing recorded, so no pretend switch to replay
    assert json.loads((h.out / "cost_report.json").read_text())["runs"]["strong"]["outcome"] == "error"


def test_a_live_run_replays_exactly_without_the_model(tmp_path):
    Harness(tmp_path, "strong").run()
    replay = Harness(tmp_path, "strong", mode="replay")
    done = replay.run()
    assert done.outcome == "completed" and replay.model.calls == []
    memo = (replay.out / "phase6_step3_strong-memo.md").read_text(encoding="utf-8")
    assert "[REPLAY MODE]" in memo.splitlines()[0]
    assert "[REPLAY MODE]" in replay.founder.says[0].text


def test_done_lists_every_file_written(tmp_path):
    h = Harness(tmp_path, "strong")
    done = h.run()
    listed = {Path(f).name for f in done.files}
    on_disk = {n for n in h.files() if n.startswith("phase") or n == "payment_test_log.md"}
    assert on_disk <= listed


def test_phase_and_gate_events_carry_their_numbers(tmp_path):
    h = Harness(tmp_path, "strong")
    h.run()
    phases = [s.phase for s in h.founder.says if s.kind == "phase"]
    gates = [(s.phase, s.outcome) for s in h.founder.says if s.kind == "gate"]
    assert phases == [1, 2, 3, 4, 5, 6]
    assert [g[0] for g in gates] == [1, 2, 3, 4, 5, 6] and all(o == "go" for _, o in gates)
    assert h.founder.says[-1].kind == "done"


def test_the_founder_cannot_pivot_forever(tmp_path):
    h = Harness(tmp_path, "strong", n_sources=0)
    ideas = [Reply(True, f"A bilingual template pack for graduates, version {i}.") for i in range(5)]
    done = h.run(Founder({"gate1_pivot": ideas}))
    assert h.actions().count("pivot_back") == 1                        # max_pivots = 1
    assert h.model.calls.count("restate_idea") == 2
    assert done.outcome == "stopped" and done.last_gate == "G1"
