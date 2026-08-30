from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def load_dotenv(path: Path | None = None) -> None:
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def load_mongo_env(path: Path | None = None) -> dict[str, str]:
    path = path or ROOT / ".env.mongo"
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


load_dotenv()

STUDIES_ROOT = Path(os.environ.get("STUDIES_ROOT", ROOT / "studies"))
BOT_API_BASE_URL = os.environ.get("BOT_API_BASE_URL", "http://localhost:8000")
BOTPROBE_TRACE_BASE_URL = os.environ.get("BOTPROBE_TRACE_BASE_URL", "http://10.128.0.34:3333")
BOTPROBE_TRACE_ENV = os.environ.get("BOTPROBE_TRACE_ENV", "prod")
BOTPROBE_BASE_URL = os.environ.get("BOTPROBE_BASE_URL", BOTPROBE_TRACE_BASE_URL)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MAX_TRACE_SESSIONS = int(os.environ.get("MAX_TRACE_SESSIONS", "200"))
