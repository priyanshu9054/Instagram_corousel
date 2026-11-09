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

# Runtime state (growth-strategy weights, content log, last-picked state, the
# Instagram login session). Defaults to living alongside the code for local dev.
# This is deliberately treated as a CACHE, not durable storage: the deployment runs
# without a persistent volume, so every redeploy wipes it. Recovery goes through the
# API instead — the session from INSTAGRAM_SESSION_JSON or POST /session/upload, and
# the content log / strategy rebuilt from the account's real posts (content_log.
# rebuild_from_instagram, POST /state/rebuild). Nothing here may be assumed to exist.
DATA_DIR = Path(getenv_clean("DATA_DIR", str(ROOT)))
STATE_DIR = DATA_DIR / "assets"
SESSION_DIR = DATA_DIR / ".ig_session"

STATE_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR.mkdir(parents=True, exist_ok=True)
