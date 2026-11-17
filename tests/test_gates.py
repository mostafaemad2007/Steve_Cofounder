"""Part 3: the gates decide by calculation, and the thresholds cannot move during a run."""
import shutil
from pathlib import Path

import pytest

from venturegate.gates import Gates, ThresholdLocked, UnlabelledData
from venturegate.logger import DecisionLogger, validate_entry

ROOT = Path(__file__).resolve().parent.parent
LABEL = "DRAFT - not legal advice"
FIT = {"runway_months": 8, "hours_per_week": 10}


@pytest.fixture
def gates(tmp_path):
    """A copy of the real gates.yaml, so a test can edit it without touching the repo's file."""
    shutil.copy(ROOT / "gates.yaml", tmp_path / "gates.yaml")
    return Gates(tmp_path / "gates.yaml", DecisionLogger(tmp_path / "log.json"))


# == G2: the headline STOP ====================================================
def test_twelve_of_a_hundred_signups_is_a_stop(gates):
    decision = gates.g2_validate(signups={"count": 12, "days": 14, "simulated": True}, founder_approved=True)
    assert decision.outcome == "stop"
    assert "12 of 100" in decision.reasons[0] and "[SIMULATED]" in decision.reasons[0]
    assert "12%" in decision.reasons[0]


def test_stop_report_names_the_numbers_and_does_not_soften(gates):
    decision = gates.g2_validate(signups={"count": 12, "days": 14, "simulated": True}, founder_approved=True)
    report = decision.to_markdown("Gate 2")
    assert "STOP" in report and "100" in report and "12" in report
    assert "fixed in `gates.yaml` before the run" in report


def test_a_gate_decision_is_logged_with_its_outcome(gates):
    gates.g2_validate(signups={"count": 12, "simulated": True}, founder_approved=True)
    entry = gates.logger.read()[-1]
    validate_entry(entry)
    assert entry["agent"] == "gate" and entry["outcome"] == "stop" and entry["model"] is None


@pytest.mark.parametrize("count, expected", [
    (12, "stop"), (49, "stop"), (50, "pivot"), (99, "pivot"), (100, "go"), (134, "go"),
])
def test_g2_outcome_follows_the_pre_set_thresholds(gates, count, expected):
    decision = gates.g2_validate(signups={"count": count, "simulated": True}, founder_approved=True)
    assert decision.outcome == expected


def test_meeting_the_target_still_needs_founder_approval(gates):
    decision = gates.g2_validate(signups={"count": 134, "simulated": True}, founder_approved=False)
    assert decision.outcome == "stop" and "did not approve" in decision.reasons[0]


def test_unlabelled_signup_data_is_refused(gates):
    with pytest.raises(UnlabelledData):
        gates.g2_validate(signups={"count": 500}, founder_approved=True)


# == G1: evidence and founder fit =============================================
def test_g1_passes_with_enough_evidence_and_fit(gates):
    assert gates.g1_discover(alternatives=3, sourced_claims=5, **FIT).outcome == "go"


@pytest.mark.parametrize("alternatives, claims", [(1, 5), (3, 2), (2, 4)])
def test_g1_pivots_when_the_evidence_is_thin(gates, alternatives, claims):
    decision = gates.g1_discover(alternatives=alternatives, sourced_claims=claims, **FIT)
    assert decision.outcome == "pivot"


def test_g1_stops_when_the_founder_does_not_fit(gates):
    short_budget = gates.g1_discover(alternatives=5, sourced_claims=9, runway_months=2, hours_per_week=10)
    assert short_budget.outcome == "stop" and "2 months" in " ".join(short_budget.reasons)

    no_time = gates.g1_discover(alternatives=5, sourced_claims=9, runway_months=12, hours_per_week=2)
    assert no_time.outcome == "stop" and "hours per week" in " ".join(no_time.reasons)

    blocked = gates.g1_discover(alternatives=5, sourced_claims=9, skills_blocking=True, **FIT)
    assert blocked.outcome == "stop" and "skill gap" in " ".join(blocked.reasons)


# == G3, G4, G5 ===============================================================
def test_g3_repeats_three_times_then_stops(gates):
    outcomes = [gates.g3_build(tests_passed=False, user_docs_exist=True).outcome for _ in range(4)]
    assert outcomes == ["repeat", "repeat", "repeat", "stop"]


def test_g3_passes_when_tests_and_docs_are_there(gates):
    assert gates.g3_build(tests_passed=True, user_docs_exist=True).outcome == "go"
    assert gates.g3_build(tests_passed=True, user_docs_exist=False).outcome == "repeat"


