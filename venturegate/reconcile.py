"""Reconciliation, MOCKED: orders, payments, fees and payouts matched BY ID AND STATUS.

No money amounts are used. The project reports no income, revenue or profit figures anywhere, so
amount-level reconciliation (gross, fees, net payout) is deliberately STUBBED and would come from
the founder's own payment provider, outside this system. What is reconciled here is the part that
can go wrong in a digital product: a delivery with no payment behind it, a refund that did not
revoke access, or a payment nobody was delivered for.
"""
from . import mocks
from .logger import DecisionLogger


def reconcile(access: dict, records: dict | None = None,
              logger: DecisionLogger | None = None) -> dict:
    records = records or mocks.load("ledger_records")
    logger = logger or DecisionLogger()

    payments = {p["order_id"]: p for p in records["payments"]}
    fee_payment_ids = {f["payment_id"] for f in records["fees"]}
    paid_out_ids = {pid for payout in records["payouts"] for pid in payout["payment_ids"]}

    report = {"orders": len(access), "matched": [], "refunded_and_revoked": [], "problems": [],
              "simulated": True, "amounts": "STUBBED"}

    for order_id, item in sorted(access.items()):
        payment = payments.get(order_id)
        if payment is None:
            report["problems"].append(f"{order_id}: delivered but there is no payment record")
            continue
        if payment["payment_id"] not in fee_payment_ids:
            report["problems"].append(f"{order_id}: no fee record for {payment['payment_id']}")

        if payment["status"] == "refunded":
            if item["status"] == "revoked":
                report["refunded_and_revoked"].append(order_id)
            else:
                report["problems"].append(f"{order_id}: refunded but access is still active")
        elif payment["status"] == "succeeded":
            if payment["payment_id"] not in paid_out_ids:
                report["problems"].append(f"{order_id}: payment is not in any payout")
            elif item["status"] != "active":
                report["problems"].append(f"{order_id}: paid for but access is not active")
            else:
                report["matched"].append(order_id)

    for order_id in payments.keys() - access.keys():
        report["problems"].append(f"{order_id}: payment record with no delivery")

    report["ok"] = not report["problems"]
    logger.log("reconcile", "reconcile_orders", matched=len(report["matched"]),
               refunded=len(report["refunded_and_revoked"]),
               problems=len(report["problems"]), simulated=True)
    return report
