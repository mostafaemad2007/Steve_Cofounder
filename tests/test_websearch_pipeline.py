"""Whole runs where Steve gets his evidence from (simulated) live web search."""
import shutil
from pathlib import Path

from fake_model import FakeModel
from fake_web import FakeWeb
from test_pipeline_smoke import Founder
from venturegate.agents import DiscoverAgent, RunContext
from venturegate.brief import FounderBrief
from venturegate.llm import LLM
from venturegate.logger import DecisionLogger, validate_entry
from venturegate.orchestrator import Pipeline, drive
from venturegate.sources import SourceLibrary
from venturegate.websearch import WebSourceLibrary

ROOT = Path(__file__).resolve().parent.parent


def run(tmp_path, name, web=None, model=None, mode="live"):
    shutil.copy(ROOT / "gates.yaml", tmp_path / "gates.yaml")
    logger = DecisionLogger(tmp_path / "decision_log.json")
    model = model or FakeModel()
    llm = LLM(mode=mode, model="qwen3:4b", logger=logger, replay_dir=tmp_path / "replay", transport=model)
    web = web or FakeWeb()
    library = WebSourceLibrary(mode=mode, logger=logger.for_run(name), cache_dir=tmp_path / "replay" / "search",
                               saved=SourceLibrary(tmp_path / "no-saved-pages"), get=web, searxng_url="")
    brief = FounderBrief.load(ROOT / "examples" / f"{name}_idea.yaml")
    founder = Founder()
    pipeline = Pipeline(brief, llm=llm, logger=logger, sources=library, out_dir=tmp_path / "outputs",
                        state_dir=tmp_path / "state", gates_path=tmp_path / "gates.yaml")
    done = drive(pipeline.run(), founder)
    return done, logger.read(), model, web, pipeline, founder


def test_strong_run_completes_with_evidence_from_web_search(tmp_path):
    done, log, model, web, pipeline, founder = run(tmp_path, "strong")
    assert done.outcome == "completed"
    assert model.calls.count("plan_web_searches") == 1                  # Steve plans his searches once
    searches = [e for e in log if e["action"] == "web_search"]
    assert len(searches) == 5                                           # one per research step
    assert {q for e in searches for q in e["queries"]} >= {"CV templates Egypt graduates", "CV template pack price"}
    for entry in log:
        validate_entry(entry)
    read = {url for e in searches for url in e["sources"]}
    sourced = [r for r in pipeline.ctx.ledger.records() if r["source_url"]]
    assert len({r["claim"] for r in sourced}) >= 5
    assert {r["source_url"] for r in sourced} <= read                  # every citation is a page Steve read
    assert "Steve searches the web" in founder.says[0].text
    assert not [s for s in founder.says if s.kind == "notice" and "sources/" in s.text]


def test_weak_run_still_stops_at_gate_two_with_web_evidence(tmp_path):
    done, log, *_ = run(tmp_path, "weak")
    assert done.outcome == "stopped" and done.last_gate == "G2"


def test_no_internet_ends_honestly_at_gate_one(tmp_path):
    done, log, model, web, pipeline, founder = run(tmp_path, "strong", web=FakeWeb(down=True))
    assert done.outcome == "stopped" and done.last_gate == "G1"
    assert all(r["label"] == "ASSUMPTION" for r in pipeline.ctx.ledger.records())
    assert any("no readable pages" in s.text for s in founder.says if s.kind == "notice")


def test_a_live_run_with_web_search_replays_without_model_or_network(tmp_path):
    run(tmp_path, "strong")
    done, log, model, web, *_ = run(tmp_path, "strong", web=FakeWeb(down=True), mode="replay")
    assert done.outcome == "completed" and model.calls == [] and web.calls == []


def test_a_failed_search_plan_falls_back_to_keywords(tmp_path):
    model = FakeModel({"plan_web_searches": ["not json"] * 3})
    done, log, model, web, *_ = run(tmp_path, "strong", model=model)
    assert done.outcome == "completed"
    queries = [q for e in log if e["action"] == "web_search" for q in e["queries"]]
    assert queries and all(1 <= len(q.split()) <= 8 for q in queries)


def test_planned_queries_are_cleaned(tmp_path):
    messy = {"competitors": ['"cv templates"  egypt', '"CV templates" Egypt'], "market": ["Egypt graduates jobs"],
             "legal": ["licence terms for resume templates and fonts used in the pack today please"],
             "costs": ["hosting price"], "pricing": ["cv pack price"]}
    model = FakeModel({"plan_web_searches": [messy]})
    logger = DecisionLogger(tmp_path / "l.json")
    ctx = RunContext(brief=FounderBrief.load(ROOT / "examples" / "strong_idea.yaml"),
                     llm=LLM(mode="live", logger=logger, replay_dir=tmp_path / "r", transport=model),
                     guard=None, ledger=None, logger=logger, writer=None,
                     sources=WebSourceLibrary(logger=logger, cache_dir=tmp_path / "c", get=FakeWeb(),
                                              saved=SourceLibrary(tmp_path / "none"), searxng_url=""))
    agent = DiscoverAgent(ctx)
    assert agent.research("competitors", "fallback") == ["cv templates egypt"]       # quotes gone, duplicate dropped
    assert len(agent.research("legal", "fallback")[0].split()) == 10                  # capped at 10 words
    assert agent.research("market", "fallback") == ["Egypt graduates jobs"]
    assert model.calls.count("plan_web_searches") == 1                                # planned once, then reused
