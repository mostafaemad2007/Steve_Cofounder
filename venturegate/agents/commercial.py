"""Phase 4 Commercial setup. Core step: set the price and policies. No payments of any kind.

Steps
  1 pricing    up to three options; break-even arithmetic per option is done in code
  2 policies   Terms, Privacy and Refund drafts, each labelled "DRAFT - not legal advice" by code
"""
from .. import costs as C
from ..schema import arr, obj, s
from .base import Agent, StepResult, unique, dedupe

DRAFT_LABEL = "DRAFT - not legal advice"

PRICING = obj({
    "options": arr(obj({"name": s(), "price": {"type": "number", "minimum": 0.5}, "includes": s(5),
                        "rationale": s(10)}), 1, 3),
    "recommended": s(),
})
SECTIONS = arr(obj({"heading": s(2), "text": s(20)}), 3, 8)
POLICIES = obj({"terms": SECTIONS, "privacy": SECTIONS, "refund": SECTIONS})
POLICY_TITLES = (("terms", "Terms of Service"), ("privacy", "Privacy Policy"), ("refund", "Refund Policy"))


class CommercialAgent(Agent):
    name = "commercial"

    def pricing(self, feedback=None) -> StepResult:
        b = self.ctx.brief
        monthly = self.ctx.state.get("costs", {}).get("monthly", 0.0)
        task = (f"Propose up to three price options in {b.currency} for the MVP: what each includes and "
                "why. Only include options that truly apply. Base them on the competitor prices in the "
                "sources and the target market's purchasing power. Never estimate sales, revenue or income. "
                "Name the option you recommend in `recommended`.")

        def check(d):
            dedupe(d["options"], "name", "price option")

        def build(fb):
            d, _ = self.ask("pricing_options", task, PRICING, feedback=fb, check=check,
                            query=self.research("pricing", f"{b.idea} price pricing competitors {b.currency}"))
            md = ["# Pricing options", "",
                  f"> Break-even = paying customers a month needed just to cover monthly costs "
                  f"C = {C.fmt_money(monthly, b.currency)}, worked out as ceil(C / P). It is a calculation on "
                  "the founder's own numbers, not a forecast that anyone will buy. Payment-provider fees and "
                  "taxes are ignored here (ASSUMPTION).", "",
                  "| Option | Price P | Includes | Break-even customers a month | Why |", "|---|---|---|---|---|"]
            for option in d["options"]:
                needed = C.break_even_customers(monthly, option["price"])
                md.append(f"| {option['name']} | {C.fmt_money(option['price'], b.currency)} | {option['includes']} "
                          f"| {needed if needed is not None else 'n/a'} | {option['rationale']} |")
            chosen = self._recommended(d)
            note = "" if chosen["name"].strip().lower() == d["recommended"].strip().lower() else \
                f" (the model named '{d['recommended']}', which is not one of the options, so the first option is used)"
            md += ["", f"Recommended: **{chosen['name']}**{note}. The founder decides; this system never charges anyone."]
            return "\n".join(md), (d, chosen)

        d, chosen = self.guarded(build, feedback)
        self.ctx.state["price_options"] = d["options"]
        self.ctx.state["price"] = {
            "name": chosen["name"], "price": chosen["price"],
            "label": f"{chosen['name']} at {C.fmt_money(chosen['price'], b.currency)}",
            "break_even": C.break_even_customers(monthly, chosen["price"]),
        }
        path = self.ctx.writer.write(4, 1, "pricing", self.latest)
        price = self.ctx.state["price"]
        return StepResult(f"Recommended: {price['label']}. Break-even condition: {price['break_even']} "
                          "paying customers a month to cover costs.", [path], {"options": d["options"], **price})

    @staticmethod
    def _recommended(d: dict) -> dict:
        wanted = d["recommended"].strip().lower()
        return next((o for o in d["options"] if o["name"].strip().lower() == wanted), d["options"][0])

    def policies(self, feedback=None) -> StepResult:
        task = ("Draft short, fair, plain-language Terms of Service, a Privacy Policy and a Refund Policy for "
                "selling this digital product online. They are drafts for a qualified professional to review: "
                "do not present them as legal advice or as binding.")

        def build(fb):
            d, _ = self.ask("draft_policies", task, POLICIES, feedback=fb)
            texts, md = {}, ["# Draft policies", "",
                             f"> {DRAFT_LABEL}. Have a qualified professional review these before use.", ""]
            for key, title in POLICY_TITLES:
                body = [f"## {title} ({DRAFT_LABEL})", ""]
                for section in d[key]:
                    body += [f"### {section['heading']}", "", section["text"], ""]
                texts[key] = "\n".join(body)
                md.append(texts[key])
            return "\n".join(md), texts

        texts = self.guarded(build, feedback)
        self.ctx.state["policies"] = texts
        path = self.ctx.writer.write(4, 2, "policies", self.latest, labels=[DRAFT_LABEL])
        return StepResult(f"Terms, privacy and refund drafts written, each labelled '{DRAFT_LABEL}'.", [path], texts)
