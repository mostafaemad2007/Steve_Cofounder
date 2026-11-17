"""HTML for the founder console, following the design on the canvas.

Pure functions from pipeline events to HTML, so the page can be tested without a browser. Every piece
of text that came from the model, a source or the founder is escaped before it is placed in the page.
"""
import html
import math
import re
from pathlib import Path

from .events import Done, Request, Say

PHASES = [(1, "Discover", "Find opportunities"), (2, "Validate", "Design the business"),
          (3, "Build", "Build the product"), (4, "Commercial setup", "Set the price and policies"),
          (5, "Launch", "Open the store, deliver"), (6, "Operate and learn", "Persevere, pivot or stop")]
PHASE_NAMES = {n: (name, core) for n, name, core in PHASES}
OUTCOME_LABEL = {"go": "GO", "repeat": "REPEAT", "pivot": "PIVOT", "stop": "STOP"}

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:'
         'wght@500;600&family=Pixelify+Sans:wght@500;600;700&display=swap" rel="stylesheet">')
# Keeps the conversation scrolled to the newest message as Steve adds steps.
AUTOSCROLL = """<script>
(function () {
  var last = 0;
  new MutationObserver(function () {
    var box = document.getElementById("vg-timeline");
    if (!box) return;
    var size = box.scrollHeight;
    if (size !== last) { last = size; box.scrollTop = size; }
  }).observe(document.documentElement, {childList: true, subtree: true});
})();
</script>"""
HEAD = FONTS + AUTOSCROLL

