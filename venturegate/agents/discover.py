"""Phase 1 Discover. Core step: find opportunities.

Steps
  1 intake          restate the idea; flag a non-digital or excluded product
  2 opportunities   compare the idea with alternatives; give an honest verdict with evidence
  3 market fit      judge the idea against the target market
  4 improvements    up to 3 improvements, the intellectual property checklist, skill gaps
  5 costs/runway    the model lists costs with sources; the arithmetic is done in code
  6 interview       a Mom Test script. The interviews themselves are STUBBED: the founder runs them.
"""
import re

from .. import costs as C
from ..schema import CLAIMS, arr, obj, s
from .base import Agent, StepResult, planning_months, unique

IP_AREAS = ("trademark", "copyright_licensing", "platform_terms", "patents", "exclusive_rights_regulation")
MARKET_FACTORS = ("demand", "competition", "culture", "regulation", "language", "purchasing_power")
NULLABLE_ID = {"type": ["string", "null"]}

INTAKE = obj({
    "restatement": s(20),
    "is_digital_product": {"type": "boolean"},
    "product_type": s(),
    "excluded_category": {"type": ["string", "null"]},
    "open_questions": arr(s(), 0, 4),
})

OPPORTUNITIES = obj({
    "options": arr(obj({
        "name": s(), "description": s(10),
        "demand": {"type": "integer", "minimum": 1, "maximum": 5},
        "competition_room": {"type": "integer", "minimum": 1, "maximum": 5},
        "founder_fit": {"type": "integer", "minimum": 1, "maximum": 5},
        "note": s(),
    }), 3, 5),
    "competitors": arr(obj({"name": s(), "what_they_offer": s(5), "source_id": NULLABLE_ID}), 0, 6),
    "verdict": {"type": "string", "enum": ["strong", "promising", "weak", "not_viable"]},
    "verdict_reasons": arr(s(10), 2, 6),
    "claims": CLAIMS,
})

MARKET = obj({
    "fit": {"type": "string", "enum": ["good", "mixed", "poor"]},
    "factors": arr(obj({
        "factor": {"type": "string", "enum": list(MARKET_FACTORS)},
        "rating": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "assessment": s(10),
    }), 4, 6),
    "claims": CLAIMS,
})

IMPROVE = obj({
    "improvements": arr(obj({
        "title": s(), "change": s(10), "why": s(10),
        "cost_impact": {"type": "string", "enum": ["none", "low", "medium", "high"]},
    }), 1, 3),
    "ip_checklist": arr(obj({
        "area": {"type": "string", "enum": list(IP_AREAS)},
        "status": {"type": "string", "enum": ["clear", "risk", "unknown"]},
        "finding": s(10),
        "source_id": NULLABLE_ID,
    }), 5, 5),
    "skill_gaps": arr(obj({"skill": s(), "blocking": {"type": "boolean"}, "how_to_cover": s()}), 0, 4),
    "claims": CLAIMS,
})

COST_ITEM = obj({"item": s(), "cost": {"type": "number", "minimum": 0}, "source_id": NULLABLE_ID})
COSTS = obj({"one_off": arr(COST_ITEM, 0, 8), "monthly": arr(COST_ITEM, 1, 10),
             "cheaper_options": arr(s(10), 0, 3)})

SCRIPT = obj({
    "segment": s(),
    "learning_goals": arr(s(), 2, 4),
    "questions": arr(obj({"question": s(10), "why": s(5)}), 6, 12),
    "avoid": arr(s(), 2, 6),
})

# The Mom Test: ask about past behaviour, never about a hypothetical future.
HYPOTHETICAL = re.compile(
    r"^\s*(would|will|could|might|do you think|if (we|i) (built|made|offered)|how much would you)\b"
    r"|\bwould you (pay|buy|use|like|want)\b", re.I)
DISCLAIMER = "This is not legal advice; consult a qualified professional before relying on it."


