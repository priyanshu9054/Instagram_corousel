import json
import re
import tempfile
from pathlib import Path
from typing import Optional
import random

from pipeline.paths import STATE_DIR, getenv_clean

STATE_FILE = STATE_DIR / ".last_track.json"

MOOD_DESCRIPTION = (
    "a dark, introspective stoic/philosophy Instagram Reels page — grayscale portrait "
    "art of philosophers (Marcus Aurelius, Nietzsche, Seneca, Socrates...) paired with "
    "quotes about mortality, discipline, suffering, and meaning"
)

# Cheap keyword pre-filter to drop obvious mismatches before spending an LLM call.
_MISMATCH_PATTERNS = [
    r'from\s+"', r"\(from ", r"soundtrack", r"lullaby", r"nursery rhyme",
    r"bhajan", r"aarti", r"devotional", r"\bkids?\b", r"disney", r"birthday",
    r"wedding", r"cartoon",
]


def _looks_mismatched(track: dict) -> bool:
    text = f"{track.get('title', '')} {track.get('subtitle', '')}".lower()
    return any(re.search(p, text) for p in _MISMATCH_PATTERNS)


def _flatten_clips_browser(resp: dict) -> list[dict]:
    """items[].playlist.preview_items[].track — the Reels/Clips camera 'Add music' surface."""
    tracks = []
    for item in resp.get("items", []):
        for preview in item.get("playlist", {}).get("preview_items", []):
            t = preview.get("track")
            if t:
                tracks.append(t)
    return tracks


def _flatten_trending(resp: dict) -> list[dict]:
    """items[].track — Instagram's own 'trending music' surface."""
    return [item["track"] for item in resp.get("items", []) if item.get("track")]


def fetch_trending_pool(cl) -> list[dict]:
    """
    Pull Instagram's own trending / Reels-camera audio candidates through the private
    API (instagrapi's music_* endpoints) — the same catalogue a person sees tapping
    "Add music" on a Reel, not a third-party scrape.
    """
    pool: dict[str, dict] = {}

    try:
        clips = cl.music_clips_audio_browser(product="story_camera_clips_v2")
        for t in _flatten_clips_browser(clips):
            pool[t["id"]] = t
    except Exception as e:
        print(f"music_clips_audio_browser failed: {e}")

    try:
        trending = cl.music_trending(product="feed_post")
        for t in _flatten_trending(trending):
            pool[t["id"]] = t
    except Exception as e:
        print(f"music_trending failed: {e}")

    return list(pool.values())


def _llm_pick(tracks: list[dict]) -> Optional[dict]:
    """Ask Groq to pick the best mood fit from a list of (title, artist) pairs only."""
    api_key = getenv_clean("GROQ_API_KEY")
    if not api_key or not tracks:
        return None

    listing = "\n".join(
        f"{t['id']} | {t.get('title', '')} | {t.get('display_artist', '')}" for t in tracks
    )
    prompt = (
        f"You are picking background music for {MOOD_DESCRIPTION}.\n\n"
        "From this list of currently available tracks (id | title | artist), pick the ONE id "
        "whose title/artist/language best fits a moody, cinematic, minor-key, atmospheric or "
        "serious tone. Avoid upbeat pop, devotional/religious, kids'/movie-soundtrack, or "
        "comedic-sounding tracks unless nothing else qualifies.\n"
        "Reply with ONLY the id, nothing else.\n\n"
        f"{listing}"
    )
    try:
        from openai import OpenAI
        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
        model = getenv_clean("GROQ_MODEL", "openai/gpt-oss-120b")
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
            # gpt-oss models spend max_tokens on hidden reasoning before answering;
            # low effort + this small a task leaves room for an actual reply.
            extra_body={"reasoning_effort": "low"},
        )
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            print("Groq mood-pick returned empty content; falling back to random pick.")
            return None
        picked_id = content.split()[0].strip('"\'.')
        for t in tracks:
            if str(t.get("id")) == picked_id:
                return t
        print(f"Groq returned an id not in the candidate list ({picked_id!r}); ignoring.")
    except Exception as e:
        print(f"Mood-matching via Groq failed ({e}); falling back to random pick.")
    return None


def pick_mood_matched_track(cl) -> Optional[dict]:
    """
    Pick a track that actually fits the page's dark-philosophy aesthetic, instead of a
    uniformly random trending pick (which is just as likely to be upbeat pop or a movie
    OST). Cheap keyword filtering first, then a Groq call judges title/artist vibe;
    falls back to a random pick if Groq is unavailable or picks nothing valid.
    """
    pool = fetch_trending_pool(cl)
    if not pool:
        return None

    last_id = None
    if STATE_FILE.exists():
        try:
            last_id = json.loads(STATE_FILE.read_text(encoding="utf-8")).get("id")
        except Exception:
            pass

    candidates = [t for t in pool if t.get("id") != last_id] or pool
    filtered = [t for t in candidates if not _looks_mismatched(t)] or candidates

    chosen = _llm_pick(filtered) or random.choice(filtered)
    STATE_FILE.write_text(json.dumps({"id": chosen.get("id")}), encoding="utf-8")
    return chosen


def download_track_audio(cl, track: dict) -> Path:
    """
    Download the actual track audio (m4a/mp4-audio) so it can be muxed into the reel
    with ffmpeg — the approach that reliably plays, unlike attaching official-audio
    metadata to a silent upload (which instagrapi's clip_upload_with_music sends, but
    Instagram doesn't consistently render as audible sound).
    """
    url = track.get("progressive_download_url") or track.get("fast_start_progressive_download_url")
    if not url:
        raise RuntimeError("Track has no downloadable audio URL")

    tmp_dir = Path(tempfile.mkdtemp(prefix="ig_track_"))
    path = cl.track_download_by_url(url, filename=f"track_{track.get('id')}", folder=tmp_dir)
    return Path(path)


def track_start_offset_seconds(track: dict) -> float:
    """The track's suggested 'hook' start point, in seconds, for a good 7s highlight."""
    highlights = track.get("highlight_start_times_in_ms") or [0]
    return max(0.0, highlights[0] / 1000.0)
