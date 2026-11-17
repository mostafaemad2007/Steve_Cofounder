"""Plain arithmetic on the founder's own numbers. Costs only.

Nothing here computes, predicts or estimates income, revenue or profit. The break-even figure is a
condition ("you would need at least N paying customers a month just to cover costs"), not a forecast
that anyone will buy.
"""
import math

RUNWAY_CAP = 120.0   # months; keeps the number finite (and valid JSON) when there are no recurring costs


def clean(value) -> float:
    """A cost as a non-negative float. Junk and negatives count as 0 instead of reducing the total."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number or number in (float("inf"), float("-inf")):
        return 0.0
    return max(number, 0.0)


def total(items: list[dict]) -> float:
    return round(sum(clean(item.get("cost")) for item in items or []), 2)


def runway_months(budget: float, one_off: float, monthly: float) -> float:
    """Months of recurring costs the budget covers after paying the one-off costs."""
    left = clean(budget) - clean(one_off)
    if left <= 0:
        return 0.0
    if clean(monthly) == 0:
        return RUNWAY_CAP
    return min(math.floor(left / clean(monthly) * 10) / 10, RUNWAY_CAP)   # round DOWN: never overstate


def needed_for(months: float, one_off: float, monthly: float) -> float:
    return round(clean(one_off) + clean(monthly) * clean(months), 2)


def break_even_customers(monthly_costs: float, price: float) -> int | None:
    """ceil(C / P): paying customers per month needed just to cover monthly costs.
    Provider fees and taxes are ignored (stated as an ASSUMPTION wherever this is shown)."""
    price, monthly_costs = clean(price), clean(monthly_costs)
    if price == 0:
        return None
    if monthly_costs == 0:
        return 0
    return math.ceil(round(monthly_costs / price, 9))     # 0.3 / 0.1 must give 3, not 4


def fmt_money(value: float, currency: str) -> str:
    value = clean(value)
    text = f"{value:,.2f}"
    if text.endswith(".00"):
        text = text[:-3]
    return f"{text} {currency}"


def fmt_months(months: float) -> str:
    if months >= RUNWAY_CAP:
        return f"{RUNWAY_CAP:g}+ months (no recurring costs)"
    return f"{months:g} month" + ("" if months == 1 else "s")