CSS = """
:root{--vg-ink:#1E1A15;--vg-muted:#5A5248;--vg-line:#CDC4B6;--vg-soft-line:#E2DBCF;--vg-ground:#EFEBE3;
--vg-surface:#FFFDF8;--vg-sand:#F5F1EA;--vg-soil:#2B2117;--vg-grass:#3E7A28;--vg-grass-dark:#2F5F1E;
--vg-teal:#1C6E80;--vg-teal-dark:#145A69;--vg-teal-soft:#E1F2F5;--vg-stop:#B23A16;--vg-stop-dark:#8E2C10;
--vg-stop-soft:#F9E3DA;--vg-gold-soft:#FBF0D2;--vg-gold-ink:#7A5208;--vg-violet-soft:#EFE7FB;--vg-violet-ink:#5E3A99}
body,.gradio-container{background:var(--vg-ground)!important;color:var(--vg-ink);font-family:Inter,system-ui,sans-serif!important;font-size:14px}
.gradio-container{max-width:none!important;padding:0!important;margin:0!important}
.gradio-container main.app,.gradio-container .main{padding:0!important;max-width:none!important}
.gradio-container .contain > .column{gap:0!important}
footer{display:none!important}
.vg h1,.vg h2,.vg h3{font-family:"Pixelify Sans",Inter,sans-serif;font-weight:600;margin:0;letter-spacing:.01em;color:var(--vg-ink)}
.vg p{margin:0}
.vg a{color:var(--vg-teal)} .vg a:hover{color:var(--vg-teal-dark)}
.vg-card{background:var(--vg-surface);border:2px solid var(--vg-line);border-radius:4px;box-shadow:0 3px 0 #D8CFC0}
.vg-label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--vg-muted)}
.vg-tag{display:inline-flex;align-items:center;gap:4px;font-family:"JetBrains Mono",monospace;font-size:11px;font-weight:600;
padding:1px 7px;border-radius:3px;white-space:nowrap;border:1px solid transparent}
.vg-tag.sim{background:var(--vg-violet-soft);color:var(--vg-violet-ink);border-color:#D9C8F2}
.vg-tag.src,.vg-tag.go{background:var(--vg-teal-soft);color:var(--vg-teal-dark);border-color:#BCE0E7}
.vg-tag.asm{background:#EEEAE3;color:#4A433A;border-color:#DCD5C9}
.vg-tag.stop{background:var(--vg-stop-soft);color:var(--vg-stop-dark);border-color:#EFC2B1}
.vg-tag.pivot,.vg-tag.repeat{background:var(--vg-gold-soft);color:var(--vg-gold-ink);border-color:#EED9A0}
.vg-file{display:inline-flex;align-items:center;gap:6px;font-family:"JetBrains Mono",monospace;font-size:12px;color:var(--vg-soil)!important;
background:var(--vg-sand);border:1px solid #DCD5C9;border-radius:3px;padding:4px 8px;text-decoration:none;word-break:break-all}
.vg-file:hover{border-color:#8C8379}
.vg-header{background:var(--vg-soil);color:#FFFDF8;min-height:56px;padding:0 20px;display:flex;flex-wrap:wrap;align-items:center;gap:8px 20px}
.vg-grass{height:6px;background:repeating-linear-gradient(90deg,#5B9A36 0 12px,#4A8A2C 12px 18px,#6BAA40 18px 24px);border-bottom:3px solid #7A5534}
.vg-brand{display:flex;align-items:center;gap:10px;color:#FFFDF8!important}
.vg-brand b{font-family:"Pixelify Sans",sans-serif;font-size:21px;font-weight:700;letter-spacing:.02em;color:#FFFDF8!important;display:block;line-height:1.1}
.vg-brand small{font-size:12px;color:#D9CFBF;display:block}
.vg-run{font-size:13px;color:#D9CFBF;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;max-width:46vw}
.vg-run strong{color:#FFFDF8}
.vg-pill{display:inline-flex;align-items:center;gap:8px;font-size:12px;background:#3A2D20;border:1px solid #5A4733;padding:5px 11px;
border-radius:4px;color:#FFFDF8;white-space:nowrap}
.vg-dot{width:8px;height:8px;display:inline-block}
.vg-steve{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--vg-muted)} .vg-steve b{color:var(--vg-soil)}
.vg-rail ol{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px}
.vg-rail li{display:flex;align-items:center;gap:10px;padding:8px;border-radius:4px;color:var(--vg-muted)}
.vg-rail li strong{display:block;font-size:13px;color:var(--vg-soil)}
.vg-rail li small{display:block;font-size:12px}
.vg-rail .num{width:26px;height:26px;flex:none;display:inline-flex;align-items:center;justify-content:center;
font:600 13px "Pixelify Sans",sans-serif;border:2px solid var(--vg-line);background:var(--vg-sand);color:var(--vg-muted)}
.vg-rail li.active{background:#E8F1E1} .vg-rail li.active small{color:var(--vg-grass-dark);font-weight:600}
.vg-rail li.active .num{background:var(--vg-grass);border-color:var(--vg-grass-dark);color:#fff}
.vg-rail li.done .num{background:var(--vg-teal);border-color:var(--vg-teal-dark);color:#fff} .vg-rail li.done small{color:var(--vg-teal-dark)}
.vg-rail li.stop{background:var(--vg-stop-soft)} .vg-rail li.stop .num{background:var(--vg-stop);border-color:var(--vg-stop-dark);color:#fff}
.vg-rail li.stop small{color:var(--vg-stop-dark);font-weight:700}
.vg-rail li.pivot{background:var(--vg-gold-soft)} .vg-rail li.pivot small{color:var(--vg-gold-ink);font-weight:600}
.vg-rail li.skipped .num{border-style:dashed;background:transparent}
.vg-timeline{display:flex;flex-direction:column;gap:12px;padding-right:4px}
.vg-phase{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;margin-top:4px}
.vg-phase h1{font-size:23px}
.vg-step{padding:12px 14px;display:flex;flex-direction:column;gap:6px}
.vg-step.current{border-color:var(--vg-grass);box-shadow:0 3px 0 var(--vg-grass-dark);padding:14px 16px;gap:10px}
.vg-step-head{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.vg-step-head h2{font-size:15px}
.vg-step.current .vg-step-head h2{font-size:18px}
.vg-files{display:flex;flex-wrap:wrap;gap:6px}
.vg-line{font-size:13px;color:#4A433A;padding:2px 4px}
.vg-line.refusal{color:var(--vg-stop-dark)} .vg-line.notice{color:var(--vg-gold-ink)}
.vg-gate{padding:12px 14px;display:flex;flex-direction:column;gap:8px}
.vg-gate.go{border-color:#BCE0E7}
.vg-gate.pivot,.vg-gate.repeat{border-color:#E5C46B;box-shadow:0 3px 0 #C9A44A}
.vg-gate.stop{border-color:var(--vg-stop);box-shadow:0 4px 0 var(--vg-stop-dark);padding:20px 22px;gap:14px}
.vg-stamp{font:700 15px "Pixelify Sans",sans-serif;letter-spacing:.1em;color:#fff;background:var(--vg-stop);border:2px solid var(--vg-stop-dark);padding:3px 14px}
.vg-meter{display:grid;grid-template-columns:repeat(20,minmax(0,1fr));gap:3px}
.vg-meter span{height:14px;background:var(--vg-soft-line)}
.vg-meter span.fill{background:var(--vg-stop)}
.vg-meter span.mark{box-shadow:3px 0 0 var(--vg-soil)}
.vg-blocks{display:grid;gap:4px}
.vg-blocks span{height:12px;background:var(--vg-soft-line)} .vg-blocks span.fill{background:var(--vg-teal)}
.vg-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.vg-stat{background:var(--vg-sand);border:2px solid var(--vg-soft-line);border-radius:4px;padding:8px 10px;font-size:12px}
.vg-stat b{display:block;font:600 17px "Pixelify Sans",sans-serif}
.vg-done{padding:14px 16px;display:flex;flex-direction:column;gap:6px}
.vg-done.completed{background:var(--vg-teal-soft);border-color:#BCE0E7}
.vg-done.stopped,.vg-done.refused,.vg-done.error{background:var(--vg-stop-soft);border-color:#EFC2B1}
.vg-side{padding:14px;display:flex;flex-direction:column;gap:10px}
.vg-claim{display:flex;flex-direction:column;gap:4px;font-size:13px;border-top:1px solid var(--vg-soft-line);padding-top:8px}
.vg-claim:first-of-type{border-top:0;padding-top:0}
.vg-decision-head{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
.vg-decision-head h2{font-size:16px}
.vg-alert{background:var(--vg-gold-soft);color:var(--vg-gold-ink);border:2px solid #EED9A0;border-radius:4px;padding:8px 12px;font-size:13px;margin:10px 20px 0}
.vg-message:empty{display:none}
/* laptop layout: the three columns and the conversation scroll inside one screen */
#vg-main{padding:14px 20px 0!important;gap:16px!important;align-items:stretch!important;flex-wrap:nowrap!important}
#vg-left,#vg-right{height:calc(100vh - 92px);overflow-y:auto;padding-bottom:14px;flex:0 0 auto!important}
#vg-left{width:232px!important;min-width:232px!important;max-width:232px!important}
#vg-right{width:284px!important;min-width:284px!important;max-width:284px!important}
#vg-center{height:calc(100vh - 92px);display:flex!important;flex-direction:column!important;flex:1 1 auto!important;min-width:0!important}
#vg-start{overflow-y:auto;background:var(--vg-surface);border:2px solid var(--vg-line)!important;border-radius:4px!important;
box-shadow:0 3px 0 #D8CFC0;padding:18px 20px!important;gap:12px!important;margin-bottom:14px}
#vg-run{flex:1 1 auto!important;min-height:0!important;display:flex!important;flex-direction:column!important;gap:10px!important}
#vg-timeline{flex:1 1 auto!important;min-height:0!important;overflow-y:auto!important}
#vg-dock{flex:none!important;background:var(--vg-surface);border:2px solid var(--vg-soil)!important;border-radius:4px!important;
box-shadow:0 4px 0 var(--vg-soil);padding:12px 14px!important;gap:8px!important;margin-bottom:14px}
#vg-new{flex:none!important;margin-bottom:14px}
.vg-btn-primary{background:var(--vg-grass)!important;color:#fff!important;border:2px solid var(--vg-grass-dark)!important;border-radius:4px!important;
box-shadow:0 3px 0 var(--vg-grass-dark)!important;min-height:44px;font-weight:600!important;white-space:nowrap}
.vg-btn-secondary{background:var(--vg-surface)!important;color:var(--vg-ink)!important;border:2px solid #B9AF9F!important;border-radius:4px!important;
box-shadow:0 3px 0 #D8CFC0!important;min-height:44px;font-weight:600!important}
.vg-btn-quiet{background:transparent!important;color:var(--vg-stop-dark)!important;border:2px solid transparent!important;
min-height:44px;font-weight:600!important;box-shadow:none!important}
.gradio-container input,.gradio-container textarea,.gradio-container select{border-radius:4px!important}
@media (max-width:900px){
 #vg-main{flex-wrap:wrap!important;padding:12px!important}
 #vg-left,#vg-right,#vg-center{height:auto;width:100%!important;max-width:none!important;min-width:0!important;overflow:visible}
 #vg-timeline{overflow:visible!important} .vg-header{padding:10px 14px} .vg-run{max-width:100%;white-space:normal}}
"""

