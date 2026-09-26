from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import LoginRequired

from pipeline.paths import SESSION_DIR

SESSION_FILE = SESSION_DIR / "instagrapi_settings.json"


def get_client(username: str, password: str) -> Client:
    """
    Log into Instagram via instagrapi's private-API client, reusing a persisted
    session whenever possible so the account isn't hit with a fresh password login
    (and the challenge/2FA flow that can trigger) on every request.
    """
    cl = Client()
    SESSION_FILE.parent.mkdir(exist_ok=True)

    if SESSION_FILE.exists():
        cl.load_settings(SESSION_FILE)
        try:
            cl.login(username, password)
            cl.get_timeline_feed()  # cheap call to confirm the session is actually valid
        except LoginRequired:
            print("Saved session expired — logging in fresh.")
            cl.set_settings({})
            cl.set_uuids(cl.generate_uuids())
            cl.login(username, password)
    else:
        cl.login(username, password)

    cl.dump_settings(SESSION_FILE)
    return cl


def upload_carousel(cl: Client, image_paths: list[str], caption: str):
    """Upload a multi-image carousel post via instagrapi's album_upload."""
    return cl.album_upload([Path(p) for p in image_paths], caption=caption)


def upload_reel(cl: Client, video_path: str, caption: str, thumbnail_path: str | None = None):
    """
    Upload a 9:16 video as an Instagram Reel via instagrapi's clip_upload. The audio
    (real trending track or local library fallback) is expected to already be baked
    into video_path by reel_maker — attaching official-audio metadata to a silent
    upload (clip_upload_with_music) doesn't reliably produce audible sound.
    """
    kwargs = {"thumbnail": Path(thumbnail_path)} if thumbnail_path else {}
    return cl.clip_upload(Path(video_path), caption=caption, **kwargs)
