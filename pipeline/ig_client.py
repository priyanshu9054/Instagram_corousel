import base64
import json
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import ChallengeRequired, ClientError, LoginRequired

from pipeline.paths import SESSION_DIR, getenv_clean

SESSION_FILE = SESSION_DIR / "instagrapi_settings.json"

# Settings keys that identify the "phone" rather than the logged-in session. Instagram
# challenges a login far more readily when it comes from a device fingerprint it has
# never seen, so these are carried across a re-login while the stale auth data is
# dropped — a fresh Client() would roll a random new device and get challenged.
DEVICE_KEYS = (
    "uuids",
    "device_settings",
    "user_agent",
    "country",
    "country_code",
    "locale",
    "timezone_offset",
    "timezone_name",
    "mid",
)


def _no_interactive_challenge(username: str, choice) -> str:
    """
    Replaces instagrapi's default handler, which calls input() — in a container
    stdin is closed, so that surfaces as a confusing "EOF when reading a line"
    instead of the real problem.
    """
    raise ChallengeRequired(
        f"Instagram wants a {choice} verification code for @{username}, which this "
        "deployment cannot answer. Log in locally (where the code can be typed), then "
        "push the resulting instagrapi_settings.json to POST /session/upload, or set "
        "INSTAGRAM_SESSION_JSON so it survives redeploys."
    )


def _seed_settings() -> dict | None:
    """
    Load session settings from the local file, else from INSTAGRAM_SESSION_JSON (raw
    JSON or base64). The env var is the only copy that survives a redeploy on a host
    with no persistent volume — the file is written back on every successful login,
    but that filesystem is thrown away with the container.
    """
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Session file at {SESSION_FILE} is unreadable ({e}) — ignoring it.")

    raw = getenv_clean("INSTAGRAM_SESSION_JSON")
    if not raw:
        return None
    try:
        if not raw.lstrip().startswith("{"):
            raw = base64.b64decode(raw).decode("utf-8")
        settings = json.loads(raw)
        print("Seeded Instagram session from INSTAGRAM_SESSION_JSON.")
        return settings
    except Exception as e:
        print(f"INSTAGRAM_SESSION_JSON could not be parsed ({e}) — ignoring it.")
        return None


def _persist(cl: Client) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    cl.dump_settings(SESSION_FILE)


def _new_client() -> Client:
    cl = Client()
    cl.delay_range = [1, 3]
    cl.challenge_code_handler = _no_interactive_challenge
    return cl


def get_client(username: str, password: str) -> Client:
    """
    Log into Instagram via instagrapi's private-API client, reusing a persisted
    session whenever possible so the account isn't hit with a fresh password login
    (and the challenge/2FA flow that can trigger) on every request.

    A cold password login from a datacenter IP on an unrecognized device reliably
    triggers an email challenge that a server can't answer, so the only supported
    recovery is to hand it a session that was established elsewhere — see
    _seed_settings and POST /session/upload.
    """
    settings = _seed_settings()
    cl = _new_client()

    if settings:
        cl.set_settings(settings)
        try:
            # With auth data loaded, login() validates the existing session and only
            # falls back to a full re-login if Instagram has rejected it; that
            # internal path keeps the device fingerprint intact.
            cl.login(username, password)
            _persist(cl)
            return cl
        except (LoginRequired, ClientError) as e:
            print(f"Saved session rejected ({type(e).__name__}: {e}) — re-logging in on the same device.")

        # Drop the stale auth data but keep the device identity, so this still looks
        # like the phone that logged in before.
        cl = _new_client()
        cl.set_settings({k: settings[k] for k in DEVICE_KEYS if k in settings})
        device = (settings.get("device_settings") or {}).get("model")
        print(f"Re-login reusing device fingerprint: {device or 'unknown'}")
    else:
        # A cold login here is not just likely to fail, it's harmful: each attempt
        # sends the account another challenge email and adds to whatever risk score
        # Instagram keeps, pushing it toward a real lock. Refuse by default rather
        # than retrying something that cannot succeed unattended.
        message = (
            "No Instagram session available (no session file, and INSTAGRAM_SESSION_JSON "
            "is not set in this environment). A cold password login from here would be "
            "challenged for an emailed code that this process cannot answer, so it is "
            "not attempted. Fix by setting INSTAGRAM_SESSION_JSON, or POST a locally "
            "dumped instagrapi_settings.json to /session/upload. Check GET /diagnostics "
            "to see which variables actually reached the container. Set "
            "ALLOW_COLD_LOGIN=true to override and try anyway."
        )
        if (getenv_clean("ALLOW_COLD_LOGIN") or "").lower() not in ("1", "true", "yes"):
            raise RuntimeError(message)
        print(f"{message}\n\nALLOW_COLD_LOGIN is set — attempting the cold login anyway.")

    cl.login(username, password)
    _persist(cl)
    return cl


def export_settings() -> dict | None:
    """Current on-disk session, for copying into INSTAGRAM_SESSION_JSON."""
    if not SESSION_FILE.exists():
        return None
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


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
