"""Part 5b: the model layer, tested with a scripted fake model (no Ollama needed).

Covers: a live call, recording and replay, the fallback when the model is down, failing loudly when
there is nothing to replay, JSON extraction and retries, and that cost stays at $0.
"""
import pytest

from venturegate.llm import LLM, REPLAY_TAG, BadModelOutput, ModelUnavailable, extract_json
from venturegate.logger import DecisionLogger, validate_entry
from venturegate.schema import obj, s

VERDICT_SCHEMA = obj({"verdict": s()})


def working_model(url, payload, timeout):
    assert payload["stream"] is False
    return {"message": {"content": "Verdict: the evidence is weak."},
            "prompt_eval_count": 120, "eval_count": 30}


def model_is_down(url, payload, timeout):
    raise ModelUnavailable("connection refused")


@pytest.fixture
def env(tmp_path):
    return {"log": DecisionLogger(tmp_path / "log.json"), "replay": tmp_path / "replay"}


def make(env, transport, **kwargs):
    return LLM(mode=kwargs.pop("mode", "live"), logger=env["log"], replay_dir=env["replay"],
               transport=transport, **kwargs)


# == live =====================================================================
def test_a_live_call_is_logged_with_tokens_and_zero_cost(env):
    llm = make(env, working_model, model="qwen3:4b")
    result = llm.chat(agent="discover", action="verdict", prompt="Idea: a CV checker",
                      sources=["https://example.com/a"])
    assert result.text == "Verdict: the evidence is weak." and result.mode == "live"
    assert result.tokens == 150 and result.cost == 0

    entry = env["log"].read()[-1]
    validate_entry(entry)
    assert entry["model"] == "qwen3:4b" and entry["tokens"] == 150 and entry["cost"] == 0
    assert entry["sources"] == ["https://example.com/a"]
    assert llm.totals["calls"] == 1 and llm.totals["tokens"] == 150 and llm.totals["cost"] == 0


def test_reasoning_blocks_are_stripped_and_options_are_sent(env):
    seen = {}

    def model(url, payload, timeout):
        seen.update(payload)
        return {"message": {"content": "<think>internal reasoning</think>\nThe answer"}}

    result = make(env, model).chat(agent="discover", action="verdict", prompt="x")
    assert result.text == "The answer"
    assert seen["think"] is False
    assert seen["options"]["temperature"] <= 0.3 and "seed" in seen["options"]


def test_a_malformed_reply_is_not_silently_accepted(env):
    llm = make(env, lambda url, payload, timeout: {"error": "model not found"})
    with pytest.raises(ModelUnavailable):
        llm.chat(agent="discover", action="verdict", prompt="x")


# == replay ===================================================================
def test_a_live_reply_is_recorded_then_replayed_cleanly(env):
    make(env, working_model).chat(agent="discover", action="verdict", prompt="P")

    replayed = LLM(mode="replay", logger=env["log"], replay_dir=env["replay"]).chat(
        agent="discover", action="verdict", prompt="P")
    assert replayed.mode == "replay"
    assert replayed.text == "Verdict: the evidence is weak."        # clean, so JSON still parses
    assert replayed.labelled_text.startswith(REPLAY_TAG)            # labelled for display
    assert env["log"].read()[-1]["mode"] == "replay"


def test_a_different_prompt_is_not_replayed_as_the_same_step(env):
    make(env, working_model).chat(agent="discover", action="verdict", prompt="P")
    llm = LLM(mode="replay", logger=env["log"], replay_dir=env["replay"])
    with pytest.raises(ModelUnavailable):
        llm.chat(agent="discover", action="verdict", prompt="a different idea")


def test_falling_back_to_replay_is_announced_and_logged(env):
    make(env, working_model).chat(agent="discover", action="verdict", prompt="P")

    llm = make(env, model_is_down)
    result = llm.chat(agent="discover", action="verdict", prompt="P")
    assert result.mode == "replay" and llm.used_replay
    assert llm.notices and REPLAY_TAG in llm.notices[0]
    assert any(e["action"] == "fallback_to_replay" for e in env["log"].read())


