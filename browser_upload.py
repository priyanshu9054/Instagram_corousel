import os
import sys
import base64
import asyncio
import subprocess
from openai import OpenAI
from playwright.async_api import async_playwright
from dotenv import load_dotenv

import reel_maker

load_dotenv()

INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

IMAGE_PATH = os.path.join(os.path.dirname(__file__), "image.png")
CAPTION_FILE = os.path.join(os.path.dirname(__file__), "caption.txt")
SESSION_DIR = os.path.join(os.path.dirname(__file__), ".ig_session")
AUDIO_PATH = os.path.join(os.path.dirname(__file__), "trending_audio.mp3")
REEL_PATH = os.path.join(os.path.dirname(__file__), "reel.mp4")


def generate_caption(image_path: str, is_reel: bool = True) -> str:
    if GROQ_API_KEY:
        print("Generating caption with Groq (qwen/qwen3.8-27b)...")
        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY)
        model = "qwen/qwen3.8-27b"
    elif OPENAI_API_KEY:
        print("Generating caption with GPT-4o...")
        client = OpenAI(api_key=OPENAI_API_KEY)
        model = "gpt-4o"
    else:
        print("No AI key found — skipping caption generation.")
        return ""

    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    prompt_extra = " Tailor the hashtags for an Instagram Reel (e.g. #reels #trending #viral)." if is_reel else ""

    resp = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}},
                {"type": "text", "text": (
                    f"Write an engaging Instagram caption for this image.{prompt_extra} "
                    "Keep it concise and natural, then end with 5-10 relevant hashtags. "
                    "Return only the caption and hashtags, nothing else."
                )},
            ],
        }],
        max_tokens=300,
    )

    caption = resp.choices[0].message.content.strip()
    print(f"\nCaption:\n{caption}\n")
    return caption


def get_caption(image_path: str, is_reel: bool = True, force_regenerate: bool = False) -> str:
    """Load existing caption from caption.txt if present, or generate and cache it."""
    if not force_regenerate and os.path.exists(CAPTION_FILE):
        with open(CAPTION_FILE, "r", encoding="utf-8") as f:
            saved_caption = f.read().strip()
        if saved_caption:
            print(f"Loaded existing caption from {os.path.basename(CAPTION_FILE)}:\n")
            print(saved_caption)
            print("-" * 50)
            return saved_caption

    caption = generate_caption(image_path, is_reel=is_reel)
    if caption:
        with open(CAPTION_FILE, "w", encoding="utf-8") as f:
            f.write(caption)
        print(f"Saved caption to {os.path.basename(CAPTION_FILE)}")
    return caption


async def dismiss_dialogs(page):
    """Dismiss common Instagram pop-ups (cookies, save-login, notifications, OK modals)."""
    for label in [
        "Allow all cookies", "Accept All", "Allow essential and optional cookies",
        "Only allow essential cookies", "Decline optional cookies",
        "Save info", "Save Info", "Not now", "Not Now", "Cancel", "OK",
    ]:
        try:
            btn = page.get_by_role("button", name=label, exact=True)
            if await btn.is_visible(timeout=1200):
                await btn.click()
                print(f"  Dismissed: '{label}'")
        except Exception:
            pass


