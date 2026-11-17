"""Runs the red-team prompts through the guard and writes outputs/redteam_report.md.

The prompts live in tests/redteam/prompts.yaml, as TEAM_CLAUDE.md asks; the same file drives the
test suite, so the report and the tests can never disagree about what was tried.
"""
from pathlib import Path

import yaml

from . import config
from .guard import Guard
from .logger import DecisionLogger, now_iso

PROMPTS = config.ROOT / "tests" / "redteam" / "prompts.yaml"


def run_redteam(logger: DecisionLogger | None = None, prompts_path: Path | None = None,
                report_path: Path | None = None) -> dict:
    logger = (logger or DecisionLogger()).for_run("redteam")
    cases = yaml.safe_load(Path(prompts_path or PROMPTS).read_text(encoding="utf-8"))
    guard = Guard(logger)
    rows = []
    for case in cases:
        result = guard.pre_check(case["prompt"], agent="redteam")
        rows.append({"id": case["id"], "prompt": case["prompt"], "expected": case["expect"],
                     "refused": not result.allowed, "category": result.category, "reason": result.reason,
                     "as_expected": (not result.allowed) and result.category == case["expect"]})
    refused = sum(r["refused"] for r in rows)
    lines = ["# Red-team report", "",
             f"Run at {now_iso()} against the deterministic guard (no model involved). Each trick prompt "
             "is sent as a founder request; a refusal is logged to `decision_log.json`.", "",
             f"**{refused} of {len(rows)} refused**, "
             f"{sum(r['as_expected'] for r in rows)} in the expected category.", "",
             "| # | Trick prompt | Refused | Category | Reason given to the founder |", "|---|---|---|---|---|"]
    for r in rows:
        prompt = r["prompt"].replace("|", "/")
        reason = (r["reason"] or "-").replace("|", "/")
        lines.append(f"| {r['id']} | {prompt} | {'yes' if r['refused'] else '**NO**'} | "
                     f"{r['category'] or '-'} | {reason} |")
    path = Path(report_path) if report_path else config.path("OUTPUT_DIR", "outputs") / "redteam_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"total": len(rows), "refused": refused, "rows": rows, "report": str(path)}
