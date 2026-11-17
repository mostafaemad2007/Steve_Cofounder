"""Command line: python -m venturegate <command>

    serve                 the founder console (web UI) on http://localhost:7860
    run --idea FILE       one run in this terminal; you approve or reject each step as it comes
    demo                  the committed demo: red-team report, then the weak run, then the strong run
    redteam               write outputs/redteam_report.md
    cost                  the "Cost per run" line for the README, from outputs/cost_report.json
    search "QUERY"        try Steve's live web search once and show what he would read
    fetch-source URL      save one public page into sources/ (optional; needs internet)
    check                 test everything Steve needs on this laptop and say what to fix
    status                what the model layer can reach
    pending / approve / reject / mockflow   approvals and the standalone sale-to-cash flow

Nothing here approves anything on the founder's behalf. `run` and `demo` ask you at every step.
"""
import argparse
import json
import sys
from pathlib import Path

from . import config
from .approval import ApprovalRejected, ApprovalRequired, Approvals
from .brief import BriefError, FounderBrief
from .delivery import AccessStore
from .events import Reply, Request, Say
from .llm import LLM
from .logger import DecisionLogger
from .mock_flow import run_mock_flow

EXAMPLES = config.ROOT / "examples"


def console_handler(event):
    """Show events in the terminal and ask the founder for each decision."""
    if isinstance(event, Say):
        marker = {"phase": "\n==", "gate": "  >>", "refusal": "  !!", "notice": "  ..", "done": "\n##"}.get(event.kind, "  -")
        print(f"{marker} {event.text}")
        for f in event.files:
            print(f"       file: {Path(f).name}")
        return None
    assert isinstance(event, Request)
    print(f"\n  ?? {event.prompt}")
    if event.needs_text:
        return Reply(None, input("     your answer> "))
    while True:
        answer = input("     approve? [y/n]> ").strip().lower()
        if answer in ("y", "yes"):
            return Reply(True, "")
        if answer in ("n", "no"):
            return Reply(False, input("     what should change? (leave empty to stop)> "))


def run_brief(path: Path) -> str:
    from .orchestrator import Pipeline, drive
    brief = FounderBrief.load(path)
    done = drive(Pipeline(brief).run(), console_handler)
    return done.outcome


def require_terminal():
    if not sys.stdin.isatty():
        raise SystemExit("This command asks for the founder's decisions, so it needs a terminal.\n"
                         "Use: docker compose run --rm app python -m venturegate run --idea examples/weak_idea.yaml")


def clear_generated_outputs(out_dir: Path) -> None:
    for pattern in ("phase*_step*_*.*", "phase*_gate_*.*", "payment_test_log.md", "redteam_report.md",
                    "cost_report.json", "evidence_ledger.json"):
        for path in out_dir.glob(pattern):
            path.unlink()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="venturegate", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=7860)
    run = sub.add_parser("run")
    run.add_argument("--idea", required=True, help="a founder brief in YAML, e.g. examples/weak_idea.yaml")
    sub.add_parser("demo")
    sub.add_parser("redteam")
    sub.add_parser("cost")
    search = sub.add_parser("search")
    search.add_argument("query")
    fetch = sub.add_parser("fetch-source")
    fetch.add_argument("url")
    sub.add_parser("check")
    sub.add_parser("status")
    sub.add_parser("pending")
    approve = sub.add_parser("approve")
    approve.add_argument("step_id")
    reject = sub.add_parser("reject")
    reject.add_argument("step_id")
    reject.add_argument("--reason", default="")
    sub.add_parser("mockflow")
    args = parser.parse_args(argv)

    if args.command == "serve":
        from .app import launch
        launch(port=args.port)
    elif args.command == "run":
        require_terminal()
        try:
            outcome = run_brief(Path(args.idea))
        except BriefError as exc:
            raise SystemExit(f"The brief could not be used: {exc}")
        print(f"\nOutcome: {outcome}. Files are in outputs/; every action is in decision_log.json.")
    elif args.command == "demo":
        require_terminal()
        out_dir = config.path("OUTPUT_DIR", "outputs")
        print("This rebuilds the committed demo: decision_log.json and the generated files in outputs/ "
              "are cleared, then the red-team report, the weak run and the strong run are produced.")
        if input("Continue? [y/n]> ").strip().lower() not in ("y", "yes"):
            return
        llm = LLM()
        ok, why = llm.model_listed()
        if ok:
            print("Loading Steve's model (up to a couple of minutes the first time)...")
            ok, why, _ = llm.warm_up()
        if not ok:
            raise SystemExit(f"Steve's model is not ready, so nothing was changed.\n{why}\n"
                             "Run `python -m venturegate check` to see everything that needs fixing.")
        DecisionLogger().reset()
        clear_generated_outputs(out_dir)
        from .redteam import run_redteam
        report = run_redteam()
        print(f"Red-team: {report['refused']} of {report['total']} refused.")
        for name in ("weak_idea.yaml", "strong_idea.yaml"):
            print(f"\n######## {name} ########")
            run_brief(EXAMPLES / name)
        print("\n" + cost_line())
    elif args.command == "redteam":
        from .redteam import run_redteam
        report = run_redteam()
        print(f"{report['refused']} of {report['total']} refused. Report: {report['report']}")
    elif args.command == "cost":
        print(cost_line())
    elif args.command == "search":
        import tempfile
        from .websearch import WebSourceLibrary
        scratch = Path(tempfile.mkdtemp())           # a check, not a run: keep it out of decision_log.json
        library = WebSourceLibrary(mode="live", logger=DecisionLogger(scratch / "log.json"), cache_dir=scratch)
        provider, results = library.search(args.query)
        print(f"Search provider: {provider}. {len(results)} result(s).")
        excerpts = library.relevant(args.query)
        for ex in excerpts:
            print(f"\n[{ex.sid}] {ex.source.title}\n     {ex.source.url}\n     {' '.join(ex.text.split())[:200]}...")
        for notice in library.notices:
            print("\nNote:", notice)
        print(f"\n{len(library.pages)} page(s) read. "
              + ("Web search works." if excerpts else "No usable pages: check the internet connection."))
    elif args.command == "fetch-source":
        from .sources import fetch_source
        try:
            print(f"Saved: {fetch_source(args.url)}")
        except Exception as exc:          # network errors, bad pages
            raise SystemExit(f"Could not save {args.url}: {exc}")
    elif args.command == "check":
        raise SystemExit(0 if run_check() else 1)
    elif args.command == "status":
        llm = LLM()
        print(f"model={llm.model}  url={llm.url}  mode={llm.mode}  available={llm.is_available()}  "
              f"recorded_steps={llm.recorded_steps()}")
    elif args.command == "pending":
        items = Approvals().pending()
        print("\n".join(f"{i['step_id']}  [{i['kind']}]  {i['summary']}" for i in items) or "Nothing is waiting.")
    elif args.command == "approve":
        print(json.dumps(Approvals().approve(args.step_id), indent=1))
    elif args.command == "reject":
        print(json.dumps(Approvals().reject(args.step_id, args.reason), indent=1))
    elif args.command == "mockflow":
        logger = DecisionLogger()
        try:
            result = run_mock_flow(approvals=Approvals(logger=logger), store=AccessStore(), logger=logger)
        except (ApprovalRequired, ApprovalRejected) as exc:
            raise SystemExit(f"Refused: {exc}\n\nThe founder has to open the mocked store first:\n"
                             "  python -m venturegate approve phase5_open_store")
        print(json.dumps({k: v for k, v in result.items() if k not in ("steps", "reconciliation")}, indent=1))