EMBLEM_RECTS = [  # original 16x16 pixel emblem: a stone gate with a gem keystone over grass and soil
    ("#8C8379", [(4, 2, 3, 1), (9, 2, 3, 1), (3, 3, 4, 1), (9, 3, 4, 1), (2, 4, 12, 1)]),
    ("#A69D91", [(2, 5, 3, 9)]), ("#7A7268", [(11, 5, 3, 9)]),
    ("#3BC0C8", [(7, 2, 2, 2)]), ("#CFF5F5", [(7, 2, 1, 1)]),
    ("#1B140D", [(5, 5, 6, 9)]),
    ("#5B9A36", [(1, 14, 14, 1)]), ("#7A5534", [(1, 15, 14, 1)]),
]


def emblem(size: int = 28, label: str = "Steve") -> str:
    """Steve's emblem: an original pixel-art gate. Not any existing character."""
    rects = "".join(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}"></rect>'
                    for c, items in EMBLEM_RECTS for x, y, w, h in items)
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 16 16" shape-rendering="crispEdges" role="img" '
            f'aria-label="{label}">{rects}</svg>')


GATE_ICON = ('<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 21V8l8-5 8 5v13"></path>'
             '<path d="M9 21v-7h6v7"></path></svg>')
CHECK = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#1C6E80" stroke-width="2.6" '
         'stroke-linecap="square" role="img" aria-label="Done"><path d="M20 6 9 17l-5-5"></path></svg>')


