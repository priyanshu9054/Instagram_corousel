import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from openai import OpenAI

from pipeline import quote_card
from pipeline.paths import STATIC_ASSETS_DIR, getenv_clean

ROOT = Path(__file__).resolve().parent.parent
PORTRAITS_DIR = STATIC_ASSETS_DIR / "portraits"
CARD_SIZE = quote_card.CARD_SIZE
FONT_BOLD = quote_card.FONT_BOLD
FONT_REGULAR = quote_card.FONT_REGULAR

# 7 slides matches the 8-10 slide range research finds performs best (dwell time /
# swipe-through), structured around: Hook -> Retention (3 slides) -> Shareability ->
# Profile conversion.
SLIDE_COUNT = 7


def _fallback_copy(quote: str, author: str) -> dict:
    return {
        "hook": "One idea that changes everything",
        "unpack": f"{author} is saying how we respond matters more than what actually happens to us.",
        "relate": "We all know the spiral of replaying something we can't undo or control.",
        "apply": "Next time you catch yourself spiraling, pause and ask: is this actually in my control?",
        "shareable": "You can't control what happens. You can always control how you meet it.",
        "cta_benefit": "handle whatever life throws at you",
    }


def _clean_cta_benefit(text: str) -> str:
    """
    Strip a redundant 'Follow for wisdom that helps you ...' prefix if the model
    echoes the template back instead of just completing it (a real, observed failure
    mode) — render_cta_slide builds that sentence itself from just the tail phrase.
    """
    text = text.strip().rstrip(".").strip()
    text = re.sub(r"^follow\s+for\s+wisdom\s+that\s+helps\s+you\s+", "", text, flags=re.IGNORECASE)
    return text or "handle whatever life throws at you"


def _generate_slide_copy(quote: str, author: str) -> dict:
    """
    One Groq call generates every piece of carousel copy at once (hook, explanation,
    relatable framing, actionable tip, shareable takeaway, CTA benefit) as JSON —
    cheaper and more consistent-in-tone than separate calls per slide.
    """
    fallback = _fallback_copy(quote, author)
    api_key = getenv_clean("GROQ_API_KEY")
    if not api_key:
        return fallback

    try:
        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
        model = getenv_clean("GROQ_MODEL", "openai/gpt-oss-120b")
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": (
                    "You are writing a 7-slide Instagram carousel for a dark, introspective "
                    f"stoic/philosophy page, built around this quote by {author}:\n\n"
                    f"\"{quote}\"\n\n"
                    "Reply with ONLY a JSON object, no other text, with exactly these keys:\n"
                    '{"hook": "...", "unpack": "...", "relate": "...", "apply": "...", '
                    '"shareable": "...", "cta_benefit": "..."}\n\n'
                    "hook: a 5-8 word curiosity headline that teases the quote's idea WITHOUT "
                    "quoting it or naming the philosopher — it must create a real curiosity gap "
                    "that only swiping resolves. No punctuation gimmicks, no emoji.\n"
                    "unpack: 1-2 short sentences explaining what the quote actually means, in "
                    "plain modern language, no jargon.\n"
                    "relate: 1-2 sentences connecting it to one specific, common modern struggle "
                    "(overthinking, comparison, burnout, criticism, procrastination, etc).\n"
                    "apply: one concrete, specific small action someone can try today — must be "
                    "actionable, not vague.\n"
                    "shareable: a punchy, quotable one-line takeaway in YOUR OWN words (not the "
                    "original quote) that works as a standalone screenshot.\n"
                    "cta_benefit: ONLY the 4-7 word ending phrase itself (e.g. 'stay calm under "
                    "pressure') that would complete the sentence 'Follow for wisdom that helps "
                    "you ___'. Do NOT include the words 'Follow' or 'for wisdom that helps you' "
                    "in your answer — just the ending phrase, a concrete benefit, not generic."
                ),
            }],
            max_tokens=600,
            temperature=0.8,
            extra_body={"reasoning_effort": "low"},
        )
        content = (resp.choices[0].message.content or "").strip().strip("`")
        if content.lower().startswith("json"):
            content = content[4:].strip()
        data = json.loads(content)
        for key, default in fallback.items():
            if not data.get(key):
                data[key] = default
        data["cta_benefit"] = _clean_cta_benefit(data["cta_benefit"])
        return data
    except Exception as e:
        print(f"Slide copy generation failed ({e}); using fallback copy.")
        return fallback


