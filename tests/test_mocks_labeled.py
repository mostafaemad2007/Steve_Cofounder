"""Part 6a: every simulated record is labelled, and no fixture smuggles in a money amount."""
import pytest

from venturegate import mocks


def test_the_expected_fixtures_exist():
    assert {"signups", "audience_preference", "support_tickets", "sale_events",
            "ledger_records"} <= set(mocks.all_mock_names())


@pytest.mark.parametrize("name", mocks.all_mock_names())
def test_every_fixture_is_labelled_and_money_free(name):
    data = mocks.load(name)                      # raises MockError if unlabelled or has amounts
    assert "[SIMULATED]" in data["_note"], "each fixture must say plainly that it is simulated"
    assert "FIXTURE" in data["_note"]


def test_the_loader_rejects_an_unlabelled_record():
    with pytest.raises(mocks.MockError, match="simulated"):
        mocks._check({"records": [{"count": 5}]}, "x")


@pytest.mark.parametrize("field", ["amount", "revenue", "price", "profit", "mrr"])
def test_the_loader_rejects_money_fields(field):
    with pytest.raises(mocks.MockError, match="money fields"):
        mocks._check({"records": [{field: 10, "simulated": True}]}, "x")


def test_an_unknown_fixture_is_an_error():
    with pytest.raises(mocks.MockError):
        mocks.load("imaginary")


def test_the_weak_and_strong_scenarios_match_the_documented_demo():
    assert mocks.signups("weak")["count"] == 12
    assert mocks.signups("weak")["days"] == 14
    assert mocks.signups("strong")["count"] >= 100
    assert mocks.audience_preference("weak")["prefer_pct"] < \
        mocks.audience_preference("strong")["prefer_pct"]


def test_an_unknown_scenario_is_an_error():
    with pytest.raises(mocks.MockError, match="no 'medium' fixture"):
        mocks.signups("medium")


def test_sale_events_include_a_deliberate_retry_and_a_refund():
    events = mocks.sale_events()
    keys = [e["idempotency_key"] for e in events]
    assert len(keys) != len(set(keys)), "a repeated event is needed to prove idempotency"
    assert any(e["type"] == "order_refunded" for e in events)
    assert all(e["simulated"] is True for e in events)


def test_fixtures_are_copies_so_a_caller_cannot_corrupt_them():
    events = mocks.sale_events()
    events[0]["order_id"] = "tampered"
    assert mocks.sale_events()[0]["order_id"] != "tampered"
