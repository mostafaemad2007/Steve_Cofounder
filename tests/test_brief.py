"""Part 7a: the founder brief is validated before any model call."""
import pytest

from venturegate.brief import BriefError, FounderBrief

GOOD = {"run": "strong", "idea": "A bilingual CV template pack for Egyptian fresh graduates.",
        "skills": ["writing", "recruiting"], "budget": 300, "hours_per_week": 10}


def brief(**changes):
    data = {**GOOD, **changes}
    return FounderBrief.from_dict({k: v for k, v in data.items() if v is not ...})


def test_a_complete_brief_loads_with_defaults():
    b = brief()
    assert b.currency == "USD" and b.language == "en" and b.mock_scenario == "strong"
    assert b.target_market is None and b.values == []


@pytest.mark.parametrize("field", ["run", "idea", "budget", "hours_per_week"])
def test_each_required_field_is_required(field):
    with pytest.raises(BriefError, match=field):
        brief(**{field: ...})


@pytest.mark.parametrize("changes, message", [
    ({"budget": -5}, "negative"),
    ({"budget": "lots"}, "number"),
    ({"budget": True}, "number"),
    ({"budget": float("nan")}, "finite"),
    ({"hours_per_week": 200}, "168"),
    ({"idea": "an app"}, "full sentence"),
    ({"idea": "x" * 2100 + " a b c d"}, "2000"),
    ({"language": "fr"}, "language"),
    ({"mock_scenario": "medium"}, "mock_scenario"),
    ({"run": "!!!"}, "letter or digit"),
    ({"skills": 42}, "list"),
])
def test_bad_values_fail_with_a_clear_message(changes, message):
    with pytest.raises(BriefError, match=message):
        brief(**changes)


def test_text_inputs_are_normalised():
    b = brief(run="My Strong Run!", skills="writing, design , ", values="honesty,  care",
              budget="1,500", currency="egp ", target_market="   ", language="AR",
              idea="  A   bilingual CV pack\nfor graduates in Cairo.  ")
    assert b.run == "my-strong-run"
    assert b.skills == ["writing", "design"] and b.values == ["honesty", "care"]
    assert b.budget == 1500 and b.currency == "EGP"
    assert b.target_market is None                 # blank means "ask the founder"
    assert b.language == "ar" and b.language_name == "Arabic"
    assert b.idea == "A bilingual CV pack for graduates in Cairo."


def test_zero_budget_is_allowed_and_handled_later_by_the_gate():
    assert brief(budget=0).budget == 0


def test_as_text_contains_everything_the_agents_need():
    text = brief(target_market="Egypt", values=["honesty"]).as_text()
    for part in ("Idea:", "300 USD", "10 hours", "Egypt", "honesty", "English"):
        assert part in text


def test_load_reports_missing_and_invalid_files(tmp_path):
    with pytest.raises(BriefError, match="no brief"):
        FounderBrief.load(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("idea: [unclosed", encoding="utf-8")
    with pytest.raises(BriefError, match="not valid YAML"):
        FounderBrief.load(bad)
    listy = tmp_path / "list.yaml"
    listy.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(BriefError, match="mapping"):
        FounderBrief.load(listy)


def test_skills_are_optional_because_steve_works_them_out():
    data = dict(GOOD); data.pop("skills")
    b = FounderBrief.from_dict(data)
    assert b.skills == [] and "Founder skills" not in b.as_text()