def _dark_backdrop(portrait_file: str) -> Image.Image:
    """A heavily blurred, darkened version of a portrait to use behind slide text."""
    img = Image.open(PORTRAITS_DIR / portrait_file).convert("RGB")
    img = img.resize(CARD_SIZE)
    img = img.convert("L").convert("RGB")
    img = img.filter(ImageFilter.GaussianBlur(30))
    overlay = Image.new("RGB", CARD_SIZE, (8, 8, 8))
    return Image.blend(img, overlay, 0.75)


def _stamp_progress(img: Image.Image, slide_num: int, total: int = SLIDE_COUNT) -> None:
    """Small 'N / total' footer — signals structure/length upfront, a known retention lever."""
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_REGULAR, 26)
    text = f"{slide_num} / {total}"
    w = draw.textbbox((0, 0), text, font=font)[2]
    draw.text((CARD_SIZE[0] - w - 40, 40), text, font=font, fill=(170, 170, 170))


def render_hook_slide(hook_text: str, portrait_file: str, slide_num: int, output_path: Path) -> Path:
    """Slide 1: portrait backdrop, one bold curiosity-gap headline. No quote/author shown yet."""
    img = Image.open(PORTRAITS_DIR / portrait_file).convert("RGB")
    from PIL import ImageOps, ImageEnhance
    img = ImageOps.fit(img, CARD_SIZE, method=Image.LANCZOS, centering=(0.5, 0.35))
    img = ImageOps.grayscale(img).convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.1)
    img = ImageEnhance.Brightness(img).enhance(0.45)
    overlay = Image.new("RGB", CARD_SIZE, (5, 5, 5))
    img = Image.blend(img, overlay, 0.55)

    draw = ImageDraw.Draw(img)
    margin_x = 90
    font, lines, line_height = quote_card.fit_font(
        draw, hook_text, CARD_SIZE[0] - 2 * margin_x, max_height=700,
        font_path=FONT_BOLD, start_size=88, min_size=48,
    )
    block_height = line_height * len(lines)
    y = (CARD_SIZE[1] - block_height) / 2
    for line in lines:
        w = draw.textbbox((0, 0), line, font=font)[2]
        x = (CARD_SIZE[0] - w) / 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += line_height

    swipe_font = ImageFont.truetype(FONT_REGULAR, 32)
    swipe_text = "Swipe for more"
    sw = draw.textbbox((0, 0), swipe_text, font=swipe_font)[2]
    draw.text(((CARD_SIZE[0] - sw) / 2, CARD_SIZE[1] - 90), swipe_text, font=swipe_font, fill=(200, 200, 200))

    _stamp_progress(img, slide_num)
    output_path = Path(output_path)
    img.save(output_path, "PNG")
    return output_path


def render_text_slide(
    label: str, text: str, portrait_file: str, slide_num: int, output_path: Path,
    font_size: int = 58, quote_style: bool = False,
) -> Path:
    """Dark blurred-backdrop text slide with a small caps label — used for Unpack/Relate/Apply/Shareable."""
    img = _dark_backdrop(portrait_file)
    draw = ImageDraw.Draw(img)

    if label:
        label_font = ImageFont.truetype(FONT_BOLD, 30)
        label_text = label.upper()
        lw = draw.textbbox((0, 0), label_text, font=label_font)[2]
        draw.text(((CARD_SIZE[0] - lw) / 2, 340), label_text, font=label_font, fill=(190, 190, 190))

    margin_x = 110
    max_width = CARD_SIZE[0] - 2 * margin_x
    display_text = f"“{text}”" if quote_style else text
    font, lines, line_height = quote_card.fit_font(
        draw, display_text, max_width, max_height=650, font_path=FONT_BOLD, start_size=font_size,
    )

    block_height = line_height * len(lines)
    y = (CARD_SIZE[1] - block_height) / 2 + (30 if label else 0)
    for line in lines:
        w = draw.textbbox((0, 0), line, font=font)[2]
        x = (CARD_SIZE[0] - w) / 2
        draw.text((x, y), line, font=font, fill=(235, 235, 235))
        y += line_height

    _stamp_progress(img, slide_num)
    output_path = Path(output_path)
    img.save(output_path, "PNG")
    return output_path