def e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def file_url(path: str) -> str:
    return "/gradio_api/file=" + html.escape(str(Path(path).resolve()), quote=True)


def files_html(paths) -> str:
    chips = [f'<a class="vg-file" href="{file_url(p)}" target="_blank" rel="noopener">{e(Path(p).name)}</a>'
             for p in paths if p]
    return f'<div class="vg-files">{"".join(chips)}</div>' if chips else ""


# == header and legend ==========================================================
def header_html(*, model: str, mode: str, ready: bool, run: str | None = None, idea: str | None = None,
                cost: float = 0.0, finished: bool = False) -> str:
    if mode == "replay":
        status, dot = f"{e(model)} · [REPLAY MODE]", "#C4B5FD"
    elif ready:
        status, dot = f"{e(model)} · live · on this laptop", "#6BAA40"
    else:
        status, dot = f"{e(model)} · not reachable yet", "#E0B03A"
    run_text = (f'Run <strong>{e(run)}</strong>{" · " + e(_short(idea, 70)) if idea else ""}' if run
                else "Ready for a new idea")
    cost_pill = (f'<span class="vg-pill" style="font-family:\'JetBrains Mono\',monospace">${cost:.2f}'
                 f'{" · run ended" if finished else " so far"}</span>' if run else "")
    return (f'<div class="vg"><div class="vg-header"><div class="vg-brand">{emblem(30)}<div><b>VentureGate</b>'
            f'<small>with Steve, your honest AI cofounder</small></div></div><div class="vg-run">{run_text}</div>'
            f'<div style="flex:1 1 auto"></div><span class="vg-pill"><span class="vg-dot" style="background:{dot}"></span>'
            f'{status}</span>{cost_pill}</div><div class="vg-grass"></div></div>')


def legend_html() -> str:
    return ('<section class="vg vg-card vg-side" style="margin-top:12px"><div class="vg-label">What the labels mean</div>'
            '<div style="display:flex;flex-direction:column;gap:6px;font-size:12px;color:#4A433A">'
            '<span><span class="vg-tag sim">[SIMULATED]</span> prepared fixture, not real data</span>'
            '<span><span class="vg-tag sim">MOCKED</span> nothing leaves this laptop</span>'
            '<span><span class="vg-tag src">SOURCED</span> links to a saved page</span>'
            '<span><span class="vg-tag asm">ASSUMPTION</span> no source behind it</span></div></section>')


