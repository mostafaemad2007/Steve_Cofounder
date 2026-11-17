# VentureGate

**Steve, your honest AI cofounder.** VentureGate is an open-source team of AI agents that takes a founder's idea for a **digital** product through six gated phases (Discover, Validate, Build, Commercial setup, Launch, Operate and learn) and recommends **stop** with evidence when the evidence is weak. Steve runs on a free local open-weight model, cites a real source for every claim or labels it `ASSUMPTION`, and publishes, sends or spends nothing without the founder's approval.

## Quickstart

```bash
docker compose up
```

Then open http://localhost:7860.

On the page, read the short introduction and press **Get started**, describe your idea (or press **Fill in an example idea for me**), then **Start working with Steve**. Steve works with you in a chat: he sends each step's report as a message, and you answer with a button (**Yes, this is right. Continue** or **Stop**) or type what he should change. The whole conversation stays on screen, and every report is also saved in `outputs/`.

The weak example that ends in STOP (12 of 100 [SIMULATED] sign-ups) runs from the terminal: `docker compose run --rm app python -m venturegate run --idea examples/weak_idea.yaml`.

The first start downloads the local model (`qwen3:4b`, about 2.5 GB; no GPU needed). Until it is ready, press **Watch a recorded example** on the first page to replay a recorded real run, clearly labelled `[REPLAY MODE]`.

From a terminal instead: `docker compose run --rm app python -m venturegate run --idea examples/weak_idea.yaml`.
Run the tests: `docker compose run --rm app pytest`.
If Steve does not start, run `docker compose run --rm app python -m venturegate check`: it tests the model, web search and files, and says what to fix.

## What works and what is mocked

| Step | Status |
|---|---|
| Decision log (`decision_log.json`) and evidence ledger | Working |
| Live web search for evidence: Steve plans queries, reads the pages, cites only pages he read | Working |
| Guard: refuses banned requests and unsourced or income-promising output | Working |
| Gates 1-6 with thresholds pre-registered in `gates.yaml` | Working |
| Founder approval enforced in code (web UI + CLI) | Working |
| Model layer: local Ollama, `[REPLAY MODE]` fallback, cost tracking | Working |
| Phase 1-6 agents, the detailed plan, and a working MVP with automatic tests | Working |
| Orchestrator: six phases, founder confirmations after every step, gates, pivot and STOP | Working |
| Founder console (web page on localhost:7860) and command line | Working |
| Red-team report: every trick prompt refused (`outputs/redteam_report.md`) | Working |
| Customer interviews (Mom Test) | **STUBBED** — the system writes the script; the founder runs the interviews and never gets invented answers |
| Waitlist sign-ups, audience preference, support tickets | **MOCKED** — `[SIMULATED]` fixtures in `venturegate/mocks/` |
| Store, sale, delivery, refund, reconciliation | **MOCKED** — no payment provider, no sandbox, no money |
| Amount-level reconciliation (gross, fees, net payout) | **STUBBED** — would come from the founder's own provider, outside this system |
| Publishing launch posts and sending support replies | **MOCKED** — approved by the founder, then recorded; nothing is posted or sent |

## Architecture

An orchestrator runs six phase agents in order. Every founder message and every agent output passes a deterministic Python guard, and each phase ends with a gate whose thresholds are fixed in `gates.yaml` before the run starts and are fingerprinted so they cannot change mid-run. Gates decide by calculation, never by the model's opinion, and return go, repeat, pivot or stop. Any publish, send or spend step raises an exception unless the founder has approved it. Every action is appended to `decision_log.json` and every claim to `evidence_ledger.json`. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Models and free resources

- Default model: `qwen3:4b` (open-weight, Apache-2.0) served by [Ollama](https://ollama.com) and pulled automatically by `docker compose up`.
- Change it in `.env`: `MODEL=qwen3:8b` or `MODEL=gpt-oss:20b` on stronger hardware.
- No paid API, no paid model, no API key.
- Evidence comes from live web search, also free and keyless: DuckDuckGo's plain HTML results page, with Wikipedia's search API as a fallback, or your own [SearXNG](https://github.com/searxng/searxng) instance via `SEARXNG_URL`. Pages saved in `sources/` are used as well, and `WEB_SEARCH=false` runs on saved pages only, with no internet.

## Cost per run

About $0.00 per run (local open-weight model; tokens and elapsed time per run are written to `outputs/cost_report.json`).

## Demo video

To be added after the demo recording.

## What our system will NOT do

- Promise income, or give any income, revenue or profit amount, range or start date — even a simulated one.
- Invent reviews, testimonials, ratings, customer quotes, interview answers, sign-ups, urgency or countdown timers.
- Pose as the founder, a customer, a real person or another brand.
- Touch payments: no payment gateway, no sandbox, no money held, moved or refunded, no card numbers.
- Store passwords, API keys or other credentials, or create accounts.
- Publish, send or spend anything without the founder's explicit approval.
- Change its own gate thresholds during a run.
- Work on physical goods, financial, investment or crypto products, or health or legal advice products.
- Put core features behind a paywall.

## How the project stays alive after the hackathon

- **Maintainers:** the founding team, under MIT so anyone can fork or take over.
- **Roadmap:** see [ARCHITECTURE.md](ARCHITECTURE.md#roadmap) — more languages, optional free-tier hosted models, pluggable phase agents.
- **Community:** agents, prompts and gate thresholds are plain files, so contributors can add a phase or tune a gate without touching the core.
- **Funding:** none needed. It runs at $0 on a local model, so the project has no hosting bill to keep alive.
