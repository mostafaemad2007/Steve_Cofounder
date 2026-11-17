"""The conversation with Steve, as chat messages.

The pipeline still yields Say / Request / Done. This module turns that history, plus what the founder
answered, into chat messages ({"role": "assistant"|"user", "content": markdown}) and decides which
quick-reply buttons to show and what a typed message means at each step. Plain Python, tested without
a browser.
"""
import re
from pathlib import Path

from .events import Done, Reply, Request, Say
from .views import PHASE_NAMES, file_label, file_url

MAX_REPORT_CHARS = 20000
YES = re.compile(r"^(yes|yeah|yep|ok|okay|sure|correct|right|good|great|fine|approve[d]?|continue|go( on| ahead)?|"
                 r"looks (good|right|fine)|that'?s (right|correct)|agreed?|proceed|next|نعم|تمام|موافق|أكمل)\b[.! ]*",
                 re.IGNORECASE)
STOP = re.compile(r"^(stop|no|nope|cancel|quit|end|don'?t|do not|لا|توقف)\b", re.IGNORECASE)

WORKING = ("_Steve is working on this… Thinking and searching the web can take a minute or two on a laptop. "
           "He will message you when he needs you._")


# == what Steve says ============================================================
def _shift_headings(markdown: str) -> str:
    """Report headings become small chat headings (# -> ###)."""
    return re.sub(r"^(#{1,4}) ", lambda m: "#" * min(len(m.group(1)) + 2, 6) + " ", markdown, flags=re.M)


def report_markdown(paths) -> str:
    """The reports themselves, shown in the message; other files as links that open in a new tab."""
    parts = []
    for p in paths or []:
        path = Path(p)
        if path.suffix == ".md" and path.exists():
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            # the chat message already has the title, and the run details are for the saved file
            text = re.sub(r"^> Run: .*\n*", "", text, flags=re.M)
            text = re.sub(r"\A\s*# [^\n]*\n+", "", text)
            if len(text) > MAX_REPORT_CHARS:
                text = text[:MAX_REPORT_CHARS] + "\n\n_(The report is longer; the full file is in the outputs folder.)_"
            parts.append(_shift_headings(text))
        elif path.exists():
            parts.append(f"[Open: {file_label(path.name)}]({file_url(str(path))})")
    return "\n\n---\n\n".join(parts)


def say_message(ev: Say) -> str | None:
    if ev.kind == "phase":
        name, core = PHASE_NAMES.get(ev.phase, ("", ""))
        return f"## Phase {ev.phase} of 6 · {name}\n{core}."
    if ev.kind == "step":
        title, _, summary = ev.text.partition(": ")
        if not summary:
            title, summary = "", ev.text
        report = report_markdown(ev.files)
        head = f"**{title}**\n\n{summary}" if title else summary
        return head + (f"\n\n---\n\n{report}" if report else "")
    if ev.kind == "gate":
        outcome = (ev.outcome or "go").upper()
        meaning = {"GO": "the evidence is good enough to continue.", "STOP": "the evidence says stop.",
                   "PIVOT": "the evidence says change the idea.", "REPEAT": "this phase needs another try."}
        reasons = " ".join((ev.data or {}).get("reasons") or [ev.text])
        report = report_markdown(ev.files)
        return (f"**Check after Phase {ev.phase}: {outcome}**, {meaning.get(outcome, '')}\n\n{reasons}"
                + (f"\n\n---\n\n{report}" if report else ""))
    if ev.kind == "refusal":
        return f"**I can't do that.** {ev.text}"
    if ev.kind == "done":
        return f"**{ev.text}**"
    return ev.text


def request_message(req: Request) -> str:
    prompt = req.prompt
    if req.kind == "confirm":
        title = prompt.split(": is this right?")[0] if ": is this right?" in prompt else ""
        return (f"Does **{title}** look right to you?" if title else prompt) + \
            "\n\nPress **Yes, this is right** to continue, or type what I should change."
    if req.kind == "gate" and req.step_id.endswith("_pivot"):
        return ("My recommendation is to **change the idea** (pivot). Type your new idea in one full sentence and "
                "I will start again from Phase 1 with it. Or press **Stop here**.")
    if req.kind == "gate":
        return prompt.replace("Continue to", "Shall we move on to") + " "
    if req.kind in ("publish", "send", "spend"):
        return (f"{prompt}\n\nThis is **practice only (MOCKED)**: nothing is really published, sent or paid, and "
                "nothing happens unless you approve.")
    return prompt