async def fetch_trending_audio(page) -> str:
    """
    Navigate to Instagram Reels feed, capture the audio stream of the top trending Reel,
    and save it as an MP3 file.
    """
    print("\n🎧 Fetching trending music directly from Instagram Reels...")
    try:
        await page.goto("https://www.instagram.com/reels/", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2500)
        await dismiss_dialogs(page)

        record_script = """
        async () => {
            const videos = Array.from(document.querySelectorAll('video'));
            const video = videos.find(v => !v.paused && v.duration > 0) || videos[0];
            if (!video) return { error: "No video found on page" };

            video.muted = false;
            video.volume = 1.0;
            try { await video.play(); } catch(e) {}

            let stream;
            if (video.captureStream) {
                stream = video.captureStream();
            } else if (video.mozCaptureStream) {
                stream = video.mozCaptureStream();
            } else {
                return { error: "captureStream not supported" };
            }

            const audioTracks = stream.getAudioTracks();
            if (!audioTracks || audioTracks.length === 0) {
                return { error: "No audio track available" };
            }

            const audioStream = new MediaStream(audioTracks);
            const recorder = new MediaRecorder(audioStream);
            const chunks = [];

            return new Promise((resolve) => {
                recorder.ondataavailable = (e) => {
                    if (e.data && e.data.size > 0) chunks.push(e.data);
                };
                recorder.onstop = () => {
                    const blob = new Blob(chunks, { type: 'audio/webm' });
                    const reader = new FileReader();
                    reader.onloadend = () => resolve({ data: reader.result });
                    reader.readAsDataURL(blob);
                };
                recorder.start();
                setTimeout(() => {
                    recorder.stop();
                }, 7000);
            });
        }
        """

        result = await page.evaluate(record_script)
        if "error" in result:
            print(f"  Note: {result['error']}. Using default audio.")
            return None

        data_url = result.get("data", "")
        if not data_url:
            return None

        header, encoded = data_url.split(",", 1)
        raw_bytes = base64.b64decode(encoded)

        temp_webm = os.path.join(os.path.dirname(AUDIO_PATH), "temp_trending.webm")
        with open(temp_webm, "wb") as f:
            f.write(raw_bytes)

        # Convert webm to mp3 using FFmpeg
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe, "-y",
            "-i", temp_webm,
            "-vn",
            "-c:a", "libmp3lame",
            "-q:a", "2",
            AUDIO_PATH,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if os.path.exists(temp_webm):
            os.remove(temp_webm)

        if res.returncode == 0 and os.path.exists(AUDIO_PATH) and os.path.getsize(AUDIO_PATH) > 1000:
            print(f"  ✅ Captured trending Instagram audio ({os.path.getsize(AUDIO_PATH)} bytes)")
            return AUDIO_PATH
        return None

    except Exception as e:
        print(f"  Could not capture audio stream: {e}. Fallback audio will be used.")
        return None


