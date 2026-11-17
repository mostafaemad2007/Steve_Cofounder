"""The model layer: a free local open-weight model through Ollama, or a recorded run replayed.

Modes
  live (default)  POST to Ollama /api/chat. Every reply is recorded so it can be replayed later.
  replay          Return the recorded reply for the same (agent, action, system, prompt).

If live is selected and the model cannot be reached, the layer falls back to replay when a
recording exists, tells the founder in plain words and logs the switch; with no recording it fails
loudly rather than inventing anything. Replay is an honest fallback, never a disguise: the caller
displays [REPLAY MODE], and the files committed in outputs/ must come from a live run.

chat_json() asks for JSON matching a schema, validates it, and retries with the error attached, so
a malformed reply becomes a retry instead of a crash halfway through a phase.

Cost is $0 for a local model. Paid APIs are not supported by this layer at all.
"""
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import config
from .logger import DecisionLogger
from .schema import SchemaError, validate

REPLAY_TAG = "[REPLAY MODE]"
LOCAL_COST_PER_TOKEN = 0.0           # a local open-weight model costs nothing per token
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)


class ModelUnavailable(RuntimeError):
    """The local model could not be reached and there is nothing recorded to replay."""


class BadModelOutput(RuntimeError):
    """The model did not return usable JSON after the retries."""


@dataclass
class LLMResult:
    text: str
    model: str | None
    mode: str                 # "live" or "replay"
    prompt_tokens: int
    completion_tokens: int
    cost: float
    seconds: float

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def labelled_text(self) -> str:
        """For display. The raw text stays clean so JSON parsing is never broken by the label."""
        return f"{REPLAY_TAG}\n{self.text}" if self.mode == "replay" else self.text