# == the phase rail =============================================================
def rail_state(events: list, pending: Request | None, done: Done | None) -> list[dict]:
    """Status of each phase: todo, active, done, stop, pivot or skipped, with a short note."""
    started, gates, current = set(), {}, None
    for ev in events:
        if isinstance(ev, Say) and ev.kind == "phase":
            started.add(ev.phase)
            current = ev.phase
        elif isinstance(ev, Say) and ev.kind == "gate" and ev.phase:
            gates[ev.phase] = ev.outcome
    states = []
    for number, _, core in PHASES:
        outcome = gates.get(number)
        if outcome == "go":
            states.append({"state": "done", "note": f"Gate {number} · GO"})
        elif outcome == "stop":
            states.append({"state": "stop", "note": f"Gate {number} · STOP"})
        elif outcome in ("pivot", "repeat") and number == current and not done:
            states.append({"state": "pivot", "note": f"Gate {number} · {outcome.upper()}"})
        elif number == current and not done:
            states.append({"state": "active", "note": "Waiting for you" if pending else "Working…"})
        elif done and number not in started:
            states.append({"state": "skipped", "note": "Not reached"})
        elif number == current and done:
            states.append({"state": "stop", "note": "Run ended here"})
        else:
            states.append({"state": "todo", "note": core})
    return states


def rail_html(states: list[dict]) -> str:
    items = []
    for (number, name, _), st in zip(PHASES, states):
        mark = "✓" if st["state"] == "done" else ("✕" if st["state"] == "stop" else str(number))
        items.append(f'<li class="{st["state"]}"><span class="num" aria-hidden="true">{mark}</span>'
                     f'<span><strong>{e(name)}</strong><small>{e(st["note"])}</small></span></li>')
    return (f'<nav class="vg vg-card vg-side vg-rail" aria-label="Phases"><div class="vg-label">Six phases, six gates</div>'
            f'<ol>{"".join(items)}</ol></nav>')


def how_steve_works_html() -> str:
    return ('<section class="vg vg-card vg-side" style="margin-top:12px"><div class="vg-label">How Steve works</div>'
            '<p style="font-size:13px;color:#4A433A">Steve checks your idea against saved evidence, asks you before every '
            'step, and recommends stop when the evidence is weak. The gates decide by numbers fixed before the run.</p>'
            '</section>')


def brief_html(brief) -> str:
    if brief is None:
        return ""
    market = brief.target_market or "asked during the run"
    return (f'<section class="vg vg-card vg-side" style="margin-top:12px"><div class="vg-label">Founder brief</div>'
            f'<p style="font-size:13px">{e(brief.idea)}</p>'
            f'<dl style="margin:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;font-size:13px">'
            f'<div><dt style="color:#5A5248">Budget</dt><dd style="margin:0;font-weight:600">{brief.budget:g} {e(brief.currency)}</dd></div>'
            f'<div><dt style="color:#5A5248">Time</dt><dd style="margin:0;font-weight:600">{brief.hours_per_week:g} h / week</dd></div>'
            f'<div style="grid-column:span 2"><dt style="color:#5A5248">Target market</dt><dd style="margin:0;font-weight:600">{e(market)}</dd></div>'
            f'<div style="grid-column:span 2"><dt style="color:#5A5248">Demand data</dt><dd style="margin:0">'
            f'<span class="vg-tag sim">[SIMULATED] {e(brief.mock_scenario)} fixture</span></dd></div></dl></section>')


