"""The gates: go / repeat / pivot / stop, decided by calculation from gates.yaml.

Three properties make a STOP from this file trustworthy:

1. **Pre-registered.** Thresholds are read from gates.yaml when the run starts.
2. **Locked.** The loaded values and the file on disk are fingerprinted; if either changes during a
   run, every later gate raises ThresholdLocked rather than returning a result nobody can trust.
3. **Calculated.** No gate asks the model what it thinks. Each one compares numbers, and the reasons
   it returns quote those numbers.

A gate recommends; the founder sees the recommendation and the evidence. A failed evidence gate can
never be turned into "go" — the founder may accept stop or pivot, or revise the idea and run again.
"""
import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import config
from .guard import Guard
from .logger import DecisionLogger

OUTCOMES = ("go", "repeat", "pivot", "stop")


class ThresholdLocked(RuntimeError):
    """Raised when gate thresholds change during a run."""


class UnlabelledData(ValueError):
    """Raised when a gate is handed demand data that is not marked as simulated."""


@dataclass
class GateDecision:
    gate: str
    outcome: str
    reasons: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.outcome == "go"

    def to_markdown(self, title: str) -> str:
        lines = [f"# {title}", "",
                 f"**Gate:** {self.gate}", f"**Outcome:** {self.outcome.upper()}", "",
                 "## Why", ""]
        lines += [f"- {reason}" for reason in self.reasons]
        lines += ["", "## Numbers the gate used", "", "| Measure | Value |", "|---|---|"]
        lines += [f"| {key} | {value} |" for key, value in self.metrics.items()]
        lines += ["", "These thresholds were fixed in `gates.yaml` before the run started and cannot be "
                  "changed during it.", ""]
        return "\n".join(lines)


