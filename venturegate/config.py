"""Settings, read from the environment (see .env.example). No secrets are ever required."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Load .env if present. Values already in the environment win, so Docker can override."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def get(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def path(name: str, default: str) -> Path:
    p = Path(get(name, default))
    return p if p.is_absolute() else ROOT / p
