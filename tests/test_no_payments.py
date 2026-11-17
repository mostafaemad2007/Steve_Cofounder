"""No payment library may be imported or installed anywhere, not even a sandbox client.

TEAM_CLAUDE.md and the problem statement both forbid payments of any kind; this test makes that
mechanical rather than a promise.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIBS = r"(stripe|paypal\w*|braintree|squareup|adyen|razorpay|paddle|lemonsqueezy|mollie|checkout_sdk|payjs)"


def test_no_payment_library_is_imported():
    offenders = []
    for py in (ROOT / "venturegate").rglob("*.py"):
        for number, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(rf"\s*(import|from)\s+{LIBS}\b", line, re.I):
                offenders.append(f"{py.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, offenders


def test_no_payment_dependency_is_declared():
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert not re.search(rf"^\s*{LIBS}", reqs, re.M)


def test_no_payment_sdk_is_called_anywhere():
    offenders = []
    for py in (ROOT / "venturegate").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for match in re.finditer(rf"\b{LIBS}\s*\.\s*\w+\s*\(", text, re.I):
            offenders.append(f"{py.relative_to(ROOT)}: {match.group(0)}")
    assert not offenders, offenders