def render_cta_slide(handle: str, benefit: str, portrait_file: str, slide_num: int, output_path: Path) -> Path:
    """Final slide: ONE clear, benefit-driven CTA (profile conversion -> followers)."""
    img = _dark_backdrop(portrait_file)
    draw = ImageDraw.Draw(img)

    heading_font = ImageFont.truetype(FONT_BOLD, 56)
    sub_font = ImageFont.truetype(FONT_REGULAR, 36)
    margin_x = 100
    max_width = CARD_SIZE[0] - 2 * margin_x

    heading_lines = ["Follow", f"@{handle}"]
    sub_text = f"for wisdom that helps you {benefit}"
    sub_font_fit, sub_lines, sub_line_height = quote_card.fit_font(
        draw, sub_text, max_width, max_height=250, font_path=FONT_REGULAR, start_size=36, min_size=26,
    )

    total_height = len(heading_lines) * 72 + 20 + len(sub_lines) * sub_line_height
    y = (CARD_SIZE[1] - total_height) / 2

    for line in heading_lines:
        w = draw.textbbox((0, 0), line, font=heading_font)[2]
        draw.text(((CARD_SIZE[0] - w) / 2, y), line, font=heading_font, fill=(255, 255, 255))
        y += 72

    y += 20
    for line in sub_lines:
        w = draw.textbbox((0, 0), line, font=sub_font_fit)[2]
        draw.text(((CARD_SIZE[0] - w) / 2, y), line, font=sub_font_fit, fill=(210, 210, 210))
        y += sub_line_height

    _stamp_progress(img, slide_num)
    output_path = Path(output_path)
    img.save(output_path, "PNG")
    return output_path


def generate(output_dir: Path, preferred_author: str | None = None) -> dict:
    """
    Build a 7-slide growth-funnel carousel:
    1 Hook (curiosity gap) -> 2 Reveal (quote+author) -> 3 Unpack -> 4 Relate ->
    5 Apply -> 6 Shareable takeaway -> 7 CTA (profile conversion).
    Returns the chosen quote metadata, generated copy, and slide paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chosen = quote_card.pick_quote(preferred_author=preferred_author)
    quote, author, portrait = chosen["quote"], chosen["author"], chosen["portrait"]
    copy = _generate_slide_copy(quote, author)
    handle = getenv_clean("INSTAGRAM_USERNAME", "")

    slides = [
        render_hook_slide(copy["hook"], portrait, 1, output_dir / "slide_1.png"),
        quote_card.render_card(quote, author, portrait, output_dir / "slide_2.png"),
        render_text_slide("What it means", copy["unpack"], portrait, 3, output_dir / "slide_3.png"),
        render_text_slide("Why it matters", copy["relate"], portrait, 4, output_dir / "slide_4.png"),
        render_text_slide("Try this today", copy["apply"], portrait, 5, output_dir / "slide_5.png"),
        render_text_slide("Remember this", copy["shareable"], portrait, 6, output_dir / "slide_6.png",
                           font_size=64, quote_style=True),
        render_cta_slide(handle, copy["cta_benefit"], portrait, 7, output_dir / "slide_7.png"),
    ]
    # slide 2 (quote_card.render_card) doesn't carry the carousel's progress-number
    # footer since that function is shared with the plain reel-content path — stamp
    # it here instead of duplicating render_card's whole layout.
    reveal_img = Image.open(slides[1])
    _stamp_progress(reveal_img, 2)
    reveal_img.save(slides[1])

    return {**chosen, "copy": copy, "slides": [str(s) for s in slides]}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    result = generate(ROOT / "assets" / "_carousel_preview")
    print(f"Carousel for {result['author']}: {result['quote']}")
    print(json.dumps(result["copy"], indent=2))
    print("Slides:", result["slides"])
