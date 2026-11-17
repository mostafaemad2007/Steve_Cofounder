"""Refunds, MOCKED: a simulated refund event revokes the buyer's access.

This system never moves money. A real refund is made by the founder in their own payment provider;
all that happens here is that the licence stops working, which is the part a product owner has to
get right.
"""
from .logger import DecisionLogger, now_iso


def revoke(data: dict, event: dict, logger: DecisionLogger) -> dict:
    order_id = event["order_id"]
    item = data["access"].get(order_id)
    if item is None:
        logger.log("refunds", "refund_for_unknown_order", order_id=order_id, simulated=True)
        return {"status": "unknown_order", "order_id": order_id}
    item["status"] = "revoked"
    item["revoked_at"] = now_iso()
    logger.log("refunds", "revoke_access", order_id=order_id, simulated=True)
    return {"status": "revoked", "order_id": order_id}
