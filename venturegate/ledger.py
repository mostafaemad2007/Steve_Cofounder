"""The evidence ledger: every factual claim in one place a reviewer can check in a minute.

Each record is either SOURCED (a real URL from a page actually saved in sources/) or ASSUMPTION
(with a confidence level). There is no third option, and a claim can never carry an invented link:
the URL comes from the source library, not from the model.
"""
import json
from pathlib import Path

from . import config
from .logger import is_url, now_iso

CONFIDENCE = ("low", "medium", "high")


class LedgerError(ValueError):
    """Raised when a claim cannot be recorded as written."""


class EvidenceLedger:
    def __init__(self, path: Path | None = None, run: str | None = None):
        self.path = Path(path) if path else config.path("EVIDENCE_LEDGER", "outputs/evidence_ledger.json")
        self.run = run

    def for_run(self, run: str) -> "EvidenceLedger":
        return EvidenceLedger(self.path, run)

    def read(self) -> list:
        if not self.path.exists():
            return []
        text = self.path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else []

    def add_claim(self, claim: str, *, agent: str, source_url: str | None = None,
                  confidence: str = "medium", simulated: bool = False, step: str | None = None) -> dict:
        if not isinstance(claim, str) or not claim.strip():
            raise LedgerError("claim text is empty")
        if confidence not in CONFIDENCE:
            raise LedgerError(f"confidence must be one of {CONFIDENCE}")
        if source_url is not None and not is_url(source_url):
            raise LedgerError("source_url must be an http(s) URL; pass None to record an ASSUMPTION")

        record = {
            "timestamp": now_iso(),
            "run": self.run,
            "agent": agent,
            "step": step,
            "claim": " ".join(claim.split()),
            "source_url": source_url,
            "label": "SOURCED" if source_url else "ASSUMPTION",
            "confidence": confidence,
            "simulated": simulated,
        }
        records = self.read()
        records.append(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return record

    def records(self, run: str | None = None) -> list:
        run = run if run is not None else self.run
        return [r for r in self.read() if run is None or r.get("run") == run]

    def sourced_count(self, run: str | None = None) -> int:
        """Distinct sourced claims (same text and URL counted once), which is what Gate 1 measures."""
        return len({(r["claim"].lower(), r["source_url"]) for r in self.records(run) if r["source_url"]})

    def assumption_count(self, run: str | None = None) -> int:
        return sum(1 for r in self.records(run) if not r["source_url"])

    def reset_run(self, run: str) -> None:
        """Drop one run's claims (used when a run restarts after a pivot). Other runs are kept."""
        keep = [r for r in self.read() if r.get("run") != run]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(keep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