class Gates:
    def __init__(self, path: Path | None = None, logger: DecisionLogger | None = None):
        self.path = Path(path) if path else config.ROOT / "gates.yaml"
        self._thresholds = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        self._fingerprint = self._digest(self._thresholds)
        self.logger = logger or DecisionLogger()
        self.attempts: dict[str, int] = {}

    # -- locking ----------------------------------------------------------
    @staticmethod
    def _digest(data) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    @property
    def thresholds(self) -> dict:
        """A copy: editing what you get back cannot change what the gates use."""
        return copy.deepcopy(self._thresholds)

    def set_threshold(self, *args, **kwargs):
        raise ThresholdLocked("Gate thresholds are pre-registered in gates.yaml and locked for this run.")

    def _verify_locked(self) -> None:
        on_disk = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        if self._digest(self._thresholds) != self._fingerprint or self._digest(on_disk) != self._fingerprint:
            raise ThresholdLocked(
                "gates.yaml changed during the run. Results are only trustworthy when the thresholds "
                "were fixed before the run, so this run cannot continue.")

    # -- helpers ----------------------------------------------------------
    def _decide(self, gate: str, outcome: str, reasons: list[str], metrics: dict) -> GateDecision:
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}")
        decision = GateDecision(gate, outcome, list(reasons), metrics)
        self.logger.log("gate", f"{gate}_decision", outcome=outcome,
                        reasons=decision.reasons[:6], metrics=metrics)
        return decision

    def _repeat_or_stop(self, gate: str, key: str, reasons: list[str], metrics: dict) -> GateDecision:
        """Repeat up to max_repeats, then stop rather than loop forever."""
        self.attempts[gate] = self.attempts.get(gate, 0) + 1
        max_repeats = self._thresholds[key].get("max_repeats", 3)
        metrics = {**metrics, "attempt": self.attempts[gate], "max_repeats": max_repeats}
        if self.attempts[gate] > max_repeats:
            return self._decide(gate, "stop", reasons + [f"Still failing after {max_repeats} attempts."], metrics)
        return self._decide(gate, "repeat", reasons, metrics)

    # == G1 Discover, early: the honest verdict ===========================
    def g1_verdict(self, *, verdict: str, reasons: list[str], alternatives: int,
                   sourced_claims: int) -> GateDecision | None:
        """A STOP as soon as the sourced Phase 1 verdict is one of the pre-registered stop verdicts.
        None means "no early stop": the full Gate 1 check still runs after step 6."""
        self._verify_locked()
        stop_verdicts = self._thresholds["G1_discover"].get("stop_verdicts", [])
        if verdict not in stop_verdicts:
            return None
        metrics = {"verdict from the evidence": verdict.replace("_", " ").upper(),
                   "verdicts that stop the run": ", ".join(v.replace("_", " ") for v in stop_verdicts),
                   "alternatives compared": alternatives, "claims with real sources so far": sourced_claims}
        return self._decide("G1", "stop", [
            f"The evidence gives this idea a {verdict.replace('_', ' ').upper()} verdict.", *reasons], metrics)

    # == G1 Discover: evidence threshold ==================================
    def g1_discover(self, *, alternatives: int, sourced_claims: int, runway_months: float,
                    hours_per_week: float, skills_blocking: bool = False) -> GateDecision:
        """Founder fit is calculated, not judged: budget covers the planning period, enough weekly
        hours, and no skill gap the analysis marked as blocking."""
        self._verify_locked()
        t = self._thresholds["G1_discover"]
        metrics = {
            "alternatives compared": alternatives, "minimum": t["min_alternatives"],
            "claims with real sources": sourced_claims, "minimum sourced": t["min_sourced_claims"],
            "months the budget covers": runway_months, "minimum months": t["min_runway_months"],
            "hours per week": hours_per_week, "minimum hours": t["min_hours_per_week"],
            "blocking skill gap": skills_blocking,
        }

        fit_problems = []
        if runway_months < t["min_runway_months"]:
            fit_problems.append(
                f"The budget covers {runway_months:g} months of costs, and the plan assumes "
                f"{t['min_runway_months']:g} months of little or no income (ASSUMPTION).")
        if hours_per_week < t["min_hours_per_week"]:
            fit_problems.append(f"{hours_per_week:g} hours per week are available, below the "
                                f"{t['min_hours_per_week']} this needs.")
        if skills_blocking:
            fit_problems.append("A skill gap blocks building this without outside help.")
        if t["require_founder_fit"] and fit_problems:
            return self._decide("G1", "stop",
                                ["The idea does not fit the founder's budget, time or skills."] + fit_problems,
                                metrics)

        evidence_problems = []
        if alternatives < t["min_alternatives"]:
            evidence_problems.append(f"Only {alternatives} alternatives were compared, below the "
                                     f"{t['min_alternatives']} required.")
        if sourced_claims < t["min_sourced_claims"]:
            evidence_problems.append(f"Only {sourced_claims} claims have a real source URL, below the "
                                     f"{t['min_sourced_claims']} required.")
        if evidence_problems:
            return self._decide("G1", "pivot", evidence_problems +
                                ["The evidence is too thin to continue as it stands."], metrics)
        return self._decide("G1", "go", [
            f"{alternatives} alternatives compared and {sourced_claims} claims carry real sources.",
            f"The budget covers {runway_months:g} months of costs at {hours_per_week:g} hours per week."], metrics)

    # == G2 Validate: demand ==============================================
    def g2_validate(self, *, signups: dict, founder_approved: bool) -> GateDecision:
        """signups is a mock record: {"count": int, "days": int, "simulated": true}."""
        self._verify_locked()
        if signups.get("simulated") is not True:
            raise UnlabelledData("Sign-up data must come from the mocks and be labelled simulated. "
                                 "The system never invents demand numbers.")
        t = self._thresholds["G2_validate"]
        count, target = signups["count"], t["signup_target"]
        ratio = round(count / target, 3) if target else 0.0
        metrics = {"sign-ups [SIMULATED]": count, "pre-set target": target,
                   "window (days)": t["window_days"], "share of target": f"{ratio:.0%}",
                   "stop below": f"{t['stop_below_ratio']:.0%}"}

        if count < target:
            if ratio < t["stop_below_ratio"]:
                return self._decide("G2", "stop", [
                    f"{count} of {target} sign-ups in {t['window_days']} days [SIMULATED] is "
                    f"{ratio:.0%} of the target that was set before the test.",
                    "The demand evidence is weak. The recommendation is STOP, stated plainly rather "
                    "than presented as an encouraging partial result."], metrics)
            return self._decide("G2", "pivot", [
                f"{count} of {target} sign-ups [SIMULATED] is {ratio:.0%} of target: below the bar, "
                "but not negligible.",
                "The recommendation is to pivot the segment or the offer and test again."], metrics)

        if t["require_founder_approval"] and not founder_approved:
            return self._decide("G2", "stop", [
                f"The target was met ({count} of {target} [SIMULATED]), but the founder did not "
                "approve continuing."], metrics)
        return self._decide("G2", "go", [
            f"{count} of {target} sign-ups in {t['window_days']} days [SIMULATED]: the pre-set "
            "target is met and the founder approved continuing."], metrics)

    # == G3 Build: tests ==================================================
    def g3_build(self, *, tests_passed: bool, user_docs_exist: bool) -> GateDecision:
        self._verify_locked()
        metrics = {"MVP tests pass": tests_passed, "user docs exist": user_docs_exist}
        problems = ([] if tests_passed else ["The MVP's automatic tests are failing."]) + \
                   ([] if user_docs_exist else ["The user documentation is missing."])
        if problems:
            return self._repeat_or_stop("G3", "G3_build", problems, metrics)
        return self._decide("G3", "go", ["Every MVP test passes and the user docs exist."], metrics)

    # == G4 Commercial setup: policies and price ==========================
    def g4_commercial(self, *, drafts: dict[str, str], price_approved: bool) -> GateDecision:
        self._verify_locked()
        t = self._thresholds["G4_commercial"]
        problems = []
        for name in t["required_drafts"]:
            text = drafts.get(name)
            if not text:
                problems.append(f"The {name} policy draft is missing.")
            elif t["draft_label"] not in text:
                problems.append(f"The {name} policy is not labelled '{t['draft_label']}'.")
        if t["require_price_approval"] and not price_approved:
            problems.append("The founder has not approved a price.")
        metrics = {"drafts present": ", ".join(sorted(drafts)) or "none", "price approved": price_approved}
        if problems:
            return self._repeat_or_stop("G4", "G4_commercial", problems, metrics)
        return self._decide("G4", "go", [
            f"Terms, privacy and refund drafts are all labelled '{t['draft_label']}' and the founder "
            "approved the price."], metrics)

    # == G5 Launch: the mocked sale-to-cash flow ==========================
    def g5_launch(self, *, mock_flow: dict) -> GateDecision:
        self._verify_locked()
        required = {
            "delivered_on_payment": "a simulated payment triggered delivery",
            "refund_revoked_access": "a simulated refund revoked access",
            "idempotent": "a repeated event delivered only once",
            "reconciled": "orders, payments, fees and payouts reconciled by ID",
            "simulated": "every event was labelled simulated",
        }
        checks = {key: mock_flow.get(key) is True for key in required}
        failed = [key for key, ok in checks.items() if not ok]
        if failed:
            return self._repeat_or_stop("G5", "G5_launch",
                                        [f"Check failed: {required[key]}." for key in failed], checks)
        return self._decide("G5", "go", ["The MOCKED sale-to-cash flow passed every check."], checks)

    # == G6 Operate: persevere, pivot or stop =============================
    def g6_outcome(self, *, signups: dict, runway_months: float) -> tuple[str, list[str], dict]:
        """The calculation on its own, so the memo can be written to explain a decision already made."""
        self._verify_locked()
        if signups.get("simulated") is not True:
            raise UnlabelledData("Demand signals must be labelled simulated.")
        t = self._thresholds["G6_operate"]
        target = self._thresholds["G2_validate"]["signup_target"]
        ratio = round(signups["count"] / target, 3) if target else 0.0
        metrics = {"demand vs target [SIMULATED]": f"{ratio:.0%}", "months the budget covers": runway_months,
                   "persevere at or above": f"{t['persevere_min_ratio']:.0%}",
                   "pivot at or above": f"{t['pivot_min_ratio']:.0%}",
                   "minimum months": t["min_runway_months"]}

        if runway_months < t["min_runway_months"]:
            return "stop", [f"The budget covers {runway_months:g} months of costs, below the "
                            f"{t['min_runway_months']} this plan assumes."], metrics
        if ratio >= t["persevere_min_ratio"]:
            return "go", [f"Persevere: demand signals are at {ratio:.0%} of target [SIMULATED] and the "
                          f"budget covers {runway_months:g} months of costs."], metrics
        if ratio >= t["pivot_min_ratio"]:
            return "pivot", [f"Pivot: demand is at {ratio:.0%} of target [SIMULATED], below the "
                             "persevere line but not negligible."], metrics
        return "stop", [f"Stop: demand at {ratio:.0%} of target [SIMULATED] is too weak to keep "
                        "spending time and money on."], metrics

    def g6_operate(self, *, memo: str, signups: dict, runway_months: float) -> GateDecision:
        t = self._thresholds["G6_operate"]
        outcome, reasons, metrics = self.g6_outcome(signups=signups, runway_months=runway_months)
        check = Guard(self.logger).post_check(memo, agent="operate")
        if t["forbid_income_figures"] and not check.allowed:
            return self._decide("G6", "repeat",
                                ["The memo was rejected by the guard: " + (check.reason or "")], metrics)
        return self._decide("G6", outcome, reasons, metrics)
