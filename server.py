"""
Single-hit API: one POST request runs the whole pipeline (strategy pick -> quote/
carousel -> reel/caption -> Instagram publish) and returns the result. A separate
/analyze endpoint refreshes performance metrics on past posts and nudges the growth
strategy's weights toward whatever's actually working.

Run:
    uvicorn server:app --host 0.0.0.0 --port 8000

Post content (reel or carousel, picked by the current growth strategy):
    curl -X POST http://localhost:8000/post-reel -H "x-api-key: $API_TRIGGER_KEY"

Dry run (builds the content, skips the actual Instagram upload):
    curl -X POST "http://localhost:8000/post-reel?dry_run=true" -H "x-api-key: $API_TRIGGER_KEY"

Force a content type instead of letting the strategy pick:
    curl -X POST "http://localhost:8000/post-reel?content_type=carousel" -H "x-api-key: $API_TRIGGER_KEY"

Refresh metrics on past posts and adjust the strategy (run this on a slower cron,
e.g. weekly, so there's actually new engagement data to learn from):
    curl -X POST http://localhost:8000/analyze -H "x-api-key: $API_TRIGGER_KEY"

Inspect current strategy weights / recent post log (read-only):
    curl http://localhost:8000/strategy -H "x-api-key: $API_TRIGGER_KEY"
    curl http://localhost:8000/content-log -H "x-api-key: $API_TRIGGER_KEY"

Seed this deployment's Instagram session from an already-trusted local one (avoids
a scrutinized fresh login from a datacenter IP) — without a persistent volume this
only lasts until the next restart/redeploy:
    curl -X POST http://localhost:8000/session/upload -H "x-api-key: $API_TRIGGER_KEY" \
      -H "Content-Type: application/json" -d @.ig_session/instagrapi_settings.json
    curl http://localhost:8000/session/status -H "x-api-key: $API_TRIGGER_KEY"
"""
import json
import os
import traceback
from typing import Optional

from dotenv import load_dotenv
from fastapi import Body, FastAPI, Header, HTTPException

from pipeline.run import run_pipeline
from pipeline import ig_client, analytics, strategy, content_log
from pipeline.paths import getenv_clean

load_dotenv()

app = FastAPI(title="Philosopher Reel Bot")

API_TRIGGER_KEY = getenv_clean("API_TRIGGER_KEY")


def _check_key(x_api_key: str | None):
    if API_TRIGGER_KEY and x_api_key != API_TRIGGER_KEY:
        raise HTTPException(status_code=401, detail="Missing or invalid x-api-key header")


@app.post("/post-reel")
def post_reel(
    dry_run: bool = False,
    content_type: Optional[str] = None,
    x_api_key: str | None = Header(default=None),
):
    _check_key(x_api_key)
    if content_type and content_type not in ("reel", "carousel"):
        raise HTTPException(status_code=400, detail="content_type must be 'reel' or 'carousel'")

    try:
        result = run_pipeline(dry_run=dry_run, content_type=content_type)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "dry_run" if dry_run else "posted", **result}


@app.post("/analyze")
def analyze(x_api_key: str | None = Header(default=None)):
    """Refresh metrics on past posts and nudge the strategy weights from them."""
    _check_key(x_api_key)

    username = getenv_clean("INSTAGRAM_USERNAME")
    password = getenv_clean("INSTAGRAM_PASSWORD")
    if not username or not password:
        raise HTTPException(status_code=500, detail="INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD missing from .env")

    try:
        cl = ig_client.get_client(username, password)
        result = analytics.run_analysis_cycle(cl)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    return result


@app.get("/strategy")
def get_strategy(x_api_key: str | None = Header(default=None)):
    _check_key(x_api_key)
    return strategy.load_strategy()


@app.get("/content-log")
def get_content_log(limit: int = 50, x_api_key: str | None = Header(default=None)):
    _check_key(x_api_key)
    records = content_log.load_log()
    return {"total": len(records), "records": records[-limit:]}


@app.post("/session/upload")
def upload_session(session: dict = Body(...), x_api_key: str | None = Header(default=None)):
    """
    Seed this deployment's Instagram login session from an already-trusted one
    (e.g. dumped locally via instagrapi's Client.dump_settings). A fresh login from
    a datacenter IP with no prior session gets scrutinized far more heavily by
    Instagram's anti-bot systems than reusing an established session — this avoids
    that entirely. Without a persistent volume at DATA_DIR, this only lasts until
    the next redeploy/restart.
    """
    _check_key(x_api_key)
    ig_client.SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    ig_client.SESSION_FILE.write_text(json.dumps(session), encoding="utf-8")
    return {"status": "ok", "path": str(ig_client.SESSION_FILE), "bytes_written": len(json.dumps(session))}


@app.get("/session/status")
def session_status(x_api_key: str | None = Header(default=None)):
    _check_key(x_api_key)
    exists = ig_client.SESSION_FILE.exists()
    return {
        "exists": exists,
        "path": str(ig_client.SESSION_FILE),
        "size_bytes": ig_client.SESSION_FILE.stat().st_size if exists else None,
    }


@app.get("/diagnostics")
def diagnostics(x_api_key: str | None = Header(default=None)):
    """
    Container resource info — added while diagnosing ffmpeg getting SIGKILL'd (exit
    -9) on Railway. cgroup limits (what the container is actually capped at) matter
    more than /proc/meminfo's host-level totals, which can be misleading inside a
    container.
    """
    _check_key(x_api_key)
    info = {}

    try:
        meminfo = {}
        for line in open("/proc/meminfo"):
            parts = line.split(":")
            if len(parts) == 2:
                meminfo[parts[0].strip()] = parts[1].strip()
        info["proc_meminfo"] = {
            k: meminfo[k] for k in ("MemTotal", "MemFree", "MemAvailable") if k in meminfo
        }
    except Exception as e:
        info["proc_meminfo_error"] = str(e)

    for cgroup_path in [
        "/sys/fs/cgroup/memory.max",  # cgroup v2
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",  # cgroup v1
    ]:
        try:
            info[cgroup_path] = open(cgroup_path).read().strip()
        except Exception as e:
            info[f"{cgroup_path}_error"] = str(e)

    try:
        info["cpu_count"] = os.cpu_count()
    except Exception as e:
        info["cpu_count_error"] = str(e)

    return info


@app.get("/health")
def health():
    return {"status": "ok"}
