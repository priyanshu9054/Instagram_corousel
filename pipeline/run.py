import os
import random
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reel_maker  # noqa: E402  (top-level module, reused as-is)

from pipeline import (  # noqa: E402
    quote_card,
    carousel_card,
    audio_picker,
    caption_gen,
    ig_client,
    trending_audio,
    strategy,
    content_log,
)
from pipeline.paths import getenv_clean

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
IMAGE_PATH = ROOT / "image.png"
REEL_PATH = ROOT / "reel.mp4"
CAPTION_PATH = ROOT / "caption.txt"
CAROUSEL_DIR = ROOT / "assets" / "_carousel_current"
REEL_DURATION_RANGE = (5.0, 7.0)  # seconds — every reel lands in this window, music included


def _track_label(track: Optional[dict]) -> Optional[str]:
    if not track:
        return None
    return f"{track.get('title')} — {track.get('display_artist')}"


def _build_reel(preferred_author: Optional[str], cl) -> dict:
    quote_meta = quote_card.generate(IMAGE_PATH, preferred_author=preferred_author)
    quote, author = quote_meta["quote"], quote_meta["author"]
    print(f"Quote: \"{quote}\" — {author}")

    track = trending_audio.pick_mood_matched_track(cl)
    audio_path = None
    audio_start_offset = 0.0

    if track:
        print(f"Trending audio (mood-matched): \"{track.get('title')}\" — {track.get('display_artist')}")
        try:
            audio_path = str(trending_audio.download_track_audio(cl, track))
            audio_start_offset = trending_audio.track_start_offset_seconds(track)
        except Exception as e:
            print(f"Failed to download trending track ({e}); falling back to local audio library.")
            track = None

    if not track:
        audio_path = audio_picker.pick_audio()
        print(f"Using local audio library: {audio_path or '(none — silent fallback)'}")

    duration = round(random.uniform(*REEL_DURATION_RANGE), 1)
    reel_path = reel_maker.create_reel_video(
        image_path=str(IMAGE_PATH),
        audio_path=audio_path,
        output_path=str(REEL_PATH),
        duration=duration,
        audio_start_offset=audio_start_offset,
    )

    return {
        "content_type": "reel",
        "quote": quote,
        "author": author,
        "track": _track_label(track),
        "media_path": reel_path,
    }


def _build_carousel(preferred_author: Optional[str]) -> dict:
    result = carousel_card.generate(CAROUSEL_DIR, preferred_author=preferred_author)
    print(f"Quote: \"{result['quote']}\" — {result['author']}")
    print(f"Hook: {result['copy']['hook']}")
    print(f"Shareable takeaway: {result['copy']['shareable']}")
    return {
        "content_type": "carousel",
        "quote": result["quote"],
        "author": result["author"],
        "track": None,
        "media_path": result["slides"],
    }


def run_pipeline(dry_run: bool = False, content_type: Optional[str] = None) -> dict:
    """
    One end-to-end pass, guided by the growth strategy (pipeline/strategy.py):
    pick a content type (reel or carousel) and a philosopher, weighted by which have
    performed best so far, build the content, write an LLM caption, and publish it.
    Every real post is logged (pipeline/content_log.py) so a later /analyze call can
    score performance and adjust those weights.

    With dry_run=True, everything runs (including login, for trending-audio lookup)
    except the final Instagram upload and the content log write.
    """
    username = getenv_clean("INSTAGRAM_USERNAME")
    password = getenv_clean("INSTAGRAM_PASSWORD")
    if not username or not password:
        raise RuntimeError("INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD missing from .env")

    live_strategy = strategy.load_strategy()
    chosen_author = strategy.choose_author(live_strategy)
    chosen_type = content_type or strategy.choose_content_type(live_strategy)
    print(f"Strategy picked: content_type={chosen_type}, author={chosen_author}")

    print(f"Logging in as @{username}...")
    cl = ig_client.get_client(username, password)

    if chosen_type == "carousel":
        built = _build_carousel(chosen_author)
    else:
        built = _build_reel(chosen_author, cl)

    caption = caption_gen.generate_caption(built["quote"], built["author"])
    CAPTION_PATH.write_text(caption, encoding="utf-8")
    print(f"Caption:\n{caption}\n")

    if dry_run:
        print("Dry run: skipping Instagram upload and content log.")
        return {"dry_run": True, "caption": caption, **built}

    print(f"Uploading {chosen_type}...")
    if chosen_type == "carousel":
        media = ig_client.upload_carousel(cl, built["media_path"], caption)
        url = f"https://www.instagram.com/p/{media.code}/"
    else:
        thumbnail_path = reel_maker.extract_thumbnail(built["media_path"])
        media = ig_client.upload_reel(cl, built["media_path"], caption, thumbnail_path=thumbnail_path)
        url = f"https://www.instagram.com/reel/{media.code}/"

    record = content_log.log_post({
        "content_type": chosen_type,
        "quote": built["quote"],
        "author": built["author"],
        "track": built["track"],
        "caption": caption,
        "media_pk": str(media.pk),
        "media_code": media.code,
        "url": url,
    })

    return {"dry_run": False, **record}


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    forced_type = "carousel" if "--carousel" in sys.argv else ("reel" if "--reel" in sys.argv else None)
    result = run_pipeline(dry_run=dry_run, content_type=forced_type)
    if dry_run:
        print(f"\n✅ Dry run complete: {result['media_path']}")
    else:
        print(f"\n\U0001f389 Posted: {result['url']}")