# == the conversation ===========================================================
def _short(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _tagged(text: str) -> str:
    """Escape, then turn honesty labels into tags."""
    out = e(text)
    for label, cls in (("[SIMULATED]", "sim"), ("MOCKED", "sim"), ("[REPLAY MODE]", "sim"), ("ASSUMPTION", "asm"),
                       ("STUBBED", "asm")):
        out = out.replace(e(label), f'<span class="vg-tag {cls}">{e(label)}</span>')
    return out


def step_html(ev: Say, current: bool) -> str:
    title, _, summary = ev.text.partition(": ")
    if not summary:
        title, summary = "", ev.text
    if current:
        return (f'<article class="vg-card vg-step current"><div class="vg-steve">{emblem(18)}<span><b>Steve</b> · '
                f'waiting for your decision</span></div><div class="vg-step-head"><h2>{e(title)}</h2></div>'
                f'<p>{_tagged(summary)}</p>{files_html(ev.files)}</article>')
    return (f'<article class="vg-card vg-step"><div class="vg-step-head">{CHECK}<h2>{e(title)}</h2></div>'
            f'<p style="color:#4A433A">{_tagged(summary)}</p>{files_html(ev.files)}</article>')


def gate_html(ev: Say) -> str:
    outcome = ev.outcome or "go"
    data = ev.data or {}
    name = data.get("name", "")
    title = f"Gate {ev.phase}{' · ' + e(name) if name else ''}"
    reasons = data.get("reasons") or [ev.text]
    if outcome != "stop":
        return (f'<article class="vg-card vg-gate {outcome}"><div class="vg-step-head">'
                f'<span class="vg-tag {outcome}">{OUTCOME_LABEL.get(outcome, outcome.upper())}</span><h2>{title}</h2></div>'
                f'<p style="color:#4A433A">{_tagged(" ".join(reasons))}</p>{files_html(ev.files)}</article>')
    metrics = data.get("metrics", {})
    meter = ""
    count, target = metrics.get("sign-ups [SIMULATED]"), metrics.get("pre-set target")
    if isinstance(count, (int, float)) and isinstance(target, (int, float)) and target:
        meter = meter_html(count, target, _percent(metrics.get("stop below"), 50))
    shown = {"sign-ups [SIMULATED]", "pre-set target", "stop below"} if meter else set()
    stats = "".join(f'<div class="vg-stat"><span class="vg-label">{e(k)}</span><b>{e(v)}</b></div>'
                    for k, v in list(metrics.items())[:8] if not isinstance(v, bool) and k not in shown)
    change = "".join(f"<li>{e(item)}</li>" for item in data.get("what_would_change", []))
    return (f'<article class="vg-card vg-gate stop"><div class="vg-step-head"><span class="vg-stamp">STOP</span>'
            f'<h2 style="font-size:21px">{title}</h2></div>'
            f'<div class="vg-steve">{emblem(20)}<span><b>Steve:</b> I would rather tell you now than after you have '
            f'spent the budget.</span></div>'
            f'<p style="font-size:16px;line-height:1.5">{_tagged(" ".join(reasons))}</p>{meter}'
            f'<div class="vg-stats">{stats}</div>'
            + (f'<div><h3 style="font-size:15px;margin-bottom:4px">What would change this decision</h3>'
               f'<ul style="margin:0;padding-left:18px">{change}</ul></div>' if change else "")
            + f'<div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;border-top:2px solid #E2DBCF;'
            f'padding-top:12px">{files_html(ev.files)}<span style="font-size:12px;color:#5A5248">The threshold was '
            f'fixed in gates.yaml before the run. It cannot be lowered.</span></div></article>')


def meter_html(count: float, target: float, stop_percent: float, cells: int = 20) -> str:
    """A block meter: filled blocks for the count, a dark edge where the stop line is."""
    share = max(0.0, min(count / target, 1.0))
    filled = min(cells, math.ceil(share * cells)) if count > 0 else 0
    stop_cell = max(1, min(cells, round(stop_percent / 100 * cells)))
    blocks = "".join(f'<span class="{" ".join(c for c in ("fill" if i < filled else "", "mark" if i == stop_cell - 1 else "") if c)}">'
                     f'</span>' for i in range(cells))
    return (f'<div style="display:flex;flex-direction:column;gap:6px"><div style="display:flex;justify-content:space-between;'
            f'font-size:12px;color:#4A433A"><span><strong style="font:700 20px Pixelify Sans,sans-serif;color:#8E2C10">'
            f'{count:g}</strong> sign-ups <span class="vg-tag sim">[SIMULATED]</span></span><span>target <strong>{target:g}'
            f'</strong></span></div><div class="vg-meter" role="img" aria-label="{count:g} of {target:g}; stop line at '
            f'{stop_percent:g}%">{blocks}</div><div style="text-align:center;font-size:12px;color:#4A433A">stop line at '
            f'{stop_percent:g}% of target</div></div>')


def _percent(value, default):
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*%?\s*$", str(value or ""))
    return float(match.group(1)) if match else default


def done_html(done: Done) -> str:
    titles = {"completed": "Run complete: Steve went through all six phases with you", "stopped": "The run ended with a STOP",
              "stopped_by_founder": "You stopped the run", "refused": "Refused", "error": "The run could not continue"}
    cls = "completed" if done.outcome == "completed" else ("stopped" if done.outcome != "error" else "error")
    if done.outcome == "stopped" and done.last_gate:
        # the gate card above already gives the reasons; don't repeat them
        summary = (f"The recommendation is STOP at Gate {done.last_gate.lstrip('G')}. Start a new brief, or revise "
                   "the idea with what would change the decision and run it again.")
    else:
        summary = done.summary
    return (f'<section class="vg-card vg-done {cls}"><h2 style="font-size:18px">{e(titles.get(done.outcome, done.outcome))}</h2>'
            f'<p>{_tagged(summary)}</p><p style="font-size:13px;color:#5A5248">Every action is in decision_log.json, '
            f'every claim in evidence_ledger.json, the cost in cost_report.json.</p></section>')


def timeline_html(events: list, pending: Request | None, done: Done | None) -> str:
    parts, last_step = [], None
    for index, ev in enumerate(events):
        if isinstance(ev, Say) and ev.kind == "step":
            last_step = index
    current_step = last_step if pending is not None and pending.kind == "confirm" else None
    for index, ev in enumerate(events):
        if not isinstance(ev, Say):
            continue
        if ev.kind == "phase":
            name, core = PHASE_NAMES.get(ev.phase, (ev.text, ""))
            parts.append(f'<div class="vg-phase"><h1>Phase {ev.phase} · {e(name)}</h1>'
                         f'<span style="font-size:14px;color:#5A5248">{e(core)}</span></div>')
        elif ev.kind == "step":
            parts.append(step_html(ev, index == current_step))
        elif ev.kind == "gate":
            parts.append(gate_html(ev))
        elif ev.kind == "done":
            continue
        else:
            parts.append(f'<div class="vg-line {e(ev.kind)}">{_tagged(ev.text)}{files_html(ev.files)}</div>')
    if done is not None:
        parts.append(done_html(done))
    return f'<div class="vg vg-timeline" aria-live="polite">{"".join(parts)}</div>'


# == the decision panel =========================================================
KIND_TAGS = {"publish": '<span class="vg-tag sim">MOCKED</span>', "send": '<span class="vg-tag sim">MOCKED</span>'}


def decision_controls(request: Request | None) -> dict:
    """Labels and visibility for the decision panel, by request kind."""
    if request is None:
        return {"visible": False}
    pivot = request.step_id.endswith("_pivot")
    if request.kind == "question":
        return {"visible": True, "primary": "Send answer", "secondary": None, "quiet": None,
                "text_label": "Your answer", "text_visible": True}
    if request.kind == "confirm":
        return {"visible": True, "primary": "Approve and continue", "secondary": "Request changes",
                "quiet": "Stop the run", "text_label": "What should change? (needed for “Request changes”)",
                "text_visible": True}
    if request.kind == "gate" and pivot:
        return {"visible": True, "primary": "Pivot with this idea", "secondary": None, "quiet": "Stop here",
                "text_label": "Your revised idea, in one full sentence", "text_visible": True}
    if request.kind == "gate":
        return {"visible": True, "primary": "Continue", "secondary": None, "quiet": "Stop the run",
                "text_label": "", "text_visible": False}
    return {"visible": True, "primary": "Approve (MOCKED)", "secondary": None,
            "quiet": "Don't approve", "text_label": "", "text_visible": False}


def decision_html(request: Request | None) -> str:
    if request is None:
        return ""
    return (f'<div class="vg"><div class="vg-decision-head">{emblem(20)}<h2>Steve is waiting for your decision</h2>'
            f'{KIND_TAGS.get(request.kind, "")}<span style="font-size:12px;color:#5A5248">Nothing continues until you '
            f'choose</span></div><p style="margin-top:6px">{_tagged(request.prompt)}</p>{files_html(request.files)}</div>')


# == the evidence panel =========================================================
def evidence_html(records: list[dict], min_sourced: int, sources_loaded: int) -> str:
    sourced = len({(r["claim"].lower(), r["source_url"]) for r in records if r.get("source_url")})
    assumptions = sum(1 for r in records if not r.get("source_url"))
    cells = max(min_sourced, 1)
    blocks = "".join(f'<span class="{"fill" if i < min(sourced, cells) else ""}"></span>' for i in range(cells))
    claims = []
    for r in list(reversed(records))[:6]:
        if r.get("source_url"):
            domain = re.sub(r"^https?://(www\.)?", "", r["source_url"]).split("/")[0]
            tag = (f'<span><span class="vg-tag src">SOURCED</span> <a href="{e(r["source_url"])}" target="_blank" '
                   f'rel="noopener" style="font-size:12px">{e(domain)}</a></span>')
        else:
            tag = f'<span><span class="vg-tag asm">ASSUMPTION · {e(r.get("confidence", "low"))}</span></span>'
        claims.append(f'<div class="vg-claim"><span>{e(_short(r["claim"], 140))}</span>{tag}</div>')
    claims_html = "".join(claims) or '<p style="font-size:13px;color:#5A5248">No claims yet.</p>'
    return (f'<section class="vg vg-card vg-side"><div class="vg-label">Gate 1 · evidence</div>'
            f'<div style="display:flex;align-items:baseline;gap:6px"><span style="font:700 30px Pixelify Sans,sans-serif">'
            f'{sourced}</span><span style="color:#5A5248">of {min_sourced} sourced claims needed</span></div>'
            f'<div class="vg-blocks" style="grid-template-columns:repeat({cells},minmax(0,1fr))" role="img" '
            f'aria-label="{sourced} of {min_sourced} sourced claims">{blocks}</div>'
            f'<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px">'
            f'<div class="vg-stat"><b>{sourced}</b>sourced</div><div class="vg-stat"><b>{assumptions}</b>assumptions</div></div>'
            f'<p style="font-size:12px;color:#5A5248">{sources_loaded} page(s) saved in sources/</p></section>'
            f'<section class="vg vg-card vg-side" style="margin-top:12px"><div class="vg-label">Latest claims</div>{claims_html}</section>')


def records_html(paths: list[str]) -> str:
    return (f'<section class="vg vg-card vg-side" style="margin-top:12px"><div class="vg-label">Files from this run</div>'
            f'{files_html(paths) or "<p style=font-size:13px;color:#5A5248>Files appear here as each step finishes.</p>"}'
            f'</section>')


# == the start screen side panel ================================================
def start_side_html(*, model: str, ready: bool, recorded: int, sources_loaded: int, thresholds: dict) -> str:
    def row(ok, title, text):
        icon = CHECK if ok else ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#7A5208" stroke-width="2.2" '
                                 'stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="Needs attention">'
                                 '<path d="M12 8v5"></path><path d="M12 16h.01"></path><circle cx="12" cy="12" r="9"></circle></svg>')
        return f'<div style="display:flex;gap:12px;align-items:flex-start">{icon}<div style="font-size:14px"><strong>{title}</strong><br><span style="color:#5A5248">{text}</span></div></div>'
    g1, g2 = thresholds["G1_discover"], thresholds["G2_validate"]
    model_row = row(ready, "Local model ready" if ready else "Local model not reachable yet",
                    f"{e(model)} runs on this laptop. Cost: $0.00." if ready else
                    f"It may still be downloading. {recorded} recorded step(s) are available to replay.")
    source_row = row(sources_loaded >= g1["min_sourced_claims"], f"{sources_loaded} evidence page(s) saved",
                     f"Gate 1 needs {g1['min_sourced_claims']} claims backed by them. Add pages to <code>sources/</code>.")
    return (f'<section class="vg vg-card vg-side"><div class="vg-label">Before you start</div>{model_row}{source_row}</section>'
            '<section class="vg vg-card vg-side" style="margin-top:12px"><div class="vg-label">Steve will not</div>'
            '<ul style="margin:0;padding-left:18px;font-size:14px;display:flex;flex-direction:column;gap:6px">'
            '<li>Promise or estimate income</li><li>Write reviews, testimonials or sign-ups</li>'
            '<li>Touch payments, even in a sandbox</li><li>Publish or send without your approval</li>'
            '<li>Change his own gate thresholds</li><li>Work on physical, financial, crypto, health or legal products</li></ul></section>'
            f'<section class="vg vg-card vg-side" style="margin-top:12px"><div class="vg-label">Gate thresholds · gates.yaml</div>'
            f'<p style="font-size:13px;color:#5A5248">Fixed in <code>gates.yaml</code> before the run.</p>'
            f'<dl style="margin:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 12px;font-size:13px">'
            f'<dt style="color:#5A5248">Sourced claims</dt><dd style="margin:0;font-weight:600">{g1["min_sourced_claims"]} or more</dd>'
            f'<dt style="color:#5A5248">Sign-up target</dt><dd style="margin:0;font-weight:600">{g2["signup_target"]} in {g2["window_days"]} days</dd>'
            f'<dt style="color:#5A5248">Stop below</dt><dd style="margin:0;font-weight:600">{g2["stop_below_ratio"]:.0%} of target</dd>'
            f'<dt style="color:#5A5248">Budget covers</dt><dd style="margin:0;font-weight:600">{g1["min_runway_months"]:g} months of costs</dd></dl></section>')


def alert_html(text: str | None) -> str:
    return f'<div class="vg vg-alert" role="alert">{e(text)}</div>' if text else ""
