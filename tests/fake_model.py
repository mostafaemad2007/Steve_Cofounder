"""TEST-ONLY scripted model. It never produces committed outputs: those come from live runs.

It answers each agent action (sent to Ollama as format.title) with a canned, valid reply shaped like
a real model's output. `overrides` replays a list of replies for an action, in order, so a test can
script "first a bad reply, then a good one".
"""
import copy
import json

ITEM = ("Use this checklist before every application. List the role, the company and the deadline. "
        "Match three skills from the job post to three finished projects, with one line of proof for "
        "each. Keep the CV to one page and export it as a PDF named after you. Ask a friend to read it "
        "aloud to catch mistakes before you send it.")
SCRIPT_QUESTIONS = ["Tell me about the last time you updated your CV.", "What did you use to make it?",
                    "What was the hardest part of that?", "Have you paid for any help with your CV before?",
                    "Where did you look for templates last time?", "What happened after you sent it?"]

RESPONSES = {
    "plan_web_searches": {"competitors": ["CV templates Egypt graduates", "bilingual resume templates"],
                          "market": ["Egypt engineering graduates jobs"], "legal": ["resume template licence terms"],
                          "costs": ["static hosting price per month"], "pricing": ["CV template pack price"]},
    "restate_idea": {
        "restatement": "A bilingual Arabic and English CV template pack for Egyptian fresh graduates "
                       "applying to junior tech jobs.",
        "is_digital_product": True, "product_type": "template pack", "excluded_category": None,
        "open_questions": ["Which roles first?"]},
    "find_opportunities": {
        "options": [
            {"name": "Founder idea", "description": "Bilingual CV template pack", "demand": 4,
             "competition_room": 3, "founder_fit": 5, "note": "Clear niche"},
            {"name": "CV review service", "description": "Paid one-to-one CV reviews", "demand": 3,
             "competition_room": 2, "founder_fit": 3, "note": "Time heavy"},
            {"name": "Interview prep pack", "description": "Question bank for interviews", "demand": 3,
             "competition_room": 3, "founder_fit": 4, "note": "Adjacent"}],
        "competitors": [{"name": "Canva", "what_they_offer": "Generic CV templates", "source_id": "S1"}],
        "verdict": "promising",
        "verdict_reasons": ["Generic templates ignore Arabic layout needs.",
                            "Graduates already search for CV help."],
        "claims": [{"text": "Canva offers free CV templates", "source_id": "S1", "confidence": "high"},
                   {"text": "Many engineering students graduate each year", "source_id": "[s2]", "confidence": "medium"},
                   {"text": "Graduates prefer bilingual CVs", "source_id": None, "confidence": "low"},
                   {"text": "An invented statistic", "source_id": "S99", "confidence": "low"}]},
    "market_fit": {
        "fit": "good",
        "factors": [{"factor": f, "rating": "positive", "assessment": "Supports the idea in this market."}
                    for f in ("demand", "competition", "culture", "language")],
        "claims": [{"text": "Tech employers hire graduates every year", "source_id": "S1", "confidence": "medium"}]},
    "improvements_ip_check": {
        "improvements": [{"title": "Focus on software roles", "change": "Target junior developers first.",
                          "why": "Clearer need and better examples.", "cost_impact": "none"}],
        "ip_checklist": [{"area": a, "status": "unknown", "finding": "Nothing conclusive in the sources.",
                          "source_id": None} for a in ("trademark", "copyright_licensing", "platform_terms",
                                                       "patents", "exclusive_rights_regulation")],
        "skill_gaps": [{"skill": "Design", "blocking": False, "how_to_cover": "Use free fonts"}],
        "claims": [{"text": "Google Fonts are free to use", "source_id": "S1", "confidence": "high"}]},
    "list_costs": {
        "one_off": [{"item": "Domain", "cost": 12, "source_id": "S1"}],
        "monthly": [{"item": "Hosting", "cost": 5, "source_id": "S1"},
                    {"item": "Email tool", "cost": 10, "source_id": None}],
        "cheaper_options": ["Use a free static host instead of paid hosting"]},
    "mom_test_script": {
        "segment": "Final-year computer science students in Cairo",
        "learning_goals": ["How they build CVs today", "What they already pay for"],
        "questions": [{"question": q, "why": "Past behaviour"} for q in SCRIPT_QUESTIONS],
        "avoid": ["Pitching the idea", "Hypothetical questions"]},
    "lean_canvas": {
        "problem": ["Generic templates ignore Arabic"], "customer_segments": ["Fresh graduates"],
        "unique_value_proposition": "Bilingual CVs that pass tech recruiters' screening",
        "solution": ["Template pack with worked examples"], "channels": ["University groups"],
        "pricing_model": "One-time purchase", "cost_structure": ["Hosting"],
        "key_metrics": ["Waitlist sign-ups"], "unfair_advantage": "Founder knows local hiring"},
    "landing_page": {
        "headline": "Bilingual CVs for tech graduates",
        "subheadline": "Arabic and English templates made for junior tech roles.",
        "benefits": ["Right-to-left ready", "Worked examples", "One page"],
        "how_it_works": ["Pick a template", "Fill in your projects", "Export to PDF"],
        "faq": [{"q": "Is it editable?", "a": "Yes, in Google Docs."},
                {"q": "Which roles?", "a": "Junior software roles."}],
        "cta_label": "Join the waitlist"},
    "detailed_plan": {"areas": [
        {"area": a, "steps": ["Do the first thing", "Do the second thing"],
         "options": [{"name": "Free route", "cost": "0", "time": "1 week", "tradeoffs": "Slower but free"}],
         "tools": ["Google Docs"], "founder_approves": "The final version"}
        for a in ("operate_and_learn", "find_opportunity", "design_business", "build_product",
                  "price_and_policies", "open_store", "deliver_automatically")]},   # deliberately shuffled
    "build_mvp": {
        "product_name": "Bilingual Tech CV Pack",
        "tagline": "Arabic and English CV templates for junior tech roles.",
        "audience": "Egyptian fresh graduates",
        "items": [{"title": t, "description": "A practical template with guidance.", "content": ITEM}
                  for t in ("One-page developer CV", "Project proof checklist", "Arabic layout guide")],
        "user_docs": {"quick_start": ["Open the pack", "Pick a template", "Export to PDF"],
                      "faq": [{"q": "Can I edit it?", "a": "Yes, every template is editable."},
                              {"q": "Is Arabic supported?", "a": "Yes, right-to-left layouts are included."}]}},
    "pricing_options": {
        "options": [{"name": "Basic pack", "price": 5, "includes": "3 templates",
                     "rationale": "Below competitor paid packs"},
                    {"name": "Full pack", "price": 9, "includes": "All templates and guides",
                     "rationale": "Matches local purchasing power"}],
        "recommended": "Full pack"},
    "draft_policies": {k: [{"heading": h, "text": "Plain-language text explaining this section to buyers."}
                           for h in ("Scope", "Use", "Contact")] for k in ("terms", "privacy", "refund")},
    "store_page": {
        "title": "Bilingual Tech CV Pack",
        "description": "Arabic and English CV templates with worked examples for junior tech roles.",
        "bullets": ["3 templates", "Arabic layout guide", "Application checklist"],
        "faq": [{"q": "What format?", "a": "Google Docs and PDF."}, {"q": "Refunds?", "a": "See the draft policy."}],
        "button_label": "Get the pack"},
    "launch_posts": {"posts": [
        {"channel": "LinkedIn", "text": "I made a bilingual CV template pack for junior tech roles: <STORE_LINK>"},
        {"channel": "University group", "text": "Graduating this year? Arabic and English CV templates: <STORE_LINK>"}]},
    "support_replies": {"replies": [
        {"ticket_id": t, "reply": "Thanks for writing. Here is how to solve this, step by step."}
        for t in ("T-1", "T-2", "T-3")]},
    "persevere_pivot_memo": {
        "summary": "Demand signals are above the target and the budget covers the planning period.",
        "what_we_learned": ["Graduates respond to bilingual layouts", "Costs stay low"],
        "next_steps": ["Run five real interviews", "Test a real waitlist"],
        "risks": ["Simulated demand may not match reality"]},
}


class FakeModel:
    def __init__(self, overrides=None):
        self.overrides = {action: list(replies) for action, replies in (overrides or {}).items()}
        self.calls: list[str] = []
        self.prompts: list[str] = []

    def __call__(self, url, payload, timeout):
        action = payload.get("format", {}).get("title", "")
        self.calls.append(action)
        self.prompts.append(payload["messages"][-1]["content"])
        if self.overrides.get(action):
            reply = self.overrides[action].pop(0)
        elif action == "check_json":
            reply = {"idea": "A shared notes app for study groups"}
        elif action not in RESPONSES:          # e.g. the warm-up ("Say OK") has no schema
            reply = "OK"
        else:
            reply = copy.deepcopy(RESPONSES[action])
        content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return {"message": {"content": content}, "prompt_eval_count": 200, "eval_count": 80}


def variant(action: str, **changes) -> dict:
    """A copy of the canned reply for `action` with some fields replaced."""
    reply = copy.deepcopy(RESPONSES[action])
    reply.update(changes)
    return reply
