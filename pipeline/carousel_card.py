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


def _generate_reflection(quote: str, author: str) -> str:
    """A single reflective sentence for the carousel's second slide (not the IG caption)."""
    api_key = getenv_clean("GROQ_API_KEY")
    if not api_key:
        return "Sit with that for a moment."

    try:
        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
        model = getenv_clean("GROQ_MODEL", "openai/gpt-oss-120b")
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": (
                    f'One short, dark, reflective sentence (max ~18 words) expanding on this '
                    f'{author} quote for a philosophy carousel slide:\n\n"{quote}"\n\n'
                    "No hashtags, no quotation marks, no attribution. Return only the sentence."
                ),
            }],
            max_tokens=200,
            temperature=0.8,
            extra_body={"reasoning_effort": "low"},
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or "Sit with that for a moment."
    except Exception as e:
        print(f"Reflection generation failed ({e}); using fallback line.")
        return "Sit with that for a moment."


def _dark_backdrop(portrait_file: str) -> Image.Image:
    """A heavily blurred, darkened version of a portrait to use behind slide text."""
    img = Image.open(PORTRAITS_DIR / portrait_file).convert("RGB")
    img = img.resize(CARD_SIZE)
    img = img.convert("L").convert("RGB")
    img = img.filter(ImageFilter.GaussianBlur(30))
    overlay = Image.new("RGB", CARD_SIZE, (8, 8, 8))
    return Image.blend(img, overlay, 0.75)


def render_reflection_slide(text: str, portrait_file: str, output_path: Path) -> Path:
    img = _dark_backdrop(portrait_file)
    draw = ImageDraw.Draw(img)

    margin_x = 110
    max_width = CARD_SIZE[0] - 2 * margin_x
    quoted = f"“{text}”"
    font, lines, line_height = quote_card.fit_font(
        draw, quoted, max_width, max_height=500, font_path=FONT_BOLD, start_size=58,
    )

    block_height = line_height * len(lines)
    y = (CARD_SIZE[1] - block_height) / 2
    for line in lines:
        w = draw.textbbox((0, 0), line, font=font)[2]
        x = (CARD_SIZE[0] - w) / 2
        draw.text((x, y), line, font=font, fill=(235, 235, 235))
        y += line_height

    output_path = Path(output_path)
    img.save(output_path, "PNG")
    return output_path


def render_cta_slide(handle: str, portrait_file: str, output_path: Path) -> Path:
    img = _dark_backdrop(portrait_file)
    draw = ImageDraw.Draw(img)

    heading_font = ImageFont.truetype(FONT_BOLD, 60)
    sub_font = ImageFont.truetype(FONT_REGULAR, 38)

    lines = [
        ("Save this for later", heading_font, (255, 255, 255)),
        (f"Follow @{handle}", sub_font, (220, 220, 220)),
        ("for daily philosophy", sub_font, (220, 220, 220)),
    ]

    total_height = sum(draw.textbbox((0, 0), t, font=f)[3] + 24 for t, f, _ in lines)
    y = (CARD_SIZE[1] - total_height) / 2
    for text, font, color in lines:
        w = draw.textbbox((0, 0), text, font=font)[2]
        x = (CARD_SIZE[0] - w) / 2
        draw.text((x, y), text, font=font, fill=color)
        y += draw.textbbox((0, 0), text, font=font)[3] + 24

    output_path = Path(output_path)
    img.save(output_path, "PNG")
    return output_path


def generate(output_dir: Path, preferred_author: str | None = None) -> dict:
    """
    Build a 3-slide carousel: hook quote card, a reflective follow-up slide, and a
    save/follow CTA slide. Returns the chosen quote metadata plus the slide paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chosen = quote_card.pick_quote(preferred_author=preferred_author)
    quote, author, portrait = chosen["quote"], chosen["author"], chosen["portrait"]

    slide1 = quote_card.render_card(quote, author, portrait, output_dir / "slide_1.png")

    reflection = _generate_reflection(quote, author)
    slide2 = render_reflection_slide(reflection, portrait, output_dir / "slide_2.png")

    handle = getenv_clean("INSTAGRAM_USERNAME", "")
    slide3 = render_cta_slide(handle, portrait, output_dir / "slide_3.png")

    return {**chosen, "reflection": reflection, "slides": [str(slide1), str(slide2), str(slide3)]}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    result = generate(ROOT / "assets" / "_carousel_preview")
    print(f"Carousel for {result['author']}: {result['quote']}")
    print(f"Reflection: {result['reflection']}")
    print("Slides:", result["slides"])
