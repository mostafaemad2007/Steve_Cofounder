"""Phase 6 Operate and learn.

Steps
  1 support   reply drafts for the [SIMULATED] tickets. Sending needs approval and is MOCKED.
  2 metrics   no model: [SIMULATED] demand and support signals plus the founder's cost data
  3 memo      persevere, pivot or stop. Gate 6 decides by calculation; the memo explains that
              decision and is never allowed to soften it or to mention income figures.
"""
from .. import costs as C
from .. import mocks
from ..schema import arr, obj, s
from .base import Agent, StepResult

REPLIES = obj({"replies": arr(obj({"ticket_id": s(), "reply": s(20)}), 1, 10)})
MEMO = obj({"summary": s(30), "what_we_learned": arr(s(10), 2, 5), "next_steps": arr(s(10), 2, 5),
            "risks": arr(s(10), 1, 4)})
LABELS = {"go": "PERSEVERE", "pivot": "PIVOT", "stop": "STOP"}


class OperateAgent(Agent):
    name = "operate"

    def support(self, feedback=None) -> StepResult:
        tickets = mocks.support_tickets()
        ids = {t["ticket_id"] for t in tickets}
        listing = "\n".join(f"- {t['ticket_id']} ({t['status']}): {t['topic']}" for t in tickets)
        task = ("Draft a short, helpful and honest reply to each of these [SIMULATED] support tickets, one "
                "reply per ticket id. Never promise features that do not exist.\n" + listing)

        def check(d):
            # one reply per real ticket: repeats and invented ticket ids are dropped
            d["replies"][:] = [r for r in d["replies"] if r["ticket_id"] in ids]
            seen = set()
            d["replies"][:] = [r for r in d["replies"] if not (r["ticket_id"] in seen or seen.add(r["ticket_id"]))]
            if not d["replies"]:
                raise ValueError(f"reply to these ticket ids: {sorted(ids)}")
            for tid in sorted(ids - seen):         # a ticket the model skipped is left to the founder
                d["replies"].append({"ticket_id": tid, "reply": "No draft in this run: the founder answers this "
                                                                "ticket personally."})

        def build(fb):
            d, _ = self.ask("support_replies", task, REPLIES, feedback=fb, check=check)
            topics = {t["ticket_id"]: t["topic"] for t in tickets}
            md = ["# Support reply drafts", "",
                  "> The tickets are [SIMULATED] fixtures. Sending replies needs the founder's approval and "
                  "is MOCKED: nothing is sent.", ""]
            for reply in sorted(d["replies"], key=lambda r: r["ticket_id"]):
                md += [f"## {reply['ticket_id']}: {topics[reply['ticket_id']]}", "", reply["reply"], ""]
            return "\n".join(md), d

        d = self.guarded(build, feedback)
        path = self.ctx.writer.write(6, 1, "support-replies", self.latest, labels=["[SIMULATED] tickets"])
        return StepResult(f"{len(d['replies'])} support reply drafts.", [path], {"tickets": tickets, **d})

    def metrics(self) -> StepResult:
        b, st = self.ctx.brief, self.ctx.state
        signups = mocks.signups(b.mock_scenario)
        preference = mocks.audience_preference(b.mock_scenario)
        tickets = mocks.support_tickets()
        resolved = sum(t["status"] == "resolved" for t in tickets)
        cost = st.get("costs") or {"monthly": 0.0, "one_off": 0.0, "runway_months": 0.0}
        price = st.get("price") or {}
        md = ["# Metrics", "",
              "> Demand and support numbers are [SIMULATED] fixtures. Costs come from Phase 1, each sourced or "
              "labelled ASSUMPTION. No income, revenue or profit figure is reported.", "",
              "| Metric | Value |", "|---|---|",
              f"| Waitlist sign-ups ({signups['days']} days) | {signups['count']} [SIMULATED] |",
              f"| Preferred over alternatives | {preference['prefer_pct']}% [SIMULATED] |",
              f"| Support tickets resolved | {resolved} of {len(tickets)} [SIMULATED] |",
              f"| Monthly costs | {C.fmt_money(cost['monthly'], b.currency)} |",
              f"| The budget covers | {C.fmt_months(cost['runway_months'])} |",
              f"| Break-even condition at the chosen price | {price.get('break_even', 'n/a')} paying customers a month |"]
        self.ctx.logger.log(self.name, "compute_metrics", simulated=True)
        path = self.ctx.writer.write(6, 2, "metrics", "\n".join(md), labels=["[SIMULATED]"])
        return StepResult("Metrics compiled.", [path],
                          {"signups": signups, "runway_months": cost["runway_months"]})

    def memo(self, outcome: str, reasons: list[str], feedback=None) -> StepResult:
        if outcome not in LABELS:
            raise ValueError(f"outcome must be one of {list(LABELS)}")
        label = LABELS[outcome]
        task = (f"Gate 6 has already decided, by calculation: {label}. Its reasons: {'; '.join(reasons)}. "
                "Write a short persevere-or-pivot memo that explains this decision honestly: what was learned, "
                f"concrete next steps and the risks. Do not argue with the decision and do not soften a STOP. "
                "No income, revenue or profit figures.")

        def build(fb):
            d, _ = self.ask("persevere_pivot_memo", task, MEMO, feedback=fb)
            md = [f"# Persevere-or-pivot memo: {label}", "",
                  f"**Decision, calculated by Gate 6 from [SIMULATED] signals and cost data: {label}.**", "",
                  *[f"- {reason}" for reason in reasons], "", d["summary"], "", "## What we learned", ""]
            md += [f"- {x}" for x in d["what_we_learned"]]
            md += ["", "## Next steps", ""] + [f"{i}. {x}" for i, x in enumerate(d["next_steps"], 1)]
            md += ["", "## Risks", ""] + [f"- {x}" for x in d["risks"]]
            return "\n".join(md), d

        self.guarded(build, feedback)
        path = self.ctx.writer.write(6, 3, "memo", self.latest)
        return StepResult(f"Memo written: {label}.", [path], {"memo": self.latest, "label": label})
