"""The guard: deterministic Python checks around every step. No model is involved.

    pre_check(text)   every founder message and brief, before any agent sees it
    post_check(text)  every agent output, before it is shown or saved

The rules mirror README "What our system will NOT do". Two design choices matter:

1. Patterns are specific (a verb plus its object), not bare keywords. A guard that blocks
   "my competitors sell through Stripe" or "add a testimonials section we fill with real quotes
   later" is useless to a founder, so false alarms are treated as bugs and covered by tests.
2. Text is normalised first (NFKC, zero-width and bidi characters removed, dashes unified), so
   "w​rite fake reviews" cannot slip through.

Every refusal is logged, with its category, to decision_log.json.
"""
import re
import unicodedata
from dataclasses import dataclass, field

from .logger import DecisionLogger

F = re.I | re.S
ZERO_WIDTH = re.compile(r"[​-‏‪-‮⁠﻿]")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = ZERO_WIDTH.sub("", text)
    text = re.sub(r"[‐-―]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class GuardResult:
    allowed: bool
    category: str | None = None
    reason: str | None = None
    problems: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.allowed


WRITE = r"(write|generate|create|make|fake|invent|draft|produce|post|add|give me|craft|compose|fabricate)"

# (category, reason shown to the founder, patterns). First match wins, so order matters.
PRE_RULES: list[tuple[str, str, list[str]]] = [
    ("prompt_injection",
     "Requests to ignore or replace the system's rules are refused. The rules are what make a STOP "
     "trustworthy, so they are not negotiable mid-run.", [
         r"\b(ignore|disregard|forget|override|bypass|drop)\b.{0,30}\b(previous|prior|above|earlier|all|your|the|these|system|safety)\b.{0,25}\b(rules?|instructions?|guardrails?|prompts?|polic(y|ies)|restrictions?|checks?)",
         r"\byou are now\b", r"\bdeveloper mode\b", r"\bjailbreak", r"\bDAN mode\b",
         r"\b(reveal|print|show|repeat)\b.{0,20}\b(your )?system prompt\b",
         r"\bno (rules|restrictions|limits|guardrails) (apply|mode)\b",
         r"\bpretend\b.{0,20}\b(the rules|you have no)\b",
         r"تجاهل.{0,30}(القواعد|التعليمات)",
     ]),
    ("threshold_change",
     "Gate thresholds are fixed in gates.yaml before the run and cannot be changed to make an idea "
     "pass. Pre-registering them is what proves the result was not spun.", [
         r"\b(change|edit|lower|reduce|modify|set|adjust|tweak|relax|drop|raise)\b.{0,40}\b(thresholds?|gates\.yaml|gate (target|rule|number)s?|sign-?up target|target (to|of) \d)",
         r"\bgates\.yaml\b",
         r"\b(make|let|force|help)\b.{0,25}\b(the )?(gate|idea|it)\b.{0,20}\bpass\b",
     ]),
    ("publish_without_approval",
     "Nothing is published, sent or spent without the founder's explicit approval, and that is "
     "enforced in code rather than by habit.", [
         r"\b(publish|post|send|email|launch|spend|buy|tweet|share)\b.{0,50}\bwithout\b.{0,25}\b(my |the |founder'?s? |any )?(approval|asking|confirmation|review|permission|checking)",
         r"\b(skip|remove|disable|turn off)\b.{0,25}\b(the )?(approval|confirmation|review) (step|gate|process)?",
         r"\bauto-?approv", r"\bdon'?t ask (me|for approval|first)\b", r"\bjust (publish|post|send) it\b",
     ]),
    ("fake_reviews",
     "The system never writes reviews, ratings or testimonials. They have to come from real "
     "customers, or they are fabricated social proof.", [
         WRITE + r"\b.{0,40}\b(reviews?|testimonials?|ratings?|endorsements?)\b(?!\s*(section|page|form|widget|request|system|link))",
         r"\bfake\b.{0,20}\b(reviews?|testimonials?|ratings?|stars?|feedback)\b",
         r"\b(five|5)[- ]star\b.{0,20}\b(reviews?|ratings?)\b",
         r"(اكتب|اعمل|ولد|أنشئ).{0,30}(تقييمات|مراجعات|شهادات)",
     ]),
    ("fake_interviews",
     "Customer interview answers must come from real interviews. The system writes the script; "
     "inventing the answers would be fabricating testimony.", [
         r"\b(write|invent|make up|generate|fake|fill in|simulate|imagine|pretend)\b.{0,40}\b(interview|customer|user|respondent)\b.{0,25}\b(answers?|responses?|quotes?|feedback|transcripts?|notes)\b",
         r"\b(answer|fill)\b.{0,20}\bthe interview (questions?|script)\b.{0,20}\b(for me|yourself)\b",
     ]),
    ("fake_signups",
     "The system never creates sign-ups, users, followers or traction that do not exist.", [
         r"\bfake\b.{0,25}\b(sign-?ups?|users?|subscribers?|waitlist|followers?|traction|downloads?|customers?|numbers)",
         r"\b(create|generate|add|inflate|invent|buy|simulate)\b.{0,20}\d+.{0,25}\b(sign-?ups?|subscribers?|followers?|users?|customers?|waitlist)\b",
         r"\b(inflate|pad|boost|bump)\b.{0,25}\b(the )?(numbers?|sign-?ups?|metrics|results|stats)\b",
     ]),
    ("fake_urgency",
     "Fake urgency, scarcity and countdown timers pressure people with something untrue.", [
         r"\bonly\s+\d+\s+([\w-]+\s+){0,2}(left|remain|remaining|available)\b",
         r"\b\d+\s+(items?|spots?|seats?|copies|licen[sc]es?)\s+(left|remain)",
         r"\bcountdown\b", r"\bfake\b.{0,20}\b(urgency|scarcity|deadline|discount|timer)",
         r"\b(selling out|almost gone|last chance|ends tonight|hurry)\b",
         r"\b(urgency|scarcity)\b.{0,25}\b(trick|tactic|pressure|create|add)",
     ]),
    ("impersonation",
     "The system never poses as the founder, a customer, a real person or another brand.", [
         # "pretend to be X" is refused whatever X is: X is usually a real brand or person
         # ("pretend to be Canva"), which no generic word list would catch.
         r"\b(pretend|pose|masquerade)\b.{0,15}\b(to be|as)\b",
         r"\bimpersonat",
         r"\b(write|post|reply|sign|speak|comment)\b.{0,30}\bas (if (you|i) (were|was) )?(a |an |the )?(real |happy |satisfied )?(customer|user|buyer|client|the founder|me)\b",
         r"\bin the name of\b.{0,30}\b(company|brand|ceo|someone)\b",
     ]),
    ("credentials",
     "The system never stores passwords, API keys, card numbers or other credentials, and never "
     "creates or signs into accounts.", [
         r"\b(store|save|remember|keep|hold|record|log|memorise|memorize)\b.{0,35}\b(passwords?|api[ _-]?keys?|credit cards?|card numbers?|credentials?|secrets?|login details|tokens?)\b",
         r"\b(here is|this is) my (password|api key|card number)\b",
         r"\b(create|open|register|sign up for)\b.{0,20}\b(an? )?accounts?\b.{0,25}\b(for me|on my behalf|on (twitter|x|linkedin|facebook|instagram|gumroad|etsy|reddit))",
         r"\b(log ?in|sign ?in)\b.{0,25}\b(for me|as me|to my)\b",
     ]),
    ("payment_gateway",
     "No payment integration of any kind is allowed, not even a sandbox or test mode. Sales in this "
     "system are mocked, and a real provider is a manual step the founder takes outside it.", [
         r"\b(enable|integrate|set ?up|connect|add|use|test|configure|install|wire|hook up|implement)\b.{0,35}\b(stripe|paypal|braintree|adyen|razorpay|paddle|lemon ?squeezy|square|checkout|payment (gateway|provider|api|processing))\b",
         r"\b(stripe|paypal|braintree|adyen)\b.{0,25}\b(sandbox|test mode|test keys?|api keys?|integration|checkout|webhook)\b",
         r"\bsandbox\b.{0,25}\b(payment|checkout|mode|keys?)\b",
         r"\b(take|accept|process|collect)\b.{0,20}\b(real )?(payments?|cards?)\b",
     ]),
    ("money_movement",
     "The system never holds, moves, charges or refunds real money.", [
         r"\b(transfer|move|wire|withdraw|send|hold|collect)\b.{0,25}\b(money|funds|cash|payments?|payouts?)\b",
         r"\bcharge\b.{0,25}\b(customers?|cards?|buyers?|users?|them)",
         r"\b(issue|process|send|give|make)\b.{0,20}\b(a )?refunds?\b.{0,25}\b(to|for|the)\b",
     ]),
    ("income_promise",
     "The system never promises, predicts or estimates income, revenue or profit, not even as a "
     "range. It works with costs and break-even arithmetic instead.", [
         r"\bguarantee\w*\b.{0,45}(\$|\d|\b(income|revenue|profit|money|earn\w*|sales|success|customers)\b)",
         r"\byou will (earn|make|profit)\b",
         r"\b(make|earn)\b.{0,20}(\$\s?\d|\d[\d,]*\s?(\$|usd|egp|dollars?|pounds?))",
         r"\b(how much|predict|forecast|estimate|calculate|project)\b.{0,35}\b(income|revenue|profits?|earnings?|(i|we) (will|would) (earn|make))",
         r"\bpassive income\b", r"\bget rich\b",
         r"\bpromise\b.{0,35}\b(income|revenue|profit|money|success|results)\b",
     ]),
    ("paywall",
     "Core features are never put behind a paywall; hiding them would make the open-source promise "
     "hollow.", [
         r"\b(core|essential|basic|main|key)\b.{0,45}\b(paywall|behind a (pay|subscription|payment))",
         r"\b(paywall|behind a (pay|subscription|payment)\w*)\b.{0,45}\b(core|essential|basic|main|key)\b",
         r"\b(lock|hide|gate|restrict)\b.{0,25}\b(the )?(core|essential|basic) features?\b",
         r"\bpaywall\b.{0,35}\b(venturegate|this (tool|system|app)|the agents?)\b",
     ]),
    ("paid_api",
     "Only free, open-weight models are used. Paid APIs and paid models are not allowed in this "
     "project.", [
         r"\b(use|switch to|call|connect|enable|buy|upgrade to)\b.{0,25}\b(gpt-?4\w*|gpt-?5\w*|openai api|anthropic api|claude api|gemini api|paid (api|model|plan|tier|credits?))\b",
     ]),
    ("excluded_crypto_finance",
     "Financial, investment and crypto products are excluded from this challenge.", [
         r"\b(crypto\w*|bitcoin|ethereum|nfts?|memecoins?|defi|blockchain|icos?|web3|airdrops?|staking)\b",
         r"\btokens?\b.{0,20}\b(project|sale|launch|presale|economy|holders?)\b",
         r"\b(trading (bot|signals?|app)|stock (picks?|tips|advice)|investment (product|app|fund|advice|platform)|forex|loans?|lending|insurance|betting|gambling|casino)\b",
     ]),
    ("excluded_health",
     "Health and medical products or advice are excluded from this challenge.", [
         r"\b(medical|medicine|medication|diagnos\w*|prescri\w*|dosage|symptoms?|supplements?|patients?)\b",
         r"\b(treatment|therapy)\b.{0,20}\b(plan|for|program|app)\b",
         r"\bhealth (advice|app|product|tracker|coach\w*|service)\b",
         r"\b(cure|heal|treat)\b.{0,25}\b(pain|disease|illness|condition|depression|anxiety)\b",
     ]),
    ("excluded_legal",
     "Legal advice products and binding contracts are excluded. Policies here are drafts labelled "
     "'DRAFT - not legal advice'.", [
         r"\blegal advice\b", r"\bbinding\b.{0,25}\b(contracts?|agreements?)",
         r"\b(lawyer|attorney|legal) (bot|app|service|advisor)\b",
         r"\b(will|contract|lawsuit|legal document)\b.{0,15}\bgenerator\b",
     ]),
    ("excluded_physical",
     "Only digital products are in scope; physical goods are excluded.", [
         r"\bphysical (products?|goods?|items?|inventory)\b",
         r"\b(t-?shirts?|merch(andise)?|hardware devices?|dropshipping|print[- ]on[- ]demand|handmade|furniture|clothing line|mugs?|stickers?)\b",
         r"\b(ship|deliver)\b.{0,20}\b(to (their|the customer'?s?) (door|address)|by (post|courier))\b",
     ]),
]

INCOME_WORDS = r"(income|revenue|profits?|earnings?|mrr|arr|turnover|net margin|sales figures?)"
MONEY = r"((\$|usd|egp|eur|£|€)\s?\d[\d,.]*\s?k?|\d[\d,.]*\s?(k\b|\$|usd|egp|eur|dollars?|pounds?))"

# (category, pattern) applied to every agent output.
POST_RULES: list[tuple[str, str]] = [
    ("income_promise", r"\bguarantee\w*\b.{0,45}\b(income|revenue|profits?|earnings?|success|customers)\b"),
    ("income_promise", r"\byou will (earn|make|profit)\b"),
    ("income_figure", r"\b" + INCOME_WORDS + r"\b[^.\n]{0,45}" + MONEY),
    ("income_figure", MONEY + r"[^.\n]{0,45}\b" + INCOME_WORDS + r"\b"),
    ("income_forecast", r"\b(expected?|projected|forecast\w*|estimated|anticipated)\b.{0,30}\b" + INCOME_WORDS + r"\b"),
    ("fake_urgency", r"\bonly\s+\d+\s+([\w-]+\s+){0,2}(left|remain|remaining)\b|\bcountdown\b|"
                     r"\b(selling out|almost gone|last chance|hurry)\b"),
    ("fake_testimonial", r"[\"“][^\"”\n]{15,200}[\"”]\s*[-—–]\s*[A-Z][a-z]+( [A-Z]\.?)?[,\s]"),
    ("fake_rating", r"\b[45](\.\d)?\s*/\s*5\s*(stars?)?\b|★{3,}|\b\d+\s*(happy|satisfied) (customers|users)\b"),
]

# Claims in agent output are written as "CLAIM: <text> (source: <url>)" or "... (ASSUMPTION ...)".
CLAIM_LINE = re.compile(r"^\s*(?:[-*]\s*)?CLAIM:\s*(.+)$", re.I | re.M)


class Guard:
    def __init__(self, logger: DecisionLogger | None = None):
        self.logger = logger or DecisionLogger()

    def classify(self, text: str) -> tuple[str, str] | None:
        """Return (category, reason) if the text breaks a rule, else None. Does not log."""
        normalized = normalize(text)
        for category, reason, patterns in PRE_RULES:
            if any(re.search(pattern, normalized, F) for pattern in patterns):
                return category, reason
        return None

    def pre_check(self, text: str, *, agent: str = "guard") -> GuardResult:
        hit = self.classify(text)
        if hit is None:
            return GuardResult(True)
        category, reason = hit
        self.logger.log("guard", "refuse_request", category=category,
                        request_excerpt=normalize(text)[:160], for_agent=agent)
        return GuardResult(False, category, reason)

    def post_check(self, text: str, *, agent: str) -> GuardResult:
        """Check an agent output: no income figures, no fabricated social proof, no unsourced claims."""
        problems: list[str] = []
        body = normalize(text)
        for category, pattern in POST_RULES:
            match = re.search(pattern, body, re.S if category == "fake_testimonial" else F)
            if match:
                problems.append(f"{category}: '{match.group(0)[:80]}'")
        for match in CLAIM_LINE.finditer(text):
            claim = match.group(1)
            if not re.search(r"https?://\S+", claim) and "ASSUMPTION" not in claim:
                problems.append(f"unsourced_claim: '{claim[:80]}'")
        if not problems:
            return GuardResult(True)
        self.logger.log("guard", "reject_output", for_agent=agent, problems=problems[:10])
        return GuardResult(False, problems[0].split(":")[0],
                           "Output rejected: " + "; ".join(problems), problems)
