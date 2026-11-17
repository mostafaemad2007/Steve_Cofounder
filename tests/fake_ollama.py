"""TEST-ONLY HTTP server that answers like Ollama, to test the real HTTP path without a model.

    python tests/fake_ollama.py PORT MODE [DELAY_SECONDS]

MODE: ok | missing (model not pulled) | memory (not enough RAM) | busy (500 once, then ok)
Replies come from tests/fake_model.py. Error bodies copy Ollama's real wording.
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_model import FakeModel   # noqa: E402

PORT, MODE = int(sys.argv[1]), sys.argv[2]
DELAY = float(sys.argv[3]) if len(sys.argv) > 3 else 0
MODEL = FakeModel()
STATE = {"calls": 0}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/tags":
            models = [] if MODE == "missing" else [{"name": "qwen3:4b", "size": 2497293931}]
            return self._send(200, {"models": models})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        STATE["calls"] += 1
        if MODE == "missing":
            return self._send(404, {"error": f'model "{payload["model"]}" not found, try pulling it first'})
        if MODE == "memory":
            return self._send(500, {"error": "model requires more system memory (4.6 GiB) than is available (3.1 GiB)"})
        time.sleep(DELAY)
        self._send(200, MODEL(None, payload, 0))

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
