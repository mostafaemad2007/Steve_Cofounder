"""The decision log: one entry per agent action, appended by code, written to decision_log.json.

Required keys on every entry, exactly as TEAM_CLAUDE.md specifies:
    timestamp, agent, action, sources, model, cost, approved_by

Extra keys are allowed and used (run, outcome, simulated, mode, tokens, ...).
The schema is enforced *before* anything is written, so an invalid entry can never reach the file:
a log a reviewer cannot trust is worse than no log.
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config

REQUIRED_KEYS = ("timestamp", "agent", "action", "sources", "model", "cost", "approved_by")
ALLOWED_APPROVERS = ("founder", None)
GATE_OUTCOMES = ("go", "repeat", "pivot", "stop")

_lock = threading.Lock()


class LogSchemaError(ValueError):
    """Raised when an entry does not match the required schema."""


def is_url(value) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://")) and " " not in value


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_entry(entry: dict) -> None:
    if not isinstance(entry, dict):
        raise LogSchemaError("entry must be an object")
    missing = [k for k in REQUIRED_KEYS if k not in entry]
    if missing:
        raise LogSchemaError(f"missing keys: {missing}")

    timestamp = entry["timestamp"]
    if not isinstance(timestamp, str):
        raise LogSchemaError("timestamp must be an ISO 8601 string")
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LogSchemaError(f"bad timestamp: {timestamp}") from exc

    for key in ("agent", "action"):
        if not isinstance(entry[key], str) or not entry[key].strip():
            raise LogSchemaError(f"{key} must be a non-empty string")

    sources = entry["sources"]
    if not isinstance(sources, list) or not all(is_url(s) for s in sources):
        raise LogSchemaError("sources must be a list of http(s) URLs "
                             "(ASSUMPTIONs belong in evidence_ledger.json, not here)")

    model = entry["model"]
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise LogSchemaError("model must be a non-empty string, or null for steps without a model")

    cost = entry["cost"]
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
        raise LogSchemaError("cost must be a non-negative number in USD")

    if entry["approved_by"] not in ALLOWED_APPROVERS:
        raise LogSchemaError('approved_by must be "founder" or null, with no other values')

    if "outcome" in entry and entry["outcome"] not in GATE_OUTCOMES:
        raise LogSchemaError(f"outcome must be one of {GATE_OUTCOMES}")


class DecisionLogger:
    """Appends entries to decision_log.json. `run` labels entries from one example run."""

    def __init__(self, path: Path | None = None, run: str | None = None):
        self.path = Path(path) if path else config.path("DECISION_LOG", "decision_log.json")
        self.run = run

    def for_run(self, run: str) -> "DecisionLogger":
        return DecisionLogger(self.path, run)

    def read(self) -> list:
        if not self.path.exists():
            return []
        text = self.path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else []

    def log(self, agent: str, action: str, *, sources=None, model=None, cost=0,
            approved_by=None, **extra) -> dict:
        entry = {
            "timestamp": now_iso(),
            "agent": agent,
            "action": action,
            "sources": list(dict.fromkeys(sources or [])),
            "model": model,
            "cost": cost,
            "approved_by": approved_by,
        }
        if self.run and "run" not in extra:
            entry["run"] = self.run
        entry.update({k: v for k, v in extra.items() if v is not None})
        validate_entry(entry)
        with _lock:
            entries = self.read()
            entries.append(entry)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(entries, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.replace(self.path)
        return entry

    def entries_for(self, run: str) -> list:
        return [e for e in self.read() if e.get("run") == run]

    def total_cost(self) -> float:
        return round(sum(float(e["cost"]) for e in self.read()), 6)

    def reset(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("[]\n", encoding="utf-8")
