import json
import threading
import traceback
import uuid
from datetime import datetime, timezone
from typing import Optional

from pipeline.paths import STATE_DIR

JOBS_FILE = STATE_DIR / "jobs.json"
_lock = threading.Lock()


def _load() -> dict:
    if not JOBS_FILE.exists():
        return {}
    try:
        return json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(jobs: dict) -> None:
    JOBS_FILE.write_text(json.dumps(jobs, indent=2), encoding="utf-8")


def create_job(kind: str) -> str:
    """Register a new background job and return its id."""
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        jobs = _load()
        jobs[job_id] = {
            "job_id": job_id,
            "kind": kind,
            "status": "running",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "result": None,
            "error": None,
        }
        _save(jobs)
    return job_id


def finish_job(job_id: str, result: Optional[dict] = None, error: Optional[str] = None) -> None:
    with _lock:
        jobs = _load()
        if job_id in jobs:
            jobs[job_id]["status"] = "failed" if error else "succeeded"
            jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
            jobs[job_id]["result"] = result
            jobs[job_id]["error"] = error
            _save(jobs)


def get_job(job_id: str) -> Optional[dict]:
    return _load().get(job_id)


def run_in_background(kind: str, fn, *args, **kwargs) -> str:
    """Register a job, run fn(*args, **kwargs) in a daemon thread, record the outcome."""
    job_id = create_job(kind)

    def _runner():
        try:
            result = fn(*args, **kwargs)
            finish_job(job_id, result=result)
        except Exception as e:
            traceback.print_exc()
            finish_job(job_id, error=str(e))

    threading.Thread(target=_runner, daemon=True).start()
    return job_id