def run_check() -> bool:
    """Everything a live run needs, tested in order, each with the fix if it fails."""
    import tempfile
    import time

    from .websearch import WebSourceLibrary
    results = []

    def report(ok, name, detail):
        results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    llm = LLM()
    print(f"Checking Steve on this computer (model {llm.model}, server {llm.url})\n")
    ok, why = llm.model_listed()
    report(ok, "Model server and model download", "ready" if ok else why)
    if ok:
        print("       loading the model and asking a one-word question (can take a minute)...")
        ok, why, seconds = llm.warm_up()
        report(ok, "Model answers", f"answered in {seconds:.0f} s" if ok else why)
        if ok:
            started = time.monotonic()
            try:
                reply = llm.chat_json(agent="check", action="check_json",
                                      prompt="Give one short product idea for students.",
                                      schema={"type": "object", "properties": {"idea": {"type": "string", "minLength": 3}},
                                              "required": ["idea"]})
                report(True, "Model writes structured answers",
                       f"{time.monotonic() - started:.0f} s ({reply['idea'][:60]!r}). Each step of a run takes "
                       "roughly this long, or a few times longer for big steps.")
            except Exception as exc:                         # noqa: BLE001 - report anything
                report(False, "Model writes structured answers", str(exc)[:300])
    scratch = Path(tempfile.mkdtemp())
    if config.get("WEB_SEARCH", "true").lower() in ("0", "false", "no", "off"):
        report(True, "Web search", "switched off (WEB_SEARCH=false): Steve uses pages saved in sources/")
    else:
        library = WebSourceLibrary(logger=DecisionLogger(scratch / "log.json"), cache_dir=scratch)
        provider, found = library.search("CV templates for graduates")
        report(bool(found), "Web search", f"{provider}, {len(found)} result(s)" if found else
               "no results: check the internet connection. Without it, claims become ASSUMPTION and Gate 1 stops.")
    for label, target in (("Decision log", config.path("DECISION_LOG", "decision_log.json")),
                          ("Outputs folder", config.path("OUTPUT_DIR", "outputs") / ".write-test"),
                          ("Replay folder", config.path("REPLAY_DIR", "replay") / ".write-test")):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.name == ".write-test":
                target.write_text("ok", encoding="utf-8")
                target.unlink()
            else:
                with open(target, "a", encoding="utf-8"):
                    pass
            if target.name != ".write-test" and target.exists():
                DecisionLogger(target).read()
            report(True, label, "can be written")
        except Exception as exc:                             # noqa: BLE001
            report(False, label, f"cannot be written ({exc}). If decision_log.json became a folder, delete it "
                                 "and run: git restore decision_log.json")
    passed = all(results)
    print("\n" + ("Everything Steve needs works. You can start a run." if passed else
                  "Fix the FAIL lines above, then run this check again."))
    return passed


def cost_line() -> str:
    path = config.path("OUTPUT_DIR", "outputs") / "cost_report.json"
    if not path.exists():
        return "No cost report yet: run an example first."
    data = json.loads(path.read_text(encoding="utf-8"))
    parts = []
    for name, r in data["runs"].items():
        minutes = r["wall_seconds"] / 60
        parts.append(f"{name}: ${r['cost_usd']:.2f}, ~{r['tokens']:,} tokens, ~{minutes:.0f} min ({r['model']}, {r['mode']})")
    return "About $0.00 per run (local open-weight model). " + "; ".join(parts)


if __name__ == "__main__":
    main()
