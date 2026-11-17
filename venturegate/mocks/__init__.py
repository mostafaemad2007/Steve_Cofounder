"""The only source of simulated data in VentureGate.

Every number the system shows that is not calculated from the founder's own figures comes from a
file in this folder. Nothing is generated on the fly, so a reviewer can read the fixtures and see
exactly what was simulated.

Two rules are enforced by the loader rather than by discipline:
  * every record carries "simulated": true, or loading fails;
  * no record may contain a money field, because the project reports no income, revenue or profit
    figures anywhere, not even simulated ones.
"""
import json
from pathlib import Path

MOCK_DIR = Path(__file__).resolve().parent

#: Keys that would introduce a money amount into a simulated record.
FORBIDDEN_KEYS = {"amount", "price", "revenue", "income", "profit", "total", "net", "gross",
                  "earnings", "sales", "payout_amount", "fee_amount", "mrr", "arr"}


class MockError(ValueError):
    """Raised when a fixture is unlabelled or contains a money amount."""


def _check(node, where: str) -> None:
    if isinstance(node, dict):
        bad = FORBIDDEN_KEYS & {key.lower() for key in node}
        if bad:
            raise MockError(f"{where}: money fields are not allowed in mocks: {sorted(bad)}")
        for key, value in node.items():
            _check(value, f"{where}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            if isinstance(item, dict) and item.get("simulated") is not True:
                raise MockError(f'{where}[{index}] is not labelled "simulated": true')
            _check(item, f"{where}[{index}]")


def load(name: str) -> dict:
    path = MOCK_DIR / f"{name}.json"
    if not path.exists():
        raise MockError(f"no fixture named '{name}'")
    data = json.loads(path.read_text(encoding="utf-8"))
    _check(data, name)
    return data


def all_mock_names() -> list[str]:
    return sorted(p.stem for p in MOCK_DIR.glob("*.json"))


def _by_scenario(name: str, scenario: str) -> dict:
    for record in load(name)["records"]:
        if record["scenario"] == scenario:
            return dict(record)
    raise MockError(f"no '{scenario}' fixture in {name}.json")


def signups(scenario: str) -> dict:
    """Waitlist sign-ups for a prepared scenario ("weak" or "strong"). [SIMULATED]"""
    return _by_scenario("signups", scenario)


def audience_preference(scenario: str) -> dict:
    """Share of a hypothetical audience preferring the product. [SIMULATED]"""
    return _by_scenario("audience_preference", scenario)


def sale_events() -> list[dict]:
    """Mock store events for the sale-to-cash demonstration. [SIMULATED]"""
    return [dict(record) for record in load("sale_events")["records"]]


def support_tickets() -> list[dict]:
    """Mock support tickets for Phase 6. [SIMULATED]"""
    return [dict(record) for record in load("support_tickets")["records"]]
