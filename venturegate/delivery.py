"""Automatic delivery, MOCKED. No payment provider, no sandbox, no money.

A simulated `order_paid` event grants the buyer access to the digital product: a licence record in
a local JSON store. Three rules are enforced here:

  * nothing is delivered until the founder has approved opening the store;
  * only events labelled simulated are accepted, so a real payment event could not be processed
    even if one somehow arrived;
  * every event carries an idempotency key, processed once, so a retried event never delivers twice.

Refund events are handed to refunds.py, which revokes access.
"""
import hashlib
import json
from pathlib import Path

from . import config
from .approval import Approvals
from .logger import DecisionLogger, now_iso

#: Default id of the approval that must exist before anything is delivered.
STORE_STEP_ID = "phase5_open_store"


class NotSimulated(ValueError):
    """Raised when an event is not labelled as simulated."""


class AccessStore:
    """Who currently has access, plus the idempotency keys already processed."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config.path("STATE_DIR", ".state") / "access.json"

    def read(self) -> dict:
        if not self.path.exists():
            return {"access": {}, "processed": []}
        text = self.path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else {"access": {}, "processed": []}

    def write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")

    def reset(self) -> None:
        self.write({"access": {}, "processed": []})


class DeliveryService:
    def __init__(self, store: AccessStore, approvals: Approvals,
                 logger: DecisionLogger | None = None, store_step_id: str = STORE_STEP_ID):
        self.store = store
        self.approvals = approvals
        self.logger = logger or DecisionLogger()
        self.store_step_id = store_step_id

    def process_event(self, event: dict) -> dict:
        if event.get("simulated") is not True:
            raise NotSimulated("Only simulated events are accepted. Real payments are outside this "
                               "system: the founder connects a provider themselves, later.")
        # Checked without consuming: the store is opened once, then every delivery re-checks it.
        self.approvals.require_approval(self.store_step_id, consume=False)

        data = self.store.read()
        key = event["idempotency_key"]
        if key in data["processed"]:
            self.logger.log("delivery", "skip_duplicate_event", event_id=event["event_id"],
                            order_id=event["order_id"], simulated=True)
            return {"status": "duplicate_ignored", "order_id": event["order_id"]}

        if event["type"] == "order_paid":
            result = self._grant(data, event)
        elif event["type"] == "order_refunded":
            from .refunds import revoke
            result = revoke(data, event, self.logger)
        else:
            raise ValueError(f"unknown mock event type: {event['type']}")

        data["processed"].append(key)
        self.store.write(data)
        return result

    def _grant(self, data: dict, event: dict) -> dict:
        order_id = event["order_id"]
        licence = "LIC-" + hashlib.sha256(order_id.encode()).hexdigest()[:10].upper()
        data["access"][order_id] = {
            "buyer_id": event["buyer_id"], "product_id": event["product_id"], "licence": licence,
            "status": "active", "granted_at": now_iso(), "simulated": True,
        }
        self.logger.log("delivery", "deliver_product", order_id=order_id, licence=licence, simulated=True)
        return {"status": "delivered", "order_id": order_id, "licence": licence}

    def has_access(self, order_id: str) -> bool:
        item = self.store.read()["access"].get(order_id)
        return bool(item and item["status"] == "active")
