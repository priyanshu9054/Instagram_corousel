from datetime import datetime, timezone

from instagrapi.exceptions import MediaNotFound

from pipeline import content_log, strategy


def _engagement_score(metrics: dict) -> float:
    """
    Simple, comparable-across-post-types engagement score. Reels get a small credit
    per view since play_count dwarfs like/comment counts; carousels/photos have no
    play_count so they're scored on likes+comments alone.
    """
    likes = metrics.get("like_count") or 0
    comments = metrics.get("comment_count") or 0
    plays = metrics.get("play_count") or 0
    return likes + 3 * comments + 0.05 * plays


def refresh_metrics(cl) -> list[dict]:
    """Re-fetch current like/comment/play counts for every logged post."""
    records = content_log.load_log()
    updated = []
    for r in records:
        media_pk = r.get("media_pk")
        if not media_pk or (r.get("metrics") or {}).get("removed"):
            continue
        try:
            media = cl.media_info_v1(media_pk)
            metrics = {
                "like_count": media.like_count,
                "comment_count": media.comment_count,
                "play_count": getattr(media, "play_count", None),
            }
            content_log.update_metrics(media_pk, metrics)
            updated.append({"media_pk": media_pk, **metrics})
        except MediaNotFound:
            print(f"Post {media_pk} ({r.get('media_code')}) is gone — marking removed, won't retry.")
            content_log.update_metrics(media_pk, {"removed": True})
        except Exception as e:
            print(f"Could not refresh metrics for {media_pk}: {e}")
    return updated


def build_report() -> dict:
    """Aggregate engagement by philosopher and by content type."""
    records = content_log.load_log()
    scored = [r for r in records if r.get("metrics") and not r["metrics"].get("removed")]

    def _group_by(key_fn):
        groups: dict[str, list[float]] = {}
        for r in scored:
            key = key_fn(r)
            if key is None:
                continue
            groups.setdefault(key, []).append(_engagement_score(r["metrics"]))
        return {
            k: {"avg_engagement": round(sum(v) / len(v), 3), "count": len(v)}
            for k, v in groups.items()
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_posts": len(records),
        "posts_with_metrics": len(scored),
        "by_author": _group_by(lambda r: r.get("author")),
        "by_content_type": _group_by(lambda r: r.get("content_type")),
    }


def run_analysis_cycle(cl) -> dict:
    """Refresh metrics, build a report, and nudge the strategy weights from it."""
    refresh_metrics(cl)
    report = build_report()
    updated_strategy = strategy.adjust_from_report(report)
    return {"report": report, "strategy": updated_strategy}
