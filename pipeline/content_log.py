import json
from datetime import datetime, timezone

from pipeline.paths import STATE_DIR

LOG_FILE = STATE_DIR / "content_log.json"


def load_log() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_log(records: list[dict]) -> None:
    LOG_FILE.write_text(json.dumps(records, indent=2), encoding="utf-8")


def log_post(record: dict) -> dict:
    """Append a published post's metadata (content type, quote, author, track, etc.)."""
    records = load_log()
    record = {
        "posted_at": datetime.now(timezone.utc).isoformat(),
        "metrics": None,
        "metrics_collected_at": None,
        **record,
    }
    records.append(record)
    save_log(records)
    return record


def update_metrics(media_pk: str, metrics: dict) -> None:
    records = load_log()
    for r in records:
        if str(r.get("media_pk")) == str(media_pk):
            r["metrics"] = metrics
            r["metrics_collected_at"] = datetime.now(timezone.utc).isoformat()
    save_log(records)
