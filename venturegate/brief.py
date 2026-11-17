"""The founder brief: a starting idea plus skills, budget, time, target market, values and language.

Validated on load so a bad brief fails with a clear message before any model call, rather than
halfway through a phase.
"""
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

LANGUAGES = {"en": "English", "ar": "Arabic"}
SCENARIOS = ("weak", "strong")


class BriefError(ValueError):
    """Raised when a founder brief is incomplete or malformed."""


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    raise BriefError("skills and values must be a list or a comma-separated text")


def _as_number(value, name: str) -> float:
    if isinstance(value, bool):
        raise BriefError(f"{name} must be a number")
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise BriefError(f"{name} must be a number, got {value!r}") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise BriefError(f"{name} must be a finite number")
    if number < 0:
        raise BriefError(f"{name} cannot be negative")
    return number


@dataclass
class FounderBrief:
    run: str                       # short label used in output file names, e.g. "weak" or "strong"
    idea: str
    skills: list[str]
    budget: float                  # total money the founder can put in, in `currency`
    hours_per_week: float
    currency: str = "USD"
    target_market: str | None = None
    values: list[str] = field(default_factory=list)
    language: str = "en"
    # Which [SIMULATED] demand fixture in venturegate/mocks/ this run uses. It is a prepared
    # scenario, stated openly in every output that uses it, never a prediction.
    mock_scenario: str = "strong"

    @classmethod
    def from_dict(cls, data: dict) -> "FounderBrief":
        if not isinstance(data, dict):
            raise BriefError("the brief must be a set of fields (a YAML mapping)")
        missing = [k for k in ("run", "idea", "skills", "budget", "hours_per_week")
                   if data.get(k) in (None, "", [])]
        if missing:
            raise BriefError(f"the brief is missing: {', '.join(missing)}")

        run = re.sub(r"[^a-z0-9-]+", "-", str(data["run"]).lower()).strip("-")[:20]
        if not run:
            raise BriefError("run must contain at least one letter or digit")

        idea = " ".join(str(data["idea"]).split())
        if len(idea) < 15 or len(idea.split()) < 4:
            raise BriefError("describe the idea in at least one full sentence")
        if len(idea) > 2000:
            raise BriefError("keep the idea under 2000 characters")

        skills = _as_list(data["skills"])
        if not skills:
            raise BriefError("list at least one skill")

        hours = _as_number(data["hours_per_week"], "hours_per_week")
        if hours > 168:
            raise BriefError("hours_per_week cannot exceed 168")

        language = str(data.get("language") or "en").lower()
        if language not in LANGUAGES:
            raise BriefError(f"language must be one of {sorted(LANGUAGES)}")

        scenario = str(data.get("mock_scenario") or "strong").lower()
        if scenario not in SCENARIOS:
            raise BriefError(f"mock_scenario must be one of {list(SCENARIOS)}")

        currency = re.sub(r"[^A-Za-z]", "", str(data.get("currency") or "USD")).upper()[:5] or "USD"
        target = " ".join(str(data.get("target_market") or "").split()) or None

        return cls(run=run, idea=idea, skills=skills, budget=_as_number(data["budget"], "budget"),
                   hours_per_week=hours, currency=currency, target_market=target,
                   values=_as_list(data.get("values")), language=language, mock_scenario=scenario)

    @classmethod
    def load(cls, path: str | Path) -> "FounderBrief":
        path = Path(path)
        if not path.exists():
            raise BriefError(f"no brief at {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise BriefError(f"{path.name} is not valid YAML: {exc}") from exc
        return cls.from_dict(data)

    @property
    def language_name(self) -> str:
        return LANGUAGES[self.language]

    def as_text(self) -> str:
        """The brief as the agents (and the guard) see it."""
        return "\n".join([
            f"Idea: {self.idea}",
            f"Founder skills: {', '.join(self.skills)}",
            f"Budget: {self.budget:g} {self.currency} in total",
            f"Time: {self.hours_per_week:g} hours per week",
            f"Target market: {self.target_market or 'not given yet'}",
            f"Founder values: {', '.join(self.values) or 'not given'}",
            f"Language for the founder: {self.language_name}",
        ])

    def to_dict(self) -> dict:
        return asdict(self)
