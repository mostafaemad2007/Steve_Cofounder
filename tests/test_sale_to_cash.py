"""Part 6b: the MOCKED sale-to-cash flow.

Covers the four properties TEAM_CLAUDE.md names (payment triggers delivery, a refund revokes
access, idempotency, reconciliation) plus the two safety properties this project adds: nothing is
delivered before the founder opens the store, and a non-simulated event is refused outright.
"""
import pytest

from venturegate.approval import ApprovalRequired, Approvals
from venturegate.delivery import STORE_STEP_ID, AccessStore, DeliveryService, NotSimulated
from venturegate.gates import Gates
from venturegate.logger import DecisionLogger, validate_entry
from venturegate.mock_flow import run_mock_flow
from venturegate.reconcile import reconcile


@pytest.fixture
def setup(tmp_path):
    logger = DecisionLogger(tmp_path / "log.json")
    approvals = Approvals(tmp_path / "approvals.json", logger)
    store = AccessStore(tmp_path / "access.json")
    return logger, approvals, store, tmp_path


def open_store(approvals):
    approvals.request(STORE_STEP_ID, kind="publish", summary="Open the mocked store")
    approvals.approve(STORE_STEP_ID)


def paid(order="ord-9", key="key-9"):
    return {"event_id": "evt", "type": "order_paid", "order_id": order, "buyer_id": "buyer-X",
            "product_id": "prod-1", "idempotency_key": key, "simulated": True}


# == safety ===================================================================
def test_nothing_is_delivered_before_the_founder_opens_the_store(setup):
    logger, approvals, store, _ = setup
    with pytest.raises(ApprovalRequired):
        DeliveryService(store, approvals, logger).process_event(paid())
    assert store.read()["access"] == {}


def test_a_real_event_is_refused(setup):
    logger, approvals, store, _ = setup
    open_store(approvals)
    with pytest.raises(NotSimulated, match="outside this system"):
        DeliveryService(store, approvals, logger).process_event({**paid(), "simulated": False})


def test_the_store_approval_is_not_consumed_by_deliveries(setup):
    logger, approvals, store, _ = setup
    open_store(approvals)
    service = DeliveryService(store, approvals, logger)
    for i in range(3):
        service.process_event(paid(order=f"ord-{i}", key=f"key-{i}"))
    assert approvals.status(STORE_STEP_ID) == "approved"
    assert len(store.read()["access"]) == 3


# == the four required properties =============================================
def test_payment_triggers_delivery(setup):
    logger, approvals, store, _ = setup
    open_store(approvals)
    service = DeliveryService(store, approvals, logger)
    result = service.process_event(paid())
    assert result["status"] == "delivered" and result["licence"].startswith("LIC-")
    assert service.has_access("ord-9")


def test_a_repeated_event_does_not_deliver_twice(setup):
    logger, approvals, store, _ = setup
    open_store(approvals)
    service = DeliveryService(store, approvals, logger)
    assert service.process_event(paid())["status"] == "delivered"
    assert service.process_event(paid())["status"] == "duplicate_ignored"
    assert sum(e["action"] == "deliver_product" for e in logger.read()) == 1


def test_a_refund_revokes_access(setup):
    logger, approvals, store, _ = setup
    open_store(approvals)
    service = DeliveryService(store, approvals, logger)
    service.process_event(paid())
    service.process_event({**paid(), "type": "order_refunded", "idempotency_key": "refund-9"})
    assert not service.has_access("ord-9")
    assert any(e["action"] == "revoke_access" for e in logger.read())


def test_a_refund_for_an_unknown_order_is_reported_not_crashed(setup):
    logger, approvals, store, _ = setup
    open_store(approvals)
    service = DeliveryService(store, approvals, logger)
    result = service.process_event({**paid(order="ord-unknown"), "type": "order_refunded",
                                    "idempotency_key": "refund-unknown"})
    assert result["status"] == "unknown_order"


def test_reconciliation_catches_a_delivery_with_no_payment(setup):
    logger, _, _, _ = setup
    access = {"ord-99": {"status": "active", "buyer_id": "b", "product_id": "p", "simulated": True}}
    report = reconcile(access, logger=logger)
    assert not report["ok"]
    assert any("no payment record" in p for p in report["problems"])


def test_reconciliation_catches_a_refund_that_did_not_revoke(setup):
    logger, _, _, _ = setup
    access = {"ord-2": {"status": "active", "buyer_id": "b", "product_id": "p", "simulated": True}}
    report = reconcile(access, logger=logger)
    assert any("still active" in p for p in report["problems"])


def test_reconciliation_reports_no_money_amounts(setup):
    logger, approvals, store, tmp = setup
    open_store(approvals)
    result = run_mock_flow(approvals=approvals, store=store, logger=logger,
                           report_path=tmp / "payment_test_log.md")
    assert result["reconciliation"]["amounts"] == "STUBBED"


# == the whole flow ===========================================================
def test_the_full_flow_passes_and_writes_an_honest_report(setup):
    logger, approvals, store, tmp = setup
    open_store(approvals)
    report_path = tmp / "payment_test_log.md"

    result = run_mock_flow(approvals=approvals, store=store, logger=logger,
                           report_path=report_path, run="strong")

    assert result["delivered_on_payment"]
    assert result["refund_revoked_access"]
    assert result["idempotent"]
    assert result["reconciled"]
    assert result["simulated"]
    assert result["reconciliation"]["matched"] == ["ord-1", "ord-3"]
    assert result["reconciliation"]["refunded_and_revoked"] == ["ord-2"]

    text = report_path.read_text(encoding="utf-8")
    assert "MOCKED" in text and "[SIMULATED]" in text and "STUBBED" in text
    assert "$" not in text, "the payment log must contain no money amounts"
    assert "no payment provider, no sandbox" in text.lower()
    for entry in logger.read():
        validate_entry(entry)


def test_the_flow_result_opens_gate_five(setup):
    logger, approvals, store, tmp = setup
    open_store(approvals)
    result = run_mock_flow(approvals=approvals, store=store, logger=logger,
                           report_path=tmp / "payment_test_log.md")
    assert Gates(logger=logger).g5_launch(mock_flow=result).outcome == "go"


def test_running_the_flow_twice_gives_the_same_result(setup):
    logger, approvals, store, tmp = setup
    open_store(approvals)
    first = run_mock_flow(approvals=approvals, store=store, logger=logger,
                          report_path=tmp / "a.md")
    second = run_mock_flow(approvals=approvals, store=store, logger=logger,
                           report_path=tmp / "b.md")
    keys = ("delivered_on_payment", "refund_revoked_access", "idempotent", "reconciled")
    assert {k: first[k] for k in keys} == {k: second[k] for k in keys}


def test_the_flow_refuses_to_run_without_an_open_store(setup):
    logger, approvals, store, tmp = setup
    with pytest.raises(ApprovalRequired):
        run_mock_flow(approvals=approvals, store=store, logger=logger, report_path=tmp / "x.md")
