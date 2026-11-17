"""The README must carry exactly the eight ## headings TEAM_CLAUDE.md names, word for word, in order.

The organisers' checker matches headings literally, so this test is the first line of defence
against a reworded or reordered heading.
"""
import re
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"

EXPECTED = [
    "Quickstart",
    "What works and what is mocked",
    "Architecture",
    "Models and free resources",
    "Cost per run",
    "Demo video",
    "What our system will NOT do",
    "How the project stays alive after the hackathon",
]


def headings() -> list[str]:
    return re.findall(r"^## (.+)$", README.read_text(encoding="utf-8"), re.M)


def section(name: str) -> str:
    return README.read_text(encoding="utf-8").split(f"## {name}", 1)[1].split("\n## ", 1)[0]


def test_headings_exact_and_in_order():
    assert headings() == EXPECTED


def test_quickstart_has_exact_docker_compose_up_block():
    assert re.search(r"```bash\s*\ndocker compose up\s*\n```", section("Quickstart"))


def test_quickstart_says_how_to_open_the_app():
    assert "localhost:7860" in section("Quickstart")


def test_cost_per_run_has_a_dollar_figure():
    assert re.search(r"\$\s?\d", section("Cost per run"))


def test_mocks_and_stubs_are_labelled_in_the_table():
    body = section("What works and what is mocked")
    assert "MOCKED" in body and "STUBBED" in body and "Working" in body


def test_architecture_section_links_to_architecture_file():
    assert "ARCHITECTURE.md" in section("Architecture")


def test_not_do_section_covers_the_hard_rules():
    body = section("What our system will NOT do").lower()
    for rule in ("income", "payment", "approval", "paywall", "crypto"):
        assert rule in body, f"missing rule: {rule}"
