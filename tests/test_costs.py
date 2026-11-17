"""Part 7c: cost arithmetic. Costs only; no income is ever computed."""
import json

import pytest

from venturegate import costs


def test_totals_ignore_junk_and_negatives():
    items = [{"cost": 5}, {"cost": "12.5"}, {"cost": -10}, {"cost": None}, {"cost": "abc"}, {}]
    assert costs.total(items) == 17.5
    assert costs.total([]) == 0 and costs.total(None) == 0


@pytest.mark.parametrize("budget, one_off, monthly, expected", [
    (300, 12, 15, 19.2),
    (100, 0, 30, 3.3),          # rounded DOWN: 3.33 -> 3.3, never overstated
    (100, 0, 3, 33.3),
    (50, 60, 5, 0.0),           # one-off costs eat the whole budget
    (0, 0, 10, 0.0),
    (300, 12, 0, costs.RUNWAY_CAP),
])
def test_runway(budget, one_off, monthly, expected):
    assert costs.runway_months(budget, one_off, monthly) == expected


def test_runway_is_always_valid_json():
    json.dumps({"runway": costs.runway_months(1000, 0, 0)}, allow_nan=False)


@pytest.mark.parametrize("monthly, price, expected", [
    (50, 10, 5), (51, 10, 6), (0.3, 0.1, 3), (15, 9, 2), (0, 9, 0), (15, 0, None), (15, -3, None),
])
def test_break_even_is_ceil_of_costs_over_price(monthly, price, expected):
    assert costs.break_even_customers(monthly, price) == expected


def test_needed_for_a_planning_period():
    assert costs.needed_for(6, 12, 15) == 102


@pytest.mark.parametrize("value, currency, expected", [
    (15, "USD", "15 USD"), (12.5, "EGP", "12.50 EGP"), (1500, "USD", "1,500 USD"), (-3, "USD", "0 USD"),
])
def test_money_format(value, currency, expected):
    assert costs.fmt_money(value, currency) == expected


def test_month_format():
    assert costs.fmt_months(1) == "1 month"
    assert costs.fmt_months(19.2) == "19.2 months"
    assert "no recurring costs" in costs.fmt_months(costs.RUNWAY_CAP)


def test_the_module_has_no_income_functions():
    names = [n for n in dir(costs) if not n.startswith("_")]
    assert not [n for n in names if any(w in n.lower() for w in ("income", "revenue", "profit", "earn"))]