def test_no_model_and_no_recording_fails_loudly_with_the_real_cause(env):
    llm = make(env, model_is_down)
    with pytest.raises(ModelUnavailable, match="docker compose up"):
        llm.chat(agent="discover", action="verdict", prompt="never recorded")
    assert llm.notices == []                               # no misleading "switching to replay"
    assert env["log"].read()[-1]["action"] == "model_error"


@pytest.mark.parametrize("raw, expected", [
    ('HTTP 404: model "qwen3:4b" not found, try pulling it first', "not downloaded yet"),
    ("HTTP 500: model requires more system memory (4.6 GiB) than is available (3.1 GiB)", "too little memory"),
    ("<urlopen error [Errno 111] Connection refused>", "is not running"),
    ("<urlopen error [Errno -2] Name or service not known>", "is not running"),
    ("timed out", "took too long"),
])
def test_model_errors_are_explained_with_a_fix(env, raw, expected):
    def failing(url, payload, timeout):
        raise ModelUnavailable(raw)
    with pytest.raises(ModelUnavailable, match=expected):
        make(env, failing).chat(agent="discover", action="verdict", prompt="x")


def test_warm_up_reports_memory_problems_before_a_run(env):
    def oom(url, payload, timeout):
        assert payload["options"]["num_predict"] == 1
        raise ModelUnavailable("HTTP 500: model requires more system memory (4.6 GiB) than is available")
    ok, why, _ = make(env, oom).warm_up()
    assert not ok and "too little memory" in why
    assert make(env, working_model).warm_up()[0]


# == JSON =====================================================================
@pytest.mark.parametrize("text, expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('Sure! Here it is: {"a": [1, 2]} hope that helps', {"a": [1, 2]}),
    ('<think>hmm</think>{"a": 1}', {"a": 1}),
])
def test_extract_json_tolerates_real_model_output(text, expected):
    assert extract_json(text) == expected


def test_extract_json_gives_up_on_prose():
    with pytest.raises(BadModelOutput):
        extract_json("I cannot answer that.")


def test_chat_json_validates_retries_and_passes_the_schema_to_the_model(env):
    replies = iter(["not json at all", '{"verdict": 5}', '```json\n{"verdict": "weak"}\n```'])
    seen = []

    def model(url, payload, timeout):
        seen.append(payload["format"]["title"])
        return {"message": {"content": next(replies)}}

    llm = make(env, model)
    data = llm.chat_json(agent="discover", action="verdict", prompt="x", schema=VERDICT_SCHEMA)
    assert data == {"verdict": "weak"}
    assert seen == ["verdict", "verdict", "verdict"]
    assert sum(e["action"] == "verdict_invalid_output" for e in env["log"].read()) == 2


def test_chat_json_applies_an_extra_check(env):
    replies = iter(['{"verdict": "amazing"}', '{"verdict": "weak"}'])

    def model(url, payload, timeout):
        return {"message": {"content": next(replies)}}

    def no_flattery(data):
        if data["verdict"] == "amazing":
            raise ValueError("the verdict must be realistic, not flattering")

    data = make(env, model).chat_json(agent="discover", action="verdict", prompt="x",
                                      schema=VERDICT_SCHEMA, check=no_flattery)
    assert data == {"verdict": "weak"}


def test_chat_json_gives_up_with_a_clear_error(env):
    llm = make(env, lambda url, payload, timeout: {"message": {"content": '{"wrong": 1}'}})
    with pytest.raises(BadModelOutput, match="no valid reply after"):
        llm.chat_json(agent="discover", action="verdict", prompt="x",
                      schema=VERDICT_SCHEMA, retries=1)


# == configuration ============================================================
def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="paid APIs are not supported"):
        LLM(mode="paid-api")


def test_availability_is_false_without_a_server(env):
    assert make(env, working_model, url="http://127.0.0.1:1").is_available() is False
