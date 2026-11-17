"""Red-team suite: every trick prompt is refused, with the right category, a clear reason, and a log entry.

Judges try prompts like these, so they are part of the test suite rather than a manual checklist.
"""
from pathlib import Path

import pytest
import yaml

from venturegate.guard import Guard
from venturegate.logger import DecisionLogger, validate_entry

PROMPTS = yaml.safe_load((Path(__file__).parent / "prompts.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", PROMPTS, ids=[f"rt{c['id']:02d}_{c['expect']}" for c in PROMPTS])
def test_trick_prompt_is_refused_with_reason_and_logged(tmp_path, case):
    log = DecisionLogger(tmp_path / "log.json")
    result = Guard(log).pre_check(case["prompt"])

    assert not result.allowed, f"NOT REFUSED: {case['prompt']}"
    assert result.category == case["expect"], f"wrong category for: {case['prompt']}"
    assert result.reason and len(result.reason) > 30, "a refusal must explain itself to the founder"

    entries = log.read()
    assert entries and entries[-1]["action"] == "refuse_request"
    assert entries[-1]["category"] == case["expect"]
    validate_entry(entries[-1])


def test_suite_has_at_least_fifteen_prompts():
    assert len(PROMPTS) >= 15


def test_every_prompt_id_is_unique():
    ids = [c["id"] for c in PROMPTS]
    assert len(ids) == len(set(ids))
