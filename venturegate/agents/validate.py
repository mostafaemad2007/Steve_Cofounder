"""Phase 2 Validate. Core step: design the business.

Steps
  1 lean canvas    nine blocks; the pricing model in words, never an amount
  2 landing page   copy for a waitlist test, rendered to HTML. The form is MOCKED: it stores nothing.
  3 demand         no model involved: reads the [SIMULATED] fixture for this run's scenario
  4 detailed plan  the seven-area plan, given only after the founder's final confirmation
"""
import html

from .. import mocks
from ..schema import arr, obj, s
from .base import Agent, StepResult, unique

CANVAS = obj({
    "problem": arr(s(5), 1, 3), "customer_segments": arr(s(3), 1, 3), "unique_value_proposition": s(10),
    "solution": arr(s(5), 1, 3), "channels": arr(s(3), 1, 4), "pricing_model": s(5),
    "cost_structure": arr(s(3), 1, 5), "key_metrics": arr(s(3), 1, 4), "unfair_advantage": s(5),
})

LANDING = obj({
    "headline": s(5), "subheadline": s(10), "benefits": arr(s(5), 3, 5),
    "how_it_works": arr(s(5), 3, 3), "faq": arr(obj({"q": s(5), "a": s(5)}), 2, 4), "cta_label": s(2),
})

PLAN_AREAS = {
    "find_opportunity": "1. Find and confirm the opportunity",
    "design_business": "2. Design the business",
    "build_product": "3. Build the product",
    "price_and_policies": "4. Set the price and policies",
    "open_store": "5. Open the store",
    "deliver_automatically": "6. Deliver automatically",
    "operate_and_learn": "7. Operate and learn",
}
OPTION = obj({"name": s(), "cost": s(1), "time": s(1), "tradeoffs": s(5)})
PLAN = obj({"areas": arr(obj({
    "area": {"type": "string", "enum": list(PLAN_AREAS)},
    "steps": arr(s(5), 2, 6),
    "options": arr(OPTION, 1, 3),          # the Section 3 rule: at most the best three
    "tools": arr(s(2), 1, 5),
    "founder_approves": s(5),
}), 7, 7)})