async def upload_to_instagram(caption: str, as_reel: bool = True):
    upload_file = IMAGE_PATH

    async with async_playwright() as p:
        os.makedirs(SESSION_DIR, exist_ok=True)
        context = await p.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=False,
            slow_mo=150,
            viewport={"width": 1280, "height": 900},
            args=["--autoplay-policy=no-user-gesture-required"],
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # ── 1. Check login / authenticate ──────────────────────────────────
        print("Navigating to Instagram login page...")
        await page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        await dismiss_dialogs(page)

        if "accounts/login" not in page.url:
            print("Already logged in from saved session.")
        else:
            print("Waiting for login form...")
            user_xpath = "//input[@name='email' or @name='username' or contains(@autocomplete, 'username')]"
            pass_xpath = "//input[@name='pass' or @name='password' or @type='password']"
            submit_xpath = (
                "//form//div[@role='button' and (contains(., 'Log in') or contains(., 'Log In'))] "
                "| //form//input[@type='submit'] "
                "| //button[@type='submit']"
            )

            username_input = page.locator(f"xpath={user_xpath}").first
            password_input = page.locator(f"xpath={pass_xpath}").first

            await username_input.wait_for(state="visible", timeout=20000)

            print(f"Typing credentials for @{INSTAGRAM_USERNAME}...")
            await username_input.click()
            await username_input.fill("")
            await username_input.press_sequentially(INSTAGRAM_USERNAME, delay=60)
            await page.wait_for_timeout(300)

            await password_input.click()
            await password_input.fill("")
            await password_input.press_sequentially(INSTAGRAM_PASSWORD, delay=60)
            await page.wait_for_timeout(400)

            print("Clicking Log in...")
            submit_btn = page.locator(f"xpath={submit_xpath}").first
            if await submit_btn.is_visible(timeout=3000):
                await submit_btn.click()
            else:
                await password_input.press("Enter")

            print("Waiting for redirect...")
            for _ in range(60):
                await page.wait_for_timeout(1000)
                await dismiss_dialogs(page)
                if "accounts/login" not in page.url:
                    print(f"Logged in! Current URL: {page.url}")
                    break

        await dismiss_dialogs(page)
        if "accounts/onetap" in page.url or "accounts/" in page.url:
            await page.wait_for_timeout(1500)
            await dismiss_dialogs(page)
            if "accounts/onetap" in page.url:
                try:
                    not_now = page.locator('button:has-text("Not now"), [role="button"]:has-text("Not now")').first
                    if await not_now.is_visible(timeout=2000):
                        await not_now.click()
                except Exception:
                    pass
            if "accounts/" in page.url:
                await page.goto("https://www.instagram.com/", wait_until="networkidle", timeout=30000)

        await page.wait_for_timeout(1500)
        await dismiss_dialogs(page)

        # ── 2. If Reel mode: Fetch trending audio & create 9:16 Reel ─────────
        if as_reel:
            trending_audio_file = await fetch_trending_audio(page)
            print("\n🎬 Rendering 9:16 vertical Reel video...")
            upload_file = reel_maker.create_reel_video(
                image_path=IMAGE_PATH,
                audio_path=trending_audio_file,
                output_path=REEL_PATH,
                duration=7.0,
            )
            # Return to home feed to begin upload
            await page.goto("https://www.instagram.com/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1500)
            await dismiss_dialogs(page)

        # ── 3. Open New Post dialog ────────────────────────────────────────
        print("\nOpening Create dialog...")
        dialog = page.locator('[role="dialog"]')
        if not await dialog.is_visible():
            create_selectors = [
                'svg[aria-label="New post"]',
                'svg[aria-label="Create"]',
                'a[role="link"]:has(svg[aria-label="New post"])',
                'div[role="button"]:has(svg[aria-label="New post"])',
                'span:text-is("Create")',
                'a[role="link"]:has-text("Create")',
            ]
            opened_modal = False
            for sel in create_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.is_visible(timeout=2000):
                        await loc.click()
                        opened_modal = True
                        break
                except Exception:
                    continue

            if not opened_modal:
                await page.click('svg[aria-label="New post"], svg[aria-label="Create"]', timeout=8000)

            await page.wait_for_timeout(1500)

            # Submenu popup (select "Post")
            try:
                post_submenu = page.locator(
                    'a[role="link"]:not(:has(svg[aria-label="New post"])) span:text-is("Post"), '
                    'div[role="menuitem"]:has-text("Post"), '
                    'div:not(:has(svg[aria-label="New post"])) > span:text-is("Post")'
                ).first
                if await post_submenu.is_visible(timeout=3000):
                    await post_submenu.click()
                    print("Clicked 'Post' from Create menu.")
            except Exception:
                pass

        # ── 4. Upload file (reel.mp4 or image.png) ──────────────────────────
        print(f"Selecting file: {os.path.basename(upload_file)}...")
        file_input = page.locator('input[type="file"]').first
        try:
            await file_input.wait_for(state="attached", timeout=10000)
            await file_input.set_input_files(upload_file)
            print("File selected via input[type=file].")
        except Exception:
            async with page.expect_file_chooser(timeout=10000) as fc_info:
                select_btn = page.locator('button:has-text("Select from computer"), [role="button"]:has-text("Select from computer")').first
                await select_btn.click(timeout=6000)
            file_chooser = await fc_info.value
            await file_chooser.set_files(upload_file)
            print("File selected via file chooser.")

        await page.wait_for_timeout(3000)

        # Dismiss "Video posts are now shared as reels" notice if it appears
        try:
            ok_notice = page.locator('button:has-text("OK"), [role="button"]:has-text("OK")').first
            if await ok_notice.is_visible(timeout=2500):
                await ok_notice.click()
                print("Dismissed 'Video posts are now shared as reels' notice.")
        except Exception:
            pass

        # ── 5. Next (crop step) ────────────────────────────────────────────
        # For 9:16 Reels, select 9:16 or Original crop if crop tool is available
        if as_reel:
            try:
                crop_btn = page.locator('svg[aria-label="Select crop"], button:has(svg[aria-label="Select crop"])').first
                if await crop_btn.is_visible(timeout=2000):
                    await crop_btn.click()
                    await page.wait_for_timeout(400)
                    ratio_btn = page.locator('button:has-text("9:16"), [role="button"]:has-text("9:16"), button:has-text("Original")').first
                    if await ratio_btn.is_visible(timeout=1500):
                        await ratio_btn.click()
                        print("Selected 9:16 Reel aspect ratio.")
            except Exception:
                pass

        print("Proceeding past crop step...")
        next_btn = page.locator('div[role="button"]:text-is("Next"), button:text-is("Next"), [role="button"]:has-text("Next")').first
        await next_btn.wait_for(state="visible", timeout=12000)
        await next_btn.click()
        await page.wait_for_timeout(2500)

        # ── 6. Next (Cover photo / Trim for Reels, Filters for photos) ──────
        print("Proceeding past edit/trim step...")
        next_btn = page.locator('div[role="button"]:text-is("Next"), button:text-is("Next"), [role="button"]:has-text("Next")').first
        await next_btn.wait_for(state="visible", timeout=10000)
        await next_btn.click()
        await page.wait_for_timeout(2000)

        # ── 7. Caption ─────────────────────────────────────────────────────
        if caption:
            print("Adding caption...")
            caption_box = page.locator(
                'div[aria-label="Add a caption..."], '
                'div[aria-label="Write a caption..."], '
                'div[aria-label*="caption" i], '
                'div[role="textbox"][aria-label*="caption" i], '
                'div[contenteditable="true"]'
            ).first
            await caption_box.wait_for(state="visible", timeout=10000)
            await caption_box.click()
            await caption_box.press_sequentially(caption, delay=15)
            await page.wait_for_timeout(1000)

        # ── 8. Share ───────────────────────────────────────────────────────
        print(f"Sharing {'Reel' if as_reel else 'Post'}...")
        share_btn = page.locator('div[role="button"]:text-is("Share"), button:text-is("Share")').first
        await share_btn.wait_for(state="visible", timeout=10000)
        try:
            await share_btn.click(timeout=4000)
        except Exception:
            try:
                await share_btn.click(force=True, timeout=4000)
            except Exception:
                await share_btn.dispatch_event("click")

        # Wait for success screen
        print("Waiting for upload confirmation...")
        try:
            await page.wait_for_selector(
                'span:has-text("Your post has been shared"), '
                'span:has-text("Your reel has been shared"), '
                'h2:has-text("Your post has been shared"), '
                'h2:has-text("Your reel has been shared"), '
                'div:has-text("Your post has been shared"), '
                'div:has-text("Your reel has been shared"), '
                'img[alt="Animated checkmark"]',
                timeout=40000
            )
            print(f"🎉 {'Reel' if as_reel else 'Post'} shared successfully to Instagram!")
        except Exception:
            await page.wait_for_timeout(8000)
            print("Upload action submitted.")

        await context.close()


async def main():
    if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
        print("Error: Add INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD to your .env file.")
        sys.exit(1)

    if not os.path.exists(IMAGE_PATH):
        print(f"image.png not found at {IMAGE_PATH}")
        sys.exit(1)

    # Post as Reel by default; use '--photo' if a standard static post is desired
    as_reel = "--photo" not in sys.argv
    force_new = "--new-caption" in sys.argv

    caption = get_caption(IMAGE_PATH, is_reel=as_reel, force_regenerate=force_new)
    await upload_to_instagram(caption, as_reel=as_reel)


if __name__ == "__main__":
    asyncio.run(main())
