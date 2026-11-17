"""Start must never hang or fail silently: the run checks the model first and explains any problem."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def ollama(request):
    servers = []

    def start(mode, delay=0):
        port = free_port()
        servers.append(subprocess.Popen([sys.executable, str(ROOT / "tests/fake_ollama.py"), str(port), mode, str(delay)]))
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        return f"http://127.0.0.1:{port}"
    yield start
    for s in servers:
        s.kill()


def env_for(tmp_path, url):
    sources = tmp_path / "sources"
    sources.mkdir()
    for i in range(6):
        (sources / f"s{i}.md").write_text(
            f"URL: https://example.org/s{i}\nTitle: Source {i}\n\nCV templates competitors pricing price graduates "
            f"Egypt engineering students tech jobs hosting domain month cost trademark licence terms copyright fonts "
            f"free alternatives market chatbot app page {i}\n", encoding="utf-8")
    return dict(os.environ, OLLAMA_URL=url, WEB_SEARCH="false", SOURCES_DIR=str(sources),
                OUTPUT_DIR=str(tmp_path / "out"), DECISION_LOG=str(tmp_path / "log.json"),
                STATE_DIR=str(tmp_path / "state"), REPLAY_DIR=str(tmp_path / "replay"), PYTHONPATH=str(ROOT))


RUN = """
from venturegate.brief import FounderBrief
from venturegate.orchestrator import Pipeline, drive
from venturegate.events import Reply, Say
def h(ev):
    if isinstance(ev, Say): print('SAY', ev.kind, ev.text); return None
    return Reply(True, '')
print('DONE', drive(Pipeline(FounderBrief.load('examples/weak_idea.yaml')).run(), h).outcome)
"""


def run(tmp_path, url):
    return subprocess.run([sys.executable, "-c", RUN], cwd=ROOT, env=env_for(tmp_path, url),
                          capture_output=True, text=True, timeout=120).stdout


@pytest.mark.parametrize("mode, expected", [
    ("missing", "not downloaded yet"),
    ("memory", "too little memory"),
])
def test_a_broken_model_stops_the_run_at_once_with_the_reason(tmp_path, ollama, mode, expected):
    out = run(tmp_path, ollama(mode))
    assert "DONE error" in out and expected in out
    assert "REPLAY MODE" not in out                        # no pretend switch to a recording that does not exist
    actions = [e["action"] for e in json.loads((tmp_path / "log.json").read_text())]
    assert "model_not_ready" in actions and "end_run" in actions


def test_no_model_server_is_explained(tmp_path):
    out = run(tmp_path, "http://127.0.0.1:9")
    assert "DONE error" in out and "is not running" in out and "docker compose up" in out


def test_a_working_model_runs_over_real_http(tmp_path, ollama):
    out = run(tmp_path, ollama("ok"))
    assert "waking up" in out and "Gate 2: STOP" in out and "DONE stopped" in out
    warm = [e for e in json.loads((tmp_path / "log.json").read_text()) if e["action"] == "warm_up_model"]
    assert warm and warm[0]["ok"] is True


def check(tmp_path, url):
    return subprocess.run([sys.executable, "-m", "venturegate", "check"], cwd=ROOT, env=env_for(tmp_path, url),
                          capture_output=True, text=True, timeout=120)


def test_check_passes_when_everything_works(tmp_path, ollama):
    r = check(tmp_path, ollama("ok"))
    assert r.returncode == 0 and "[FAIL]" not in r.stdout and "Everything Steve needs works" in r.stdout


@pytest.mark.parametrize("mode, expected", [("missing", "not downloaded yet"), ("memory", "too little memory")])
def test_check_names_the_problem_and_the_fix(tmp_path, ollama, mode, expected):
    r = check(tmp_path, ollama(mode))
    assert r.returncode == 1 and "[FAIL]" in r.stdout and expected in r.stdout


def test_check_without_a_model_server(tmp_path):
    r = check(tmp_path, "http://127.0.0.1:9")
    assert r.returncode == 1 and "is not running" in r.stdout


def test_the_page_shows_steve_is_working_while_he_thinks():
    from venturegate.events import Say
    from venturegate.views import timeline_html
    busy = timeline_html([Say("Steve is waking up", kind="info")], None, None)
    assert "Steve is working on this step" in busy
    assert "Steve is working on this step" not in timeline_html([], None, None)
