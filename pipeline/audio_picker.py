import random

from pipeline.paths import STATIC_ASSETS_DIR

AUDIO_DIR = STATIC_ASSETS_DIR / "audio"


def pick_audio() -> str | None:
    """
    Fallback background-music picker: a random track from assets/audio/. Only used
    when pipeline.trending_audio's real Instagram trending-track lookup fails (e.g.
    the account loses licensed-music eligibility) — drop more .mp3 files into
    assets/audio/ to expand this pool.
    """
    tracks = sorted(AUDIO_DIR.glob("*.mp3"))
    if not tracks:
        return None
    return str(random.choice(tracks))
