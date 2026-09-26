import os
from pathlib import Path


def getenv_clean(name: str, default=None):
    """
    os.getenv, but strips surrounding quotes. python-dotenv's load_dotenv() strips
    quotes from KEY="value" lines, but not every deployment platform's env-var
    injection does (e.g. `docker run --env-file .env` passes the quotes through
    literally) — this keeps values consistent regardless of how they got set.
    """
    val = os.getenv(name, default)
    if isinstance(val, str):
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
    return val

ROOT = Path(__file__).resolve().parent.parent

# Static, bundled assets that ship with the code (quotes, portraits, audio library).
STATIC_ASSETS_DIR = ROOT / "assets"

# Durable runtime state (growth-strategy weights, content log, last-picked state,
# the Instagram login session). Defaults to living alongside the code for local dev.
# On a host with an ephemeral filesystem (e.g. Railway without a volume), every
# redeploy wipes this — set DATA_DIR to a mounted volume's path (e.g. "/data") in
# the environment so the strategy/analytics loop actually persists across deploys.
DATA_DIR = Path(getenv_clean("DATA_DIR", str(ROOT)))
STATE_DIR = DATA_DIR / "assets"
SESSION_DIR = DATA_DIR / ".ig_session"

STATE_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR.mkdir(parents=True, exist_ok=True)
