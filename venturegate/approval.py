"""Founder approval, enforced in code rather than by convention.

Any action that publishes, sends or spends must go through require_approval() or run_approved().
Without a recorded founder approval they raise ApprovalRequired, so a missing approval stops the
run instead of quietly letting something out. There is deliberately no auto-approve path, no
"approve all", and no way for an agent to approve on the founder's behalf.

Approvals are single use: approving one launch post does not approve the next one.
"""
import json
from pathlib import Path
from typing import Callable

from . import config
from .logger import DecisionLogger, now_iso

KINDS = ("publish", "send", "spend", "gate", "confirm")
PENDING, APPROVED, REJECTED, USED = "pending", "approved", "rejected", "used"


class ApprovalRequired(PermissionError):
    """Raised when an action runs without the founder's approval."""


class ApprovalRejected(PermissionError):
    """Raised when the founder has explicitly rejected the action."""


class Approvals:
    def __init__(self, path: Path | None = None, logger: DecisionLogger | None = None):
        self.path = Path(path) if path else config.path("STATE_DIR", ".state") / "approvals.json"
        self.logger = logger or DecisionLogger()

    # -- storage ----------------------------------------------------------
    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        text = self.path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")

    # -- requesting -------------------------------------------------------
    def request(self, step_id: str, *, kind: str, summary: str, agent: str = "orchestrator") -> dict:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if not step_id or not str(step_id).strip():
            raise ValueError("step_id is required")
        data = self._read()
        item = {"step_id": step_id, "kind": kind, "summary": summary[:300], "status": PENDING,
                "requested_at": now_iso(), "agent": agent}
        data[step_id] = item
        self._write(data)
        self.logger.log(agent, f"request_approval:{step_id}", kind=kind)
        return item

    def get(self, step_id: str) -> dict | None:
        return self._read().get(step_id)

    def status(self, step_id: str) -> str | None:
        item = self.get(step_id)
        return item["status"] if item else None

    def pending(self) -> list[dict]:
        return [item for item in self._read().values() if item["status"] == PENDING]

    def clear(self, prefix: str) -> None:
        """Forget earlier requests at the start of a run. Never approves anything; a non-empty
        prefix is required so this cannot wipe unrelated state."""
        if not prefix:
            raise ValueError("clear() needs a prefix, to avoid wiping unrelated approvals")
        self._write({k: v for k, v in self._read().items() if not k.startswith(prefix)})

    # -- the founder's decision (only ever called from the UI or the CLI) --
    def approve(self, step_id: str) -> dict:
        return self._decide(step_id, APPROVED)

    def reject(self, step_id: str, reason: str = "") -> dict:
        return self._decide(step_id, REJECTED, reason)

    def _decide(self, step_id: str, status: str, reason: str = "") -> dict:
        data = self._read()
        if step_id not in data:
            raise KeyError(f"There is no approval request named '{step_id}'.")
        data[step_id].update(status=status, decided_at=now_iso(), reason=reason[:300])
        self._write(data)
        self.logger.log("founder", f"{'approve' if status == APPROVED else 'reject'}:{step_id}",
                        approved_by="founder" if status == APPROVED else None,
                        reason=reason[:200] or None)
        return data[step_id]

    # -- enforcement ------------------------------------------------------
    def require_approval(self, step_id: str, *, consume: bool = True) -> None:
        """Raise unless the founder approved this exact step. `consume` makes it single use."""
        data = self._read()
        item = data.get(step_id)
        if item is None:
            raise ApprovalRequired(f"'{step_id}' was never put to the founder, so it cannot run.")
        if item["status"] == PENDING:
            raise ApprovalRequired(f"'{step_id}' is still waiting for the founder's approval.")
        if item["status"] == USED:
            raise ApprovalRequired(f"The approval for '{step_id}' was already used; approving once "
                                   "does not approve again.")
        if item["status"] == REJECTED:
            raise ApprovalRejected(f"The founder rejected '{step_id}'. {item.get('reason', '')}".strip())
        if consume:
            item.update(status=USED, used_at=now_iso())
            self._write(data)

    def run_approved(self, step_id: str, action: Callable[[], object], *, agent: str,
                     action_name: str, sources=None):
        """Run a publish / send / spend action, but only after the founder approved it."""
        self.require_approval(step_id)
        result = action()
        self.logger.log(agent, action_name, sources=sources or [], approved_by="founder", step_id=step_id)
        return result
