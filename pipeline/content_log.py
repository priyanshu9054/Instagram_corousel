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


def _match_author(caption: str, known_authors: list[str]) -> str | None:
    """
    Best-effort author recovery from a published caption. Captions are LLM-written and
    deliberately don't restate the quote, so the author's name is often absent entirely
    — the fallback template's #authorname hashtag is the more reliable signal. Returns
    None when nothing matches; analytics skips records with no author rather than
    attributing them to the wrong philosopher.
    """
    haystack = (caption or "").lower()
    for author in known_authors:
        if author.lower() in haystack:
            return author
        if f"#{author.lower().replace(' ', '')}" in haystack:
            return author
    return None


def rebuild_from_instagram(cl, limit: int = 100) -> list[dict]:
    """
    Reconstruct the content log from the account's actual Instagram posts.

    Without a persistent volume this file is wiped on every redeploy, which resets the
    content-type cycle to post #0 (so every post comes out a carousel) and throws away
    the engagement history the strategy learns from. The posts themselves are the real
    source of truth, so pull them back from the API instead.

    Recovered exactly: post count, media ids, timestamps, content type, metrics.
    Recovered only heuristically: the author (see _match_author). The quote isn't
    recoverable at all — it's rendered into the image, never written to the caption.
    """
    from pipeline import strategy

    known_authors = strategy._all_authors()
    medias = cl.user_medias(cl.user_id, amount=limit)
    existing = {str(r.get("media_pk")): r for r in load_log()}

    records = []
    for media in sorted(medias, key=lambda m: m.taken_at):
        pk = str(media.pk)
        if media.media_type == 8:
            content_type = "carousel"
        elif media.media_type == 2:
            content_type = "reel" if getattr(media, "product_type", "") == "clips" else "video"
        else:
            content_type = "photo"

        caption = media.caption_text or ""
        record = {
            "posted_at": media.taken_at.isoformat(),
            "content_type": content_type,
            "quote": None,  # burned into the image, not stored in the caption
            "author": _match_author(caption, known_authors),
            "track": None,
            "caption": caption,
            "media_pk": pk,
            "media_code": media.code,
            # Key matches what run.py's live log_post writes, so a rebuilt record and
            # a natively-logged one have the same shape.
            "url": f"https://www.instagram.com/p/{media.code}/",
            "metrics": {
                "like_count": media.like_count,
                "comment_count": media.comment_count,
                "play_count": getattr(media, "play_count", None),
            },
            "metrics_collected_at": datetime.now(timezone.utc).isoformat(),
            "rebuilt_from_api": True,
        }
        # A locally-logged record knows the real quote/author/track — keep those fields
        # and just refresh the metrics from the API.
        if pk in existing:
            prior = existing[pk]
            record = {**record, **{k: v for k, v in prior.items() if v is not None}}
            record["metrics"] = {
                "like_count": media.like_count,
                "comment_count": media.comment_count,
                "play_count": getattr(media, "play_count", None),
            }
        records.append(record)

    save_log(records)
    return records


def hydrate_if_empty(cl) -> list[dict]:
    """
    Repopulate an empty log from the API before anything reads its length. Called at
    the start of a pipeline run so a post-redeploy container continues the content-type
    cycle where the account actually left off instead of restarting at post #0.
    """
    records = load_log()
    if records:
        return records
    try:
        records = rebuild_from_instagram(cl)
        print(f"Content log was empty — rebuilt {len(records)} post(s) from the Instagram API.")
    except Exception as e:
        print(f"Could not rebuild content log from the API ({type(e).__name__}: {e}) — continuing with an empty log.")
        return []
    return records
