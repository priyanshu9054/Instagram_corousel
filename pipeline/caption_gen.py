from openai import OpenAI

from pipeline.paths import getenv_clean

DEFAULT_MODEL = getenv_clean("GROQ_MODEL", "openai/gpt-oss-120b")


def _fallback_caption(quote: str, author: str) -> str:
    tag = author.lower().replace(" ", "")
    return (
        f"Words to sit with today, from {author}. \U0001f90d\n\n"
        f"#philosophy #stoicism #{tag} #wisdomquotes #reels #viral #mindset"
    )


def generate_caption(quote: str, author: str) -> str:
    """Generate an Instagram Reel caption reflecting on the quote, via Groq's LLM API."""
    api_key = getenv_clean("GROQ_API_KEY")
    if not api_key:
        print("No GROQ_API_KEY found — using fallback caption template.")
        return _fallback_caption(quote, author)

    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)

    try:
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{
                "role": "user",
                "content": (
                    f'Write a short, engaging Instagram Reel caption to go with this quote by {author}:\n\n'
                    f'"{quote}"\n\n'
                    "1-3 sentences reflecting on what it means today, warm and human tone. "
                    "Do not repeat the quote itself (it's already shown on screen). "
                    "End with 6-10 relevant hashtags, mixing philosophy/stoicism tags with reach tags "
                    "like #reels or #viral. Return only the caption, nothing else."
                ),
            }],
            max_tokens=350,
            temperature=0.8,
            extra_body={"reasoning_effort": "low"},
        )
        caption = (resp.choices[0].message.content or "").strip()
        return caption or _fallback_caption(quote, author)
    except Exception as e:
        print(f"Groq caption generation failed ({e}); using fallback template.")
        return _fallback_caption(quote, author)