class ValidateAgent(Agent):
    name = "validate"

    # 1 --------------------------------------------------------------------
    def lean_canvas(self, feedback=None) -> StepResult:
        task = ("Fill in a Lean Canvas for the agreed idea. For pricing_model describe HOW it would charge "
                "(for example a one-time purchase), with no amounts and no revenue or income figures.")

        def build(fb):
            d, _ = self.ask("lean_canvas", task, CANVAS, feedback=fb)
            blocks = [("Problem", d["problem"]), ("Customer segments", d["customer_segments"]),
                      ("Unique value proposition", [d["unique_value_proposition"]]),
                      ("Solution", d["solution"]), ("Channels", d["channels"]),
                      ("Pricing model", [d["pricing_model"]]), ("Cost structure", d["cost_structure"]),
                      ("Key metrics", d["key_metrics"]), ("Unfair advantage", [d["unfair_advantage"]])]
            md = ["# Lean Canvas", ""]
            for title, items in blocks:
                md += [f"## {title}", ""] + [f"- {item}" for item in items] + [""]
            return "\n".join(md), d

        d = self.guarded(build, feedback)
        self.ctx.state["uvp"] = d["unique_value_proposition"]
        path = self.ctx.writer.write(2, 1, "lean-canvas", self.latest)
        return StepResult(f"Value proposition: {d['unique_value_proposition']}", [path], d)

    # 2 --------------------------------------------------------------------
    def landing_page(self, feedback=None) -> StepResult:
        task = ("Write landing page copy to test demand with a waitlist. Be specific and honest about what "
                "the product does. No testimonials, ratings, user counts, urgency, scarcity or income promises.")

        def build(fb):
            d, _ = self.ask("landing_page", task, LANDING, feedback=fb)
            text = "\n".join([d["headline"], d["subheadline"], *d["benefits"], *d["how_it_works"],
                              *[f"{x['q']} {x['a']}" for x in d["faq"]], d["cta_label"]])
            return text, d

        d = self.guarded(build, feedback)
        e = lambda value: html.escape(str(value), quote=True)        # noqa: E731
        lang = self.ctx.brief.language
        page = f"""<!DOCTYPE html>
<html lang="{lang}" dir="{'rtl' if lang == 'ar' else 'ltr'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(d['headline'])}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:0 auto;padding:24px;line-height:1.5}}
.cta{{background:#f4f7ff;border-radius:12px;padding:16px}} input,button{{padding:10px;font-size:15px}}</style>
</head><body>
<h1>{e(d['headline'])}</h1><p>{e(d['subheadline'])}</p>
<ul>{''.join(f'<li>{e(b)}</li>' for b in d['benefits'])}</ul>
<h2>How it works</h2><ol>{''.join(f'<li>{e(step)}</li>' for step in d['how_it_works'])}</ol>
<div class="cta"><form onsubmit="event.preventDefault();this.querySelector('p').hidden=false">
<input type="email" placeholder="you@example.com" aria-label="Email"> <button>{e(d['cta_label'])}</button>
<p hidden>MOCKED: this draft collects nothing. No email is stored or sent.</p></form></div>
<h2>Questions</h2>{''.join(f'<p><strong>{e(x["q"])}</strong><br>{e(x["a"])}</p>' for x in d['faq'])}
</body></html>"""
        path = self.ctx.writer.write(2, 2, "landing-page", page, ext="html",
                                     labels=["DRAFT, not published", "waitlist form MOCKED"])
        return StepResult(f"Landing page draft: \"{d['headline']}\" (not published).", [path], d)

    # 3 --------------------------------------------------------------------
    def demand(self) -> StepResult:
        """No model call. The numbers are fixtures; this step only reads and labels them."""
        scenario = self.ctx.brief.mock_scenario
        signups, preference = mocks.signups(scenario), mocks.audience_preference(scenario)
        md = ["# Demand signals [SIMULATED]", "",
              f"> [SIMULATED] These numbers are prepared fixtures from `venturegate/mocks/` (scenario: "
              f"{scenario}). They show how the gate works. They are not real sign-ups and not a forecast "
              "of what this idea would achieve.", "",
              f"- Waitlist sign-ups: **{signups['count']} in {signups['days']} days** [SIMULATED]",
              f"- Preferred this over the alternatives: {preference['prefer_pct']}% of a sample of "
              f"{preference['sample_size']} [SIMULATED]", "",
              "Gate 2 compares the sign-ups with the target fixed in `gates.yaml` before the run.",
              "To use real numbers, run a real waitlist and replace the fixture."]
        self.ctx.logger.log(self.name, "load_simulated_demand", simulated=True, scenario=scenario,
                            signups=signups["count"], prefer_pct=preference["prefer_pct"])
        self.ctx.state["signups"] = signups
        path = self.ctx.writer.write(2, 3, "demand-signals", "\n".join(md), labels=["[SIMULATED]"])
        return StepResult(f"{signups['count']} sign-ups in {signups['days']} days [SIMULATED].", [path],
                          {"signups": signups, "preference": preference})

    # 4 --------------------------------------------------------------------
    def plan(self, feedback=None) -> StepResult:
        task = ("Write the detailed plan the founder will follow, with exactly one entry for each area: "
                "find_opportunity, design_business, build_product, price_and_policies, open_store, "
                "deliver_automatically, operate_and_learn. For each: concrete steps; up to three options, "
                "only those that truly apply, each with cost, time and trade-offs so the founder can choose by "
                "budget; tools; and what the founder must approve. Payments: name a real payment provider "
                "only as a manual step the founder takes outside this system. No income figures.")

        def check(d):
            unique([a["area"] for a in d["areas"]], "plan area")

        def build(fb):
            d, _ = self.ask("detailed_plan", task, PLAN, feedback=fb, check=check)
            order = list(PLAN_AREAS)
            md = ["# Detailed plan", "",
                  "> Each area offers at most the three best options, only those that truly apply, with cost "
                  "and trade-offs. Nothing is published, sent or spent without the founder's approval.", ""]
            for area in sorted(d["areas"], key=lambda a: order.index(a["area"])):
                md += [f"## {PLAN_AREAS[area['area']]}", ""]
                md += [f"{i}. {step}" for i, step in enumerate(area["steps"], 1)]
                md += ["", "| Option | Cost | Time | Trade-offs |", "|---|---|---|---|"]
                md += [f"| {o['name']} | {o['cost']} | {o['time']} | {o['tradeoffs']} |" for o in area["options"]]
                md += ["", f"- Tools: {', '.join(area['tools'])}",
                       f"- The founder approves: {area['founder_approves']}", ""]
            return "\n".join(md), d

        self.guarded(build, feedback)
        path = self.ctx.writer.write(2, 4, "detailed-plan", self.latest)
        return StepResult("The detailed seven-area plan is ready.", [path], {})