def stop_message(done: Done, changes: list[str]) -> str:
    """A STOP, said kindly but without softening the decision."""
    text = ("**I'm sorry, but I don't think this idea is ready to build, so I've stopped here.** "
            "My recommendation is to stop before you spend more time or money on it.\n\n"
            f"**Why:** {done.summary}")
    if changes:
        text += "\n\n**What could change my mind:**\n" + "\n".join(f"- {c}" for c in changes)
    return text + ("\n\nThis is not a judgement of you. Many good businesses start from a second or third idea. "
                   "Press **Start over with a new idea** whenever you are ready.")


def done_message(done: Done, changes: list[str] | None = None) -> str:
    if done.outcome == "stopped":
        return stop_message(done, changes or [])
    return {"completed": "**All six phases are done.** Every report above is also saved in the outputs folder.",
            "refused": f"**I can't work on this idea.** {done.summary}",
            "stopped_by_founder": f"**Stopped, as you asked.** {done.summary}",
            "error": f"**The run could not continue.** {done.summary}"}.get(done.outcome, done.summary)


def messages(transcript: list, pending: Request | None, done: Done | None) -> list[dict]:
    """transcript: Say, Request and ("founder", text) entries in the order they happened."""
    out = []
    for item in transcript:
        if isinstance(item, tuple):
            out.append({"role": "user", "content": item[1]})
        elif isinstance(item, Request):
            out.append({"role": "assistant", "content": request_message(item)})
        elif isinstance(item, Say):
            if item.kind == "done" and done is not None:
                continue                                  # the closing message below says it in plain words
            text = say_message(item)
            if text:
                out.append({"role": "assistant", "content": text})
    if done is not None:
        stops = [i for i in transcript if isinstance(i, Say) and i.kind == "gate" and i.outcome == "stop"]
        changes = (stops[-1].data or {}).get("what_would_change", []) if stops else []
        out.append({"role": "assistant", "content": done_message(done, changes)})
    elif pending is None and transcript:
        out.append({"role": "assistant", "content": WORKING})
    return out


# == what the founder can answer ===============================================
def quick_replies(req: Request | None, finished: bool = False) -> dict:
    """The buttons under the chat and the hint in the message box, for the current request."""
    if finished:
        return {"yes": None, "no": None, "placeholder": "This run is finished. To try another idea, press "
                "Start over with a new idea.", "can_type": False}
    if req is None:
        return {"yes": None, "no": None, "placeholder": "Steve is working. You can reply when he asks you something.",
                "can_type": False}
    if req.kind == "question":
        return {"yes": None, "no": None, "placeholder": "Type your answer, then press Send", "can_type": True}
    if req.kind == "confirm":
        return {"yes": "Yes, this is right. Continue", "no": "Stop working on this idea",
                "placeholder": "Want changes? Type what Steve should change, then press Send", "can_type": True}
    if req.kind == "gate" and req.step_id.endswith("_pivot"):
        return {"yes": None, "no": "Stop here", "placeholder": "Type your new idea in one full sentence, then press Send",
                "can_type": True}
    if req.kind == "gate":
        m = re.search(r"Phase (\d)", req.prompt.split("Continue to")[-1])
        nxt = f"Phase {m.group(1)}: {PHASE_NAMES[int(m.group(1))][0]}" if m else "the next phase"
        return {"yes": f"Yes, move on to {nxt}", "no": "Stop here", "placeholder": "Or type yes or stop",
                "can_type": True}
    return {"yes": "Approve (practice only)", "no": "Don't approve", "placeholder": "Or type yes or no",
            "can_type": True}


def reply_for(req: Request, action: str, text: str) -> tuple[Reply | None, str | None, str]:
    """action: yes | no | send. Returns (reply, problem shown to the founder, founder's chat message)."""
    text = " ".join((text or "").split())
    q = quick_replies(req)
    pivot = req.kind == "gate" and req.step_id.endswith("_pivot")
    if action == "yes" and q["yes"]:
        return Reply(True, ""), None, q["yes"]
    if action == "no" and q["no"]:
        return Reply(False, ""), None, q["no"]
    if action != "send":
        return None, "Choose one of the buttons, or type a message.", ""
    if not text:
        return None, "Type a message first." if req.kind != "question" else "Type your answer first.", ""
    if req.kind == "question":
        return Reply(None, text), None, text
    if pivot:
        if STOP.match(text) and len(text) < 15:
            return Reply(False, ""), None, text
        if len(text) < 15 or len(text.split()) < 4:
            return None, "Write the new idea in one full sentence, or press Stop here.", ""
        return Reply(True, text), None, text
    if YES.fullmatch(text) or (YES.match(text) and len(text) < 25):
        return Reply(True, ""), None, text
    if STOP.match(text) and len(text) < 25:
        return Reply(False, ""), None, text
    if req.kind == "confirm":
        return Reply(False, text), None, text            # Steve redoes the step with these changes
    return None, "For this step, press one of the buttons (or type yes or no).", ""