def test_g4_requires_labelled_drafts_and_an_approved_price(gates):
    good = {name: f"{name} policy text. {LABEL}" for name in ("terms", "privacy", "refund")}
    assert gates.g4_commercial(drafts=good, price_approved=True).outcome == "go"
    assert gates.g4_commercial(drafts={**good, "refund": "refund policy"}, price_approved=True).outcome == "repeat"
    assert gates.g4_commercial(drafts={k: v for k, v in good.items() if k != "privacy"},
                               price_approved=True).outcome == "repeat"
    assert gates.g4_commercial(drafts=good, price_approved=False).outcome == "repeat"


PASSING_FLOW = dict.fromkeys(["delivered_on_payment", "refund_revoked_access", "idempotent",
                              "reconciled", "simulated"], True)


def test_g5_passes_when_the_whole_mock_flow_works(gates):
    assert gates.g5_launch(mock_flow=PASSING_FLOW).outcome == "go"


@pytest.mark.parametrize("missing", list(PASSING_FLOW))
def test_g5_requires_every_sale_to_cash_check(gates, missing):
    """A fresh gate per case: the repeat counter is per run, not per check."""
    decision = gates.g5_launch(mock_flow={**PASSING_FLOW, missing: False})
    assert decision.outcome == "repeat", f"{missing} should be required"


def test_g5_repeats_three_times_then_stops(gates):
    broken = {**PASSING_FLOW, "idempotent": False}
    assert [gates.g5_launch(mock_flow=broken).outcome for _ in range(4)] == \
        ["repeat", "repeat", "repeat", "stop"]


# == G6 =======================================================================
def test_g6_persevere_pivot_and_stop(gates):
    memo = "Persevere: demand signals [SIMULATED] are above target and costs are covered."
    assert gates.g6_operate(memo=memo, signups={"count": 134, "simulated": True},
                            runway_months=8).outcome == "go"
    assert gates.g6_operate(memo=memo, signups={"count": 60, "simulated": True},
                            runway_months=8).outcome == "pivot"
    assert gates.g6_operate(memo=memo, signups={"count": 12, "simulated": True},
                            runway_months=8).outcome == "stop"
    assert gates.g6_operate(memo=memo, signups={"count": 134, "simulated": True},
                            runway_months=2).outcome == "stop"


def test_g6_sends_back_a_memo_that_mentions_income(gates):
    bad_memo = "We expect revenue of $2,000 per month once we launch."
    decision = gates.g6_operate(memo=bad_memo, signups={"count": 134, "simulated": True}, runway_months=8)
    assert decision.outcome == "repeat" and "guard" in decision.reasons[0]


def test_g6_outcome_matches_the_gate_it_feeds(gates):
    outcome, reasons, _ = gates.g6_outcome(signups={"count": 12, "simulated": True}, runway_months=8)
    assert outcome == "stop" and reasons
    decision = gates.g6_operate(memo="Stop: the demand signals are too weak.",
                                signups={"count": 12, "simulated": True}, runway_months=8)
    assert decision.outcome == outcome


# == locking ==================================================================
def test_thresholds_cannot_be_changed_through_the_api(gates):
    with pytest.raises(ThresholdLocked):
        gates.set_threshold("G2_validate", "signup_target", 10)


def test_editing_the_returned_thresholds_changes_nothing(gates):
    snapshot = gates.thresholds
    snapshot["G2_validate"]["signup_target"] = 10
    assert gates.g2_validate(signups={"count": 12, "simulated": True},
                             founder_approved=True).outcome == "stop"


def test_editing_gates_yaml_mid_run_is_detected(gates):
    gates.path.write_text(gates.path.read_text().replace("signup_target: 100", "signup_target: 10"),
                          encoding="utf-8")
    with pytest.raises(ThresholdLocked, match="changed during the run"):
        gates.g2_validate(signups={"count": 12, "simulated": True}, founder_approved=True)


def test_every_gate_checks_the_lock(gates):
    gates.path.write_text(gates.path.read_text().replace("min_alternatives: 3", "min_alternatives: 1"),
                          encoding="utf-8")
    checks = [
        lambda: gates.g1_discover(alternatives=1, sourced_claims=9, **FIT),
        lambda: gates.g2_validate(signups={"count": 12, "simulated": True}, founder_approved=True),
        lambda: gates.g3_build(tests_passed=True, user_docs_exist=True),
        lambda: gates.g4_commercial(drafts={}, price_approved=True),
        lambda: gates.g5_launch(mock_flow={}),
        lambda: gates.g6_outcome(signups={"count": 12, "simulated": True}, runway_months=8),
    ]
    for check in checks:
        with pytest.raises(ThresholdLocked):
            check()


def test_the_repo_gates_file_loads_and_covers_six_gates():
    real = Gates()
    assert len(real.thresholds) == 6
    assert real.thresholds["G2_validate"]["signup_target"] == 100
