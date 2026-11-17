"""Part 0: the repository has the files, layout and safety properties TEAM_CLAUDE.md requires."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = ("README.md", "LICENSE", "docker-compose.yml", "Dockerfile", "decision_log.json",
                  "ARCHITECTURE.md", ".env.example", ".gitignore", "gates.yaml", "requirements.txt")
REQUIRED_DIRS = ("outputs", "tests", "prompts", "sources", "examples", "venturegate")


def test_required_files_exist():
    missing = [n for n in REQUIRED_FILES if not (ROOT / n).is_file()]
    assert not missing, f"missing files: {missing}"


def test_required_directories_exist():
    missing = [n for n in REQUIRED_DIRS if not (ROOT / n).is_dir()]
    assert not missing, f"missing directories: {missing}"


def test_license_is_the_full_unmodified_mit_text():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    for phrase in ("Permission is hereby granted, free of charge",
                   "The above copyright notice and this permission notice shall be included",
                   'THE SOFTWARE IS PROVIDED "AS IS"', "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT"):
        assert phrase in text, f"LICENSE is missing: {phrase}"


def test_compose_starts_app_and_local_model():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert {"app", "ollama", "model-pull"} <= set(services)
    assert "7860:7860" in services["app"]["ports"]
    assert "ollama pull" in " ".join(services["model-pull"]["entrypoint"])


def test_env_example_holds_placeholders_only():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert not re.search(r"(sk-|sk_live|pk_live|ghp_|AIza)[A-Za-z0-9_-]{8,}", text), "looks like a real key"
    assert "API_KEY=" not in text.upper().replace("# ", ""), "no API key should be needed"


def test_gitignore_excludes_secrets_and_model_weights():
    lines = {l.strip() for l in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    for pattern in (".env", "*.gguf", "__pycache__/"):
        assert pattern in lines, f".gitignore missing {pattern}"


def test_gates_yaml_has_all_six_gates_with_the_documented_numbers():
    gates = yaml.safe_load((ROOT / "gates.yaml").read_text(encoding="utf-8"))
    assert [k.split("_")[0] for k in gates] == ["G1", "G2", "G3", "G4", "G5", "G6"]
    assert gates["G2_validate"]["signup_target"] == 100
    assert gates["G2_validate"]["window_days"] == 14
    assert gates["G1_discover"]["min_sourced_claims"] == 5
    assert gates["G4_commercial"]["draft_label"] == "DRAFT - not legal advice"


def test_architecture_headings_exact_and_in_order():
    text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert re.findall(r"^## (.+)$", text, re.M) == [
        "Overview", "Phases", "Gates", "Sale to cash", "Data flow", "Built vs. stubbed", "Roadmap"]


def test_architecture_uses_text_diagrams_and_covers_six_phases_and_stop():
    text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "```mermaid" in text, "diagrams must be Mermaid or ASCII, never images"
    assert len(re.findall(r"^### Phase \d", text, re.M)) == 6
    assert "STOP" in text
    sale = text.split("## Sale to cash", 1)[1].split("\n## ", 1)[0].lower()
    for required in ("delivery", "refund", "idempot", "reconcil"):
        assert required in sale, f"'Sale to cash' must cover {required}"


def test_no_images_or_binaries_committed_in_docs():
    bad = [p.name for p in ROOT.rglob("*")
           if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz")
           and ".git" not in p.parts]
    assert not bad, f"TEAM_CLAUDE.md: images, PDFs and archives are not read: {bad}"


def test_organiser_files_are_not_inside_docs():
    assert not (ROOT / "docs" / "CLAUDE.md").exists(), "CLAUDE.md belongs at the root, not in docs/"


def test_architecture_details_every_core_step():
    text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    phases = text.split("## Phases", 1)[1].split("\n## ", 1)[0].lower()
    for core in ("find opportunities", "design the business", "build the product",
                 "set the price and policies", "open the store", "deliver automatically"):
        assert f"core step: {core}" in phases or f"core steps: {core}" in phases or core in phases, core
    for agent in ("discover", "validate", "build", "commercial", "launch", "operate"):
        assert f"`{agent}`" in phases, f"agent {agent} not described"


def test_every_agent_has_a_prompt_file():
    for name in ("discover", "validate", "build", "commercial", "launch", "operate", "shared_rules"):
        assert (ROOT / "prompts" / f"{name}.md").is_file(), name


def test_organiser_conventions_are_at_the_root():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("# CLAUDE.md: hackathon submission conventions")
    assert "## Before every push" in text
