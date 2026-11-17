"""Part 1: decision_log.json and evidence_ledger.json."""
import json
from pathlib import Path

import pytest

from venturegate.ledger import EvidenceLedger, LedgerError
from venturegate.logger import DecisionLogger, LogSchemaError, validate_entry

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def log(tmp_path):
    return DecisionLogger(tmp_path / "decision_log.json")


@pytest.fixture
def ledger(tmp_path):
    return EvidenceLedger(tmp_path / "evidence_ledger.json")


# -- the committed log --------------------------------------------------------
def test_committed_decision_log_is_valid():
    entries = json.loads((ROOT / "decision_log.json").read_text(encoding="utf-8"))
    assert isinstance(entries, list)
    for entry in entries:
        validate_entry(entry)


# -- writing ------------------------------------------------------------------
def test_entry_has_all_seven_required_keys(log):
    log.log("discover", "find_opportunities", sources=["https://example.com/a"], model="qwen3:4b")
    entry = log.read()[0]
    for key in ("timestamp", "agent", "action", "sources", "model", "cost", "approved_by"):
        assert key in entry
    assert entry["cost"] == 0 and entry["approved_by"] is None


def test_steps_without_a_model_log_model_null(log):
    entry = log.log("gate", "G2_decision", outcome="stop")
    assert entry["model"] is None and entry["outcome"] == "stop"


def test_founder_approval_is_recorded(log):
    assert log.log("launch", "publish_posts", approved_by="founder")["approved_by"] == "founder"


def test_run_label_is_attached_to_every_entry(log):
    weak = log.for_run("weak")
    weak.log("discover", "a")
    weak.log("validate", "b")
    log.for_run("strong").log("discover", "c")
    assert len(weak.entries_for("weak")) == 2
    assert len(log.entries_for("strong")) == 1


def test_duplicate_sources_are_collapsed(log):
    entry = log.log("discover", "a", sources=["https://x.test/1", "https://x.test/1", "https://x.test/2"])
    assert entry["sources"] == ["https://x.test/1", "https://x.test/2"]


def test_total_cost_is_zero_for_local_models(log):
    log.log("discover", "a", model="qwen3:4b", cost=0)
    log.log("validate", "b", model="qwen3:4b", cost=0)
    assert log.total_cost() == 0


# -- rejecting ----------------------------------------------------------------
@pytest.mark.parametrize("bad, why", [
    ({"approved_by": "auto-safe"}, "approved_by must be founder or null"),
    ({"approved_by": "none"}, "the string 'none' is not null"),
    ({"approved_by": "system"}, "the system can never approve for the founder"),
    ({"sources": ["ASSUMPTION"]}, "assumptions belong in the ledger"),
    ({"sources": "https://example.com"}, "sources must be a list"),
    ({"sources": ["not a url"]}, "sources must be URLs"),
    ({"cost": -1}, "cost cannot be negative"),
    ({"cost": "0"}, "cost must be a number"),
    ({"cost": True}, "booleans are not costs"),
    ({"model": 4}, "model must be a string or null"),
    ({"model": ""}, "empty model string"),
    ({"outcome": "PIVOT_BACK"}, "outcome must be go/repeat/pivot/stop"),
    ({"timestamp": "yesterday"}, "timestamp must be ISO 8601"),
    ({"agent": ""}, "agent must be non-empty"),
])
def test_invalid_entries_are_rejected(bad, why):
    entry = {"timestamp": "2026-11-17T09:00:00Z", "agent": "discover", "action": "a",
             "sources": [], "model": None, "cost": 0, "approved_by": None}
    entry.update(bad)
    with pytest.raises(LogSchemaError):
        validate_entry(entry)


def test_missing_key_is_rejected():
    with pytest.raises(LogSchemaError, match="missing keys"):
        validate_entry({"timestamp": "2026-11-17T09:00:00Z", "agent": "a", "action": "b"})


def test_an_invalid_entry_never_reaches_the_file(log):
    with pytest.raises(LogSchemaError):
        log.log("discover", "a", approved_by="auto-safe")
    assert log.read() == []


# -- the evidence ledger ------------------------------------------------------
def test_sourced_and_assumption_claims(ledger):
    ledger.add_claim("Canva offers free CV templates", agent="discover",
                     source_url="https://www.canva.com/resumes/templates/", confidence="high")
    record = ledger.add_claim("Graduates prefer bilingual CVs", agent="discover", confidence="low")
    assert record["label"] == "ASSUMPTION" and record["source_url"] is None
    assert ledger.sourced_count() == 1 and ledger.assumption_count() == 1


def test_gate1_counts_distinct_sourced_claims_only(ledger):
    for _ in range(3):
        ledger.add_claim("Same claim", agent="discover", source_url="https://x.test/1")
    ledger.add_claim("Another claim", agent="discover", source_url="https://x.test/2")
    assert ledger.sourced_count() == 2


@pytest.mark.parametrize("kwargs", [
    {"claim": "", "agent": "discover"},
    {"claim": "   ", "agent": "discover"},
    {"claim": "x", "agent": "discover", "confidence": "certain"},
    {"claim": "x", "agent": "discover", "source_url": "made-up-source"},
    {"claim": "x", "agent": "discover", "source_url": "www.example.com"},
])
def test_bad_claims_are_rejected(ledger, kwargs):
    with pytest.raises(LedgerError):
        ledger.add_claim(**kwargs)


def test_resetting_one_run_keeps_the_other(ledger):
    ledger.for_run("weak").add_claim("weak claim", agent="discover", source_url="https://x.test/1")
    strong = ledger.for_run("strong")
    strong.add_claim("strong claim", agent="discover", source_url="https://x.test/2")
    strong.reset_run("weak")
    assert [r["run"] for r in strong.read()] == ["strong"]


def test_logging_works_when_the_log_file_cannot_be_replaced(tmp_path, monkeypatch):
    """Inside Docker, decision_log.json is a bind-mounted file: renaming over it fails with EBUSY."""
    import errno
    from pathlib import Path

    def busy(self, target):
        raise OSError(errno.EBUSY, "Device or resource busy")
    monkeypatch.setattr(Path, "replace", busy)
    log = DecisionLogger(tmp_path / "decision_log.json")
    log.log("guard", "refuse_request")
    log.log("gate", "G2_decision", outcome="stop")
    assert [e["action"] for e in log.read()] == ["refuse_request", "G2_decision"]
    assert not (tmp_path / "decision_log.tmp").exists()