class DiscoverAgent(Agent):
    name = "discover"

    # 1 --------------------------------------------------------------------
    def intake(self, feedback=None) -> StepResult:
        task = ("Restate the founder's idea in two or three plain sentences so they can confirm you "
                "understood it. Say whether it is a digital product (software, online service, content "
                "or tool) and what type. If it belongs to an excluded category (physical goods; "
                "financial, investment or crypto products; health or medical; legal advice) name that "
                "category in excluded_category, otherwise use null. List up to four open questions.")

        def build(fb):
            d, _ = self.ask("restate_idea", task, INTAKE, feedback=fb)
            md = ["# Idea intake", "", d["restatement"], "",
                  f"- Digital product: {'yes' if d['is_digital_product'] else 'NO'}",
                  f"- Type: {d['product_type']}"]
            if d["excluded_category"]:
                md.append(f"- Excluded category: **{d['excluded_category']}**")
            if d["open_questions"]:
                md += ["", "## Open questions", ""] + [f"- {q}" for q in d["open_questions"]]
            return "\n".join(md), d

        d = self.guarded(build, feedback)
        in_scope = d["is_digital_product"] and not d["excluded_category"]
        if in_scope:
            self.ctx.state["idea_summary"] = d["restatement"]
        path = self.ctx.writer.write(1, 1, "intake", self.latest)
        summary = d["restatement"] if in_scope else \
            f"Out of scope: {d['excluded_category'] or 'not a digital product'}."
        return StepResult(summary, [path], {**d, "in_scope": in_scope})

    # 2 --------------------------------------------------------------------
    def opportunities(self, feedback=None) -> StepResult:
        b = self.ctx.brief
        task = ("Find opportunities. Compare the founder's idea (the first option, named 'Founder idea') "
                "with at least two other angles or niches this same founder could pursue instead. Score "
                "each from 1 to 5 on demand, room against competitors (5 = little competition) and "
                "founder fit, using the sources. List real competitors found in the sources. Then give an "
                "honest verdict (strong, promising, weak or not_viable) with concrete reasons. A crowded "
                "market with no clear difference is weak. Do not flatter.")
        query = f"{b.idea} competitors alternatives pricing {b.target_market or ''}"

        def check(d):
            unique([o["name"] for o in d["options"]], "option name")

        def build(fb):
            d, srcmap = self.ask("find_opportunities", task, OPPORTUNITIES, query=self.research("competitors", query), feedback=fb,
                                 check=check)
            ranked = sorted(d["options"], key=lambda o: -(o["demand"] + o["competition_room"] + o["founder_fit"]))
            md = ["# Opportunities and an honest verdict", "",
                  f"**Verdict: {d['verdict'].replace('_', ' ').upper()}**", ""]
            md += [f"- {reason}" for reason in d["verdict_reasons"]]
            md += ["", "## Options compared", "",
                   "Scores are 1 to 5; the total is added up by code. Scores are the model's judgement from "
                   "the evidence below and count as ASSUMPTION where a point is unsourced.", "",
                   "| Option | Demand | Room vs competitors | Founder fit | Total | Note |",
                   "|---|---|---|---|---|---|"]
            for o in ranked:
                score = o["demand"] + o["competition_room"] + o["founder_fit"]
                md.append(f"| {o['name']} | {o['demand']} | {o['competition_room']} | {o['founder_fit']} | "
                          f"**{score}** | {o['note']} |")
            md += ["", "## Competitors", ""]
            used = set()
            for comp in d["competitors"] or []:
                url = self.cite(comp["source_id"], srcmap)
                used.add(url)
                md.append(f"- **{comp['name']}**: {comp['what_they_offer']} " +
                          (f"([source]({url}))" if url else "(ASSUMPTION)"))
            if not d["competitors"]:
                md.append("- None identified in the saved sources (ASSUMPTION: that does not mean none exist).")
            md += ["", "## Evidence", ""] + self.claim_lines(d["claims"], srcmap, "phase1_step2")
            used |= {self.cite(c["source_id"], srcmap) for c in d["claims"]}
            md.append(self.sources_section(srcmap, used))
            return "\n".join(md), (d, ranked)

        d, ranked = self.guarded(build, feedback)
        self.ctx.state["verdict"] = f"{d['verdict']}: {d['verdict_reasons'][0]}"
        self.ctx.state["verdict_reasons"] = list(d["verdict_reasons"])
        self.ctx.state["alternatives"] = len(d["options"])
        path = self.ctx.writer.write(1, 2, "opportunities", self.latest)
        return StepResult(f"Verdict: {d['verdict'].replace('_', ' ').upper()}. {d['verdict_reasons'][0]}",
                          [path], {"verdict": d["verdict"], "verdict_reasons": list(d["verdict_reasons"]), "options": ranked})

    # 3 --------------------------------------------------------------------
    def market(self, feedback=None) -> StepResult:
        market = self.ctx.brief.target_market
        if not market:
            raise ValueError("the target market must be known before judging market fit")
        task = (f"Judge whether this idea suits the target market: {market}. Rate demand, competition, "
                "culture, regulation, language and purchasing power (each at most once) as positive, "
                "neutral or negative with a short assessment, then give the overall fit.")

        def check(d):
            unique([f["factor"] for f in d["factors"]], "market factor")

        def build(fb):
            d, srcmap = self.ask("market_fit", task, MARKET, query=self.research("market", f"{market} {self.ctx.brief.idea}"),
                                 feedback=fb, check=check)
            md = [f"# Target market fit: {market}", "", f"**Overall fit: {d['fit'].upper()}**", "",
                  "| Factor | Rating | Assessment |", "|---|---|---|"]
            md += [f"| {f['factor'].replace('_', ' ')} | {f['rating']} | {f['assessment']} |" for f in d["factors"]]
            md += ["", "## Evidence", ""] + self.claim_lines(d["claims"], srcmap, "phase1_step3")
            md.append(self.sources_section(srcmap, {self.cite(c["source_id"], srcmap) for c in d["claims"]}))
            return "\n".join(md), d

        d = self.guarded(build, feedback)
        self.ctx.state["market_fit"] = d["fit"]
        path = self.ctx.writer.write(1, 3, "market-fit", self.latest)
        return StepResult(f"Fit with {market}: {d['fit'].upper()}.", [path], d)

    # 4 --------------------------------------------------------------------
    def improvements_ip(self, feedback=None) -> StepResult:
        task = ("Suggest one to three concrete improvements (positioning, features, niche, pricing "
                "direction or differentiation); list only those that truly apply. Then fill the "
                "intellectual property checklist with exactly one entry for each area: trademark, "
                "copyright_licensing, platform_terms, patents, exclusive_rights_regulation. Use status "
                "unknown whenever the sources do not settle it. Finally list the skills needed to build and "
                "sell this product (up to four), each with a free or low-cost way to learn it or get it done "
                "within the budget and hours. Mark a skill as blocking only if there is no such way.")
        if self.ctx.brief.skills:
            task += f" The founder already has: {', '.join(self.ctx.brief.skills)}; leave those out."

        def check(d):
            areas = [item["area"] for item in d["ip_checklist"]]
            unique(areas, "IP area")
            missing = sorted(set(IP_AREAS) - set(areas))
            if missing:
                raise ValueError(f"the IP checklist is missing: {missing}")

        def build(fb):
            d, srcmap = self.ask("improvements_ip_check", task, IMPROVE, check=check, feedback=fb,
                                 query=self.research("legal", f"{self.ctx.brief.idea} trademark licence terms of service copyright"))
            md = ["# Improvements, intellectual property check and skills needed", "", "## Suggested improvements", ""]
            for i, imp in enumerate(d["improvements"], 1):
                md += [f"### Option {i}: {imp['title']}", "", f"- Change: {imp['change']}",
                       f"- Why: {imp['why']}", f"- Cost impact: {imp['cost_impact']}", ""]
            md += ["## Intellectual property checklist", "", f"> {DISCLAIMER}", "",
                   "| Area | Status | Finding | Source |", "|---|---|---|---|"]
            used = set()
            for item in sorted(d["ip_checklist"], key=lambda i: IP_AREAS.index(i["area"])):
                url = self.cite(item["source_id"], srcmap)
                used.add(url)
                md.append(f"| {item['area'].replace('_', ' ')} | {item['status']} | {item['finding']} | "
                          f"{f'[source]({url})' if url else 'ASSUMPTION'} |")
            unknown = [i["area"].replace("_", " ") for i in d["ip_checklist"] if i["status"] == "unknown"]
            if unknown:
                md += ["", f"Still unknown: {', '.join(unknown)}."]
            md += ["", "## Skills this idea needs, and how to cover them", ""]
            md += [f"- {g['skill']}: {'**BLOCKING**' if g['blocking'] else 'not blocking'}. {g['how_to_cover']}"
                   for g in d["skill_gaps"]] or ["- None identified."]
            md += ["", "## Evidence", ""] + self.claim_lines(d["claims"], srcmap, "phase1_step4")
            used |= {self.cite(c["source_id"], srcmap) for c in d["claims"]}
            md.append(self.sources_section(srcmap, used))
            return "\n".join(md), d

        d = self.guarded(build, feedback)
        risks = [i["area"].replace("_", " ") for i in d["ip_checklist"] if i["status"] == "risk"]
        self.ctx.state.update(improvements=[i["title"] for i in d["improvements"]], ip_risks=risks,
                              skills_blocking=any(g["blocking"] for g in d["skill_gaps"]))
        path = self.ctx.writer.write(1, 4, "improvements-ip-check", self.latest)
        return StepResult(f"{len(d['improvements'])} improvement(s). IP risks: {', '.join(risks) or 'none found'} "
                          "(not legal advice).", [path], d)

    # 5 --------------------------------------------------------------------
    def costs(self, feedback=None) -> StepResult:
        b = self.ctx.brief
        months = planning_months()
        task = (f"List the real costs of building and running this in {b.currency}: one-off costs and "
                "recurring monthly costs (hosting, domain, tools, subscriptions, services). Choose the "
                "cheapest realistic option and cite a source id for each cost, or null. If the budget looks "
                "tight, give up to three cheaper options. Costs only: never mention income, revenue or profit.")

        def build(fb):
            d, srcmap = self.ask("list_costs", task, COSTS, feedback=fb,
                                 query=self.research("costs", f"{b.idea} hosting domain tools price per month cost"))
            one_off, monthly = C.total(d["one_off"]), C.total(d["monthly"])
            runway = C.runway_months(b.budget, one_off, monthly)
            md = ["# Costs and runway (costs only, no income figures)", "",
                  "> Customers take time to find a new product, so plan for an early period with little or "
                  "no income. The planning period below is an ASSUMPTION, not a prediction.", ""]
            used = set()
            for title, items, unit in (("One-off costs", d["one_off"], "Cost"),
                                       ("Monthly costs", d["monthly"], "Cost per month")):
                md += [f"## {title}", "", f"| Item | {unit} | Source |", "|---|---|---|"]
                for item in items:
                    url = self.cite(item["source_id"], srcmap)
                    used.add(url)
                    self.note_claim(f"{item['item']} costs about {C.clean(item['cost']):g} {b.currency} "
                                    f"({'one-off' if items is d['one_off'] else 'per month'})",
                                    url, "medium" if url else "low", "phase1_step5")
                    md.append(f"| {item['item']} | {C.fmt_money(item['cost'], b.currency)} | "
                              f"{f'[source]({url})' if url else 'ASSUMPTION'} |")
                if not items:
                    md.append("| None | 0 | |")
                md.append("")
            md += ["## Arithmetic (calculated by code)", "",
                   f"- One-off total: {C.fmt_money(one_off, b.currency)}",
                   f"- Monthly total (C): {C.fmt_money(monthly, b.currency)}",
                   f"- Founder budget: {C.fmt_money(b.budget, b.currency)}",
                   f"- Months of costs the budget covers after one-off costs: {C.fmt_months(runway)}",
                   f"- Planning period of little or no income: {months:g} months (ASSUMPTION)",
                   f"- Money needed for that period: {C.fmt_money(C.needed_for(months, one_off, monthly), b.currency)}",
                   "- Break-even condition: at price P you need at least ceil(C / P) paying customers a month "
                   "just to cover costs. It is a calculation, not a forecast; Phase 4 applies it to real prices.", ""]
            if runway < months:
                md += [f"**Warning: the budget covers {C.fmt_months(runway)}, less than the {months:g}-month "
                       "planning period.** Consider the cheaper options below or a smaller first version.", ""]
            if d["cheaper_options"]:
                md += ["## Cheaper options", ""] + [f"- {o}" for o in d["cheaper_options"]]
            md.append(self.sources_section(srcmap, used))
            return "\n".join(md), (one_off, monthly, runway)

        one_off, monthly, runway = self.guarded(build, feedback)
        self.ctx.state["costs"] = {"one_off": one_off, "monthly": monthly, "runway_months": runway}
        path = self.ctx.writer.write(1, 5, "costs-runway", self.latest)
        return StepResult(f"Monthly costs {C.fmt_money(monthly, b.currency)}; the budget covers {C.fmt_months(runway)}.",
                          [path], dict(self.ctx.state["costs"]))

    # 6 --------------------------------------------------------------------
    def interview_script(self, feedback=None) -> StepResult:
        task = ("Write a customer interview script that follows The Mom Test. Ask only about past "
                "behaviour: the last time the problem happened, how they handle it today, what they already "
                "spend time or money on. Never ask hypothetical or future questions such as 'would you use' "
                "or 'would you pay'. Do not write any answers; the founder runs real interviews.")

        def check(d):
            bad = [q["question"] for q in d["questions"] if HYPOTHETICAL.search(q["question"])]
            if bad:
                raise ValueError(f"these questions are hypothetical; rewrite them about past behaviour: {bad}")
            unique([q["question"] for q in d["questions"]], "question")

        def build(fb):
            d, _ = self.ask("mom_test_script", task, SCRIPT, feedback=fb, check=check)
            md = ["# Customer interview script (The Mom Test)", "",
                  "> Interviews are STUBBED: the founder runs them with real people. VentureGate never "
                  "writes interview answers or customer quotes.", "",
                  f"**Who to interview:** {d['segment']}", "", "## What we want to learn", ""]
            md += [f"- {g}" for g in d["learning_goals"]] + ["", "## Questions", ""]
            md += [f"{i}. {q['question']}  \n   _Why:_ {q['why']}" for i, q in enumerate(d["questions"], 1)]
            md += ["", "## Avoid", ""] + [f"- {a}" for a in d["avoid"]]
            md += ["", "## Notes template (filled in by the founder after each real interview)", "",
                   "| Person | Date | Last time it happened | Current workaround | Already spends on it | "
                   "Their own words |", "|---|---|---|---|---|---|"]
            return "\n".join(md), d

        d = self.guarded(build, feedback)
        path = self.ctx.writer.write(1, 6, "interview-script", self.latest, labels=["interviews STUBBED"])
        return StepResult(f"{len(d['questions'])} Mom Test questions for: {d['segment']}.", [path], d)
