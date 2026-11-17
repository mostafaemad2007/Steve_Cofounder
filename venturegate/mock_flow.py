"""Runs the whole MOCKED sale-to-cash flow and writes outputs/payment_test_log.md.

This is what Gate 5 checks and what `python -m venturegate mockflow` runs. It demonstrates the
four properties TEAM_CLAUDE.md asks for, in one pass over the simulated events:

    payment triggers delivery -> refund revokes access -> a retry delivers once -> reconciliation
"""
from pathlib import Path

from . import config, mocks
from .approval import Approvals
from .delivery import STORE_STEP_ID, AccessStore, DeliveryService
from .logger import DecisionLogger, now_iso
from .reconcile import reconcile


def run_mock_flow(*, approvals: Approvals, store: AccessStore, logger: DecisionLogger,
                  report_path: Path | None = None, store_step_id: str = STORE_STEP_ID,
                  run: str | None = None) -> dict:
    store.reset()                                    # a flow run always starts from nothing
    service = DeliveryService(store, approvals, logger, store_step_id)

    events = mocks.sale_events()
    steps = [(e["event_id"], e["type"], service.process_event(e)["status"]) for e in events]

    access = store.read()["access"]
    reconciliation = reconcile(access, logger=logger)

    first_paid = next(e for e in events if e["type"] == "order_paid")
    refunded_orders = [e["order_id"] for e in events if e["type"] == "order_refunded"]
    keys = [e["idempotency_key"] for e in events]
    repeated = [k for k in set(keys) if keys.count(k) > 1]
    deliveries = sum(status == "delivered" for _, _, status in steps)
    paid_orders = {e["order_id"] for e in events if e["type"] == "order_paid"}

    result = {
        "delivered_on_payment": service.has_access(first_paid["order_id"]),
        "refund_revoked_access": all(not service.has_access(o) for o in refunded_orders),
        # The fixtures repeat one event on purpose; it must not produce an extra delivery.
        "idempotent": bool(repeated) and deliveries == len(paid_orders),
        "reconciled": reconciliation["ok"],
        "simulated": all(e["simulated"] is True for e in events),
        "steps": steps,
        "reconciliation": reconciliation,
        "store_step_id": store_step_id,
        "run": run,
    }

    path = Path(report_path) if report_path else config.path("OUTPUT_DIR", "outputs") / "payment_test_log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_markdown(result), encoding="utf-8")
    result["report_path"] = str(path)
    logger.log("launch", "run_mock_sale_to_cash", simulated=True,
               passed=all(result[k] for k in ("delivered_on_payment", "refund_revoked_access",
                                              "idempotent", "reconciled", "simulated")))
    return result


def _markdown(result: dict) -> str:
    rec = result["reconciliation"]
    verdict = lambda ok: "PASS" if ok else "FAIL"          # noqa: E731
    lines = [
        "# Payment and delivery test log (MOCKED)", "",
        "> **MOCKED / [SIMULATED].** There is no payment provider, no sandbox and no test mode in "
        "this project. No money is held, moved, charged or refunded, and no amounts appear "
        "anywhere below. The events are fixtures with fake IDs from `venturegate/mocks/`.", "",
        f"Run: {result.get('run') or 'standalone'}. Delivery required the founder's approval of "
        f"`{result['store_step_id']}` before any event was processed. Executed at {now_iso()}.", "",
        "## Events processed", "", "| Event | Type | Result |", "|---|---|---|",
    ]
    lines += [f"| {event} | {kind} | {status} |" for event, kind, status in result["steps"]]
    lines += [
        "", "## Checks", "",
        f"- Payment triggers delivery: **{verdict(result['delivered_on_payment'])}**",
        f"- Refund revokes access: **{verdict(result['refund_revoked_access'])}**",
        f"- Idempotency, a repeated event delivers once: **{verdict(result['idempotent'])}**",
        f"- Reconciliation by ID and status: **{verdict(result['reconciled'])}**",
        f"- Every event labelled simulated: **{verdict(result['simulated'])}**", "",
        "## Reconciliation", "",
        f"- Orders delivered: {rec['orders']}",
        f"- Matched to a payment, a fee and a payout: {', '.join(rec['matched']) or 'none'}",
        f"- Refunded and access revoked: {', '.join(rec['refunded_and_revoked']) or 'none'}",
        f"- Problems: {'; '.join(rec['problems']) or 'none'}", "",
        "Amount-level reconciliation (gross, fees, net payout) is **STUBBED**: this system reports "
        "no money figures at all, so those would come from the founder's own payment provider, "
        "outside VentureGate.", "",
    ]
    return "\n".join(lines)