def _ollama_transport(url: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        hint = " (the model may still be downloading)" if exc.code == 404 else ""
        raise ModelUnavailable(f"HTTP {exc.code}{hint}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        raise ModelUnavailable(str(exc)) from exc


def explain_model_error(text: str, model: str) -> str:
    """Turn a raw model-server error into what happened and how to fix it."""
    t = (text or "").lower()
    if "not found" in t or "pull" in t:
        return (f"Steve's model ({model}) is not downloaded yet. Keep `docker compose up` running until its download "
                f"finishes, or download it again with: docker compose run --rm model-pull")
    if "memory" in t or "oom" in t or "killed" in t:
        return ("The laptop gave Steve's model too little memory to start. Close other programs and try again. If it "
                "still fails, give Docker more memory (Docker Desktop: Settings > Resources, or a .wslconfig file "
                "with memory=6GB), or use the smaller model by putting MODEL=qwen3:1.7b in a .env file.")
    if "timed out" in t or "timeout" in t:
        return ("Steve's model took too long to answer. The laptop may be busy: close other programs, or set "
                "LLM_TIMEOUT=1800 in a .env file.")
    if any(s in t for s in ("refused", "name or service", "nodename", "resolution", "unreachable", "errno 111",
                            "no route", "connection reset", "remote end closed")):
        return "Steve's model server (Ollama) is not running. Start everything with: docker compose up"
    return f"Steve's model server returned an error: {text[:200]}"


def replay_key(agent: str, action: str, prompt: str, system: str = "") -> str:
    digest = hashlib.sha256(f"{agent}\n{action}\n{system}\n{prompt}".encode("utf-8")).hexdigest()[:16]
    safe_action = re.sub(r"[^a-zA-Z0-9_-]", "-", action)[:60]
    return f"{agent}__{safe_action}__{digest}"


def extract_json(text: str):
    """Parse JSON out of model text, tolerating code fences, reasoning blocks and stray prose."""
    text = THINK_BLOCK.sub("", text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
        start = min(starts) if starts else -1
        end = max(text.rfind("}"), text.rfind("]"))
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise BadModelOutput("the model did not return valid JSON")


class LLM:
    def __init__(self, *, mode: str | None = None, model: str | None = None, url: str | None = None,
                 replay_dir: Path | None = None, logger: DecisionLogger | None = None,
                 transport: Callable[[str, dict, float], dict] | None = None,
                 timeout: float | None = None, temperature: float = 0.2, seed: int = 7):
        self.mode = mode or config.get("RUN_MODE", "live")
        if self.mode not in ("live", "replay"):
            raise ValueError("mode must be 'live' or 'replay'; paid APIs are not supported")
        self.model = model or config.get("MODEL", "qwen3:4b")
        self.url = url or config.get("OLLAMA_URL", "http://localhost:11434")
        self.replay_dir = Path(replay_dir) if replay_dir else config.path("REPLAY_DIR", "replay")
        self.logger = logger or DecisionLogger()
        self.transport = transport or _ollama_transport
        self.timeout = timeout or float(config.get("LLM_TIMEOUT", "900"))
        # A low temperature and a fixed seed keep two runs of the same brief comparable.
        self.options = {"temperature": temperature, "seed": seed,
                        "num_ctx": int(config.get("NUM_CTX", "8192"))}
        self.notices: list[str] = []
        self.used_replay = self.mode == "replay"
        self.totals = {"calls": 0, "tokens": 0, "cost": 0.0, "seconds": 0.0}

    # -- recording and replay --------------------------------------------
    def _replay_path(self, key: str) -> Path:
        return self.replay_dir / f"{key}.json"

    def _record(self, key: str, result: LLMResult) -> None:
        self.replay_dir.mkdir(parents=True, exist_ok=True)
        self._replay_path(key).write_text(json.dumps({
            "text": result.text, "model": result.model,
            "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
        }, indent=1, ensure_ascii=False), encoding="utf-8")

    def _replay(self, key: str) -> LLMResult:
        path = self._replay_path(key)
        if not path.exists():
            raise ModelUnavailable(
                "There is no recorded run to replay for this step. Replay only works for a brief that was run "
                "live before, unchanged (for example the two example ideas after the demo run). Choose Live instead, "
                "or start the model with: docker compose up")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.used_replay = True
        return LLMResult(text=data["text"], model=data.get("model"), mode="replay",
                         prompt_tokens=0, completion_tokens=0, cost=0.0, seconds=0.0)

    # -- the main entry point ---------------------------------------------
    def chat(self, *, agent: str, action: str, prompt: str, system: str = "",
             sources: list[str] | None = None, schema: dict | None = None) -> LLMResult:
        key = replay_key(agent, action, prompt, system)
        if self.mode == "replay":
            result = self._replay(key)
        else:
            try:
                result = self._live(prompt, system, schema)
                self._record(key, result)
            except ModelUnavailable as exc:
                if not self._replay_path(key).exists():
                    self.logger.log("llm", "model_error", reason=str(exc)[:200])
                    raise ModelUnavailable(explain_model_error(str(exc), self.model)) from exc
                notice = (f"{explain_model_error(str(exc), self.model)} Continuing in {REPLAY_TAG} from a "
                          "recorded run of this same step.")
                if notice not in self.notices:
                    self.notices.append(notice)
                self.logger.log("llm", "fallback_to_replay", reason=str(exc)[:200])
                result = self._replay(key)

        self.totals["calls"] += 1
        self.totals["tokens"] += result.tokens
        self.totals["cost"] += result.cost
        self.totals["seconds"] += result.seconds
        self.logger.log(agent, action, sources=sources or [], model=result.model,
                        cost=result.cost, mode=result.mode, tokens=result.tokens)
        return result

    def chat_json(self, *, agent: str, action: str, prompt: str, schema: dict, system: str = "",
                  sources: list[str] | None = None, retries: int = 2,
                  check: Callable[[dict], None] | None = None) -> dict:
        """Return parsed JSON matching `schema`. `check` can add rules a schema cannot express."""
        schema = {**schema, "title": schema.get("title") or action}
        instructions = ("\n\nReply with ONE JSON object and nothing else, matching this JSON schema:\n"
                        + json.dumps(schema, ensure_ascii=False))
        attempt_prompt = prompt + instructions
        last_error = ""
        for attempt in range(retries + 1):
            result = self.chat(agent=agent, prompt=attempt_prompt, system=system, sources=sources,
                               schema=schema,
                               action=action if attempt == 0 else f"{action}_retry{attempt}")
            try:
                data = extract_json(result.text)
                validate(data, schema)
                if check:
                    check(data)
                return data
            except (BadModelOutput, SchemaError, ValueError) as exc:
                last_error = str(exc)
                self.logger.log(agent, f"{action}_invalid_output", error=last_error[:200])
                attempt_prompt = (prompt + instructions +
                                  f"\n\nYour previous reply was rejected: {last_error}. "
                                  "Fix exactly that and reply with valid JSON only.")
        raise BadModelOutput(f"{agent}/{action}: no valid reply after {retries + 1} attempts "
                             f"(last error: {last_error})")

    def _live(self, prompt: str, system: str, schema: dict | None) -> LLMResult:
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "think": False, "options": self.options}
        if schema:
            payload["format"] = schema
        started = time.monotonic()
        data = self.transport(self.url, payload, self.timeout)
        seconds = time.monotonic() - started
        try:
            text = THINK_BLOCK.sub("", data["message"]["content"]).strip()
        except (KeyError, TypeError) as exc:
            raise ModelUnavailable(f"unexpected reply from the model: {str(data)[:200]}") from exc
        prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
        completion_tokens = int(data.get("eval_count", 0) or 0)
        return LLMResult(text=text, model=self.model, mode="live",
                         prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                         cost=(prompt_tokens + completion_tokens) * LOCAL_COST_PER_TOKEN,
                         seconds=seconds)

    # -- status -----------------------------------------------------------
    @property
    def uses_ollama(self) -> bool:
        return self.transport is _ollama_transport

    def model_listed(self) -> tuple[bool, str]:
        """Is the model server up, and is the model downloaded? (fast; does not load the model)"""
        try:
            with urllib.request.urlopen(self.url.rstrip("/") + "/api/tags", timeout=5) as response:
                tags = json.loads(response.read().decode("utf-8"))
        except Exception as exc:                                  # noqa: BLE001 - any failure means "not up"
            return False, explain_model_error(str(exc) or "connection refused", self.model)
        names = [m.get("name", "") for m in tags.get("models", [])]
        wanted = self.model if ":" in self.model else self.model + ":latest"
        if not any(n == wanted or n.split(":")[0] == self.model for n in names):
            return False, explain_model_error("model not found", self.model)
        return True, "ready"

    def warm_up(self) -> tuple[bool, str, float]:
        """Load the model with a one-token answer, so memory problems show up before the run starts."""
        started = time.monotonic()
        try:
            self.transport(self.url, {"model": self.model, "messages": [{"role": "user", "content": "Say OK"}],
                                      "stream": False, "think": False,
                                      "options": {**self.options, "num_predict": 1}}, min(self.timeout, 600))
        except ModelUnavailable as exc:
            return False, explain_model_error(str(exc), self.model), time.monotonic() - started
        return True, "ready", time.monotonic() - started

    def is_available(self) -> bool:
        """True when Ollama is up and the configured model is downloaded."""
        return self.model_listed()[0]

    def recorded_steps(self) -> int:
        return len(list(self.replay_dir.glob("*.json"))) if self.replay_dir.exists() else 0
