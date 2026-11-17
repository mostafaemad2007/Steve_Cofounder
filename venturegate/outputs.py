"""Writes pipeline outputs under the names TEAM_CLAUDE.md requires:

    outputs/phase<N>_step<M>_<run>-<short-name>.<ext>
    outputs/phase<N>_gate_<run>-<short-name>.<ext>

Every file opens with a status line naming the run and the model, and saying [REPLAY MODE] when
the text was replayed rather than generated live, so no output can pass for something it is not.
"""
import re
from pathlib import Path
from typing import Callable

from . import config

ALLOWED_EXTENSIONS = ("md", "json", "csv", "txt", "html")


def slug(text: str, limit: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:limit].strip("-") or "output"


class OutputWriter:
    def __init__(self, run: str, base: Path | None = None, status: Callable[[], dict] | None = None):
        self.run = slug(run, 20)
        self.base = Path(base) if base else config.path("OUTPUT_DIR", "outputs")
        self.status = status or (lambda: {})
        self.written: list[Path] = []

    def name(self, phase: int, step: int | None, short: str, ext: str = "md") -> str:
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"outputs must be text: one of {ALLOWED_EXTENSIONS}")
        if not isinstance(phase, int) or not 1 <= phase <= 6:
            raise ValueError("phase must be 1 to 6")
        if step is not None and (not isinstance(step, int) or step < 1):
            raise ValueError("step must be a positive number, or None for a gate")
        middle = "gate" if step is None else f"step{step}"
        return f"phase{phase}_{middle}_{self.run}-{slug(short)}.{ext}"

    def banner(self, labels: list[str] | None = None) -> str:
        state = self.status()
        parts = [f"Run: {self.run}", f"Model: {state.get('model') or 'none'}"]
        parts.append("[REPLAY MODE] replayed from a recorded real run" if state.get("replay") else "Mode: live")
        parts += labels or []
        return " · ".join(parts)

    def write(self, phase: int, step: int | None, short: str, content: str, *, ext: str = "md",
              labels: list[str] | None = None) -> Path:
        path = self.base / self.name(phase, step, short, ext)
        banner = self.banner(labels)
        if ext == "md":
            body = f"> {banner}\n\n{content.strip()}\n"
        elif ext == "html":
            note = (f'<div style="background:#fff3cd;padding:6px 10px;font:13px sans-serif">'
                    f'{_escape(banner)}</div>')
            if re.search(r"<body[^>]*>", content, re.I):
                body = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + note, content, count=1, flags=re.I)
            else:
                body = note + content
        else:
            body = content
        self.base.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        if path not in self.written:
            self.written.append(path)
        return path

    def gate(self, phase: int, short: str, content: str, labels: list[str] | None = None) -> Path:
        return self.write(phase, None, short, content, labels=labels)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
