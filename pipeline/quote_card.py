import json
import random
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance

from pipeline.paths import STATIC_ASSETS_DIR, STATE_DIR, getenv_clean

ROOT = Path(__file__).resolve().parent.parent
QUOTES_FILE = STATIC_ASSETS_DIR / "quotes.json"
PORTRAITS_DIR = STATIC_ASSETS_DIR / "portraits"
SHUFFLE_STATE_FILE = STATE_DIR / ".quote_shuffle.json"

CARD_SIZE = (1080, 1350)
# Bundled (OFL-licensed) fonts — not the macOS system Georgia, which can't be
# redistributed and wouldn't exist inside a Linux/Docker container anyway.
FONT_BOLD = str(STATIC_ASSETS_DIR / "fonts" / "PTSerif-Bold.ttf")
FONT_REGULAR = str(STATIC_ASSETS_DIR / "fonts" / "PTSerif-Regular.ttf")


def _load_quotes() -> list[dict]:
    with open(QUOTES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_shuffle_state() -> dict:
    if not SHUFFLE_STATE_FILE.exists():
        return {}
    try:
        return json.loads(SHUFFLE_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_shuffle_state(state: dict) -> None:
    SHUFFLE_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def pick_quote(preferred_author: str | None = None) -> dict:
    """
    Shuffle-bag picker: every quote in scope (a specific philosopher's pool, or the
    whole set) gets used exactly once before any of them repeat, instead of picking
    with replacement (which could hand back the same quote 2-3 times before ever
    reaching the others). The bag reshuffles and refills only once fully emptied.
    """
    quotes = _load_quotes()
    if preferred_author:
        by_author = [q for q in quotes if q["author"] == preferred_author]
        quotes = by_author or quotes

    scope_key = preferred_author or "__all__"
    all_texts = [q["quote"] for q in quotes]
    by_text = {q["quote"]: q for q in quotes}

    state = _load_shuffle_state()
    remaining = [t for t in state.get(scope_key, []) if t in by_text]

    if not remaining:
        remaining = all_texts.copy()
        random.shuffle(remaining)
        # Avoid the bag's own first pick matching the very last thing this scope
        # handed out right before refilling (the seam between two cycles).
        last_served = state.get(f"{scope_key}__last")
        if len(remaining) > 1 and remaining[0] == last_served:
            remaining.append(remaining.pop(0))

    chosen_text = remaining.pop(0)
    state[scope_key] = remaining
    state[f"{scope_key}__last"] = chosen_text
    _save_shuffle_state(state)

    return by_text[chosen_text]


def fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, max_height: int,
              font_path: str, start_size: int, min_size: int = 34):
    """Shrink font size until the wrapped quote fits within max_width x max_height."""
    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        avg_char_w = font.getbbox("Mo")[2] / 2 or 1
        wrap_width = max(10, int(max_width / avg_char_w))
        lines = textwrap.wrap(text, width=wrap_width) or [text]

        line_height = font.getbbox("Mgjy")[3] + 12
        total_height = line_height * len(lines)

        widest = max(draw.textbbox((0, 0), line, font=font)[2] for line in lines)
        if total_height <= max_height and widest <= max_width:
            return font, lines, line_height
        size -= 4
    font = ImageFont.truetype(font_path, min_size)
    lines = textwrap.wrap(text, width=max(10, int(max_width / (font.getbbox("Mo")[2] / 2 or 1))))
    line_height = font.getbbox("Mgjy")[3] + 12
    return font, lines, line_height


def render_card(quote: str, author: str, portrait_file: str, output_path: Path) -> Path:
    """Render a philosopher-portrait quote card matching the account's visual style."""
    portrait_path = PORTRAITS_DIR / portrait_file
    img = Image.open(portrait_path).convert("RGB")

    # Subtle randomized variation — same portrait/quote pair (inevitable once the
    # quote pool cycles fully, ~114 days in) still won't render pixel-identical.
    # Ranges kept tight so the brand's look stays consistent, not noticeably random.
    centering_y = random.uniform(0.28, 0.42)
    contrast = random.uniform(1.02, 1.18)
    brightness = random.uniform(0.50, 0.60)
    gradient_darkness = random.randint(0, 20)  # extra RGB offset toward black

    # Cover-crop to the card aspect ratio.
    img = ImageOps.fit(img, CARD_SIZE, method=Image.LANCZOS, centering=(0.5, centering_y))

    # Desaturate and darken for a moody monochrome look, matching the reference style.
    img = ImageOps.grayscale(img).convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = ImageEnhance.Brightness(img).enhance(brightness)

    # Vertical gradient overlay: darkest where the text sits (lower two-thirds).
    gradient = Image.new("L", (1, CARD_SIZE[1]), color=0)
    for y in range(CARD_SIZE[1]):
        t = y / CARD_SIZE[1]
        alpha = int(60 + 140 * min(1.0, max(0.0, (t - 0.25) / 0.6)))
        gradient.putpixel((0, y), alpha)
    gradient = gradient.resize(CARD_SIZE)
    overlay_shade = 10 + gradient_darkness
    overlay = Image.new("RGB", CARD_SIZE, color=(overlay_shade, overlay_shade, overlay_shade))
    img = Image.composite(overlay, img, gradient)

    draw = ImageDraw.Draw(img)
    margin_x = 90
    max_text_width = CARD_SIZE[0] - 2 * margin_x
    quote_text = f"“{quote}”"

    font, lines, line_height = fit_font(
        draw, quote_text, max_text_width, max_height=780,
        font_path=FONT_BOLD, start_size=64,
    )

    block_height = line_height * len(lines)
    start_y = CARD_SIZE[1] - 260 - block_height

    y = start_y
    for line in lines:
        w = draw.textbbox((0, 0), line, font=font)[2]
        x = (CARD_SIZE[0] - w) / 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += line_height

    author_font = ImageFont.truetype(FONT_REGULAR, 40)
    author_text = f"— {author}"
    aw = draw.textbbox((0, 0), author_text, font=author_font)[2]
    draw.text(((CARD_SIZE[0] - aw) / 2, y + 30), author_text, font=author_font, fill=(230, 230, 230))

    # Subtle handle watermark: keeps the brand attached when this gets screenshotted
    # or reposted elsewhere, and nudges viewers who see it that way back to a follow.
    handle = getenv_clean("INSTAGRAM_USERNAME", "")
    if handle:
        handle_font = ImageFont.truetype(FONT_REGULAR, 28)
        handle_text = f"@{handle}"
        hw = draw.textbbox((0, 0), handle_text, font=handle_font)[2]
        draw.text(((CARD_SIZE[0] - hw) / 2, CARD_SIZE[1] - 55), handle_text, font=handle_font, fill=(160, 160, 160))

    output_path = Path(output_path)
    img.save(output_path, "PNG")
    return output_path


def generate(output_path: Path, preferred_author: str | None = None) -> dict:
    """Pick a quote and render its card in one step. Returns the chosen quote metadata."""
    chosen = pick_quote(preferred_author=preferred_author)
    render_card(chosen["quote"], chosen["author"], chosen["portrait"], output_path)
    return chosen


if __name__ == "__main__":
    result = generate(ROOT / "image.png")
    print(f"Generated card for {result['author']}: {result['quote']}")
