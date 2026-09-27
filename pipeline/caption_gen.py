import random

from openai import OpenAI

from pipeline.paths import getenv_clean

DEFAULT_MODEL = getenv_clean("GROQ_MODEL", "openai/gpt-oss-120b")

# Rotate the engagement mechanic so captions don't all read the same way — each
# drives a different signal the algorithm rewards (comments, saves, shares).
_HOOK_STYLES = [
    "End by asking a genuine, specific question that invites people to answer in the "
    "comments (not a generic 'what do you think?').",
    "End with a direct prompt to save this post for a moment they need it later.",
    "End with a prompt to tag/send this to one specific kind of person who needs to see it.",
    "End by asking people to comment which word or phrase in the quote hit them hardest.",
]


def _fallback_caption(quote: str, author: str) -> str:
    tag = author.lower().replace(" ", "")
    return (
        f"Words to sit with today, from {author}. Which line hit you hardest? \U0001f90d\n\n"
        f"#philosophy #stoicism #{tag} #wisdomquotes #reels #viral #mindset"
    )


def generate_caption(quote: str, author: str) -> str:
    """Generate an Instagram Reel caption reflecting on the quote, via Groq's LLM API."""
    api_key = getenv_clean("GROQ_API_KEY")
    if not api_key:
        print("No GROQ_API_KEY found — using fallback caption template.")
        return _fallback_caption(quote, author)

    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
    hook_style = random.choice(_HOOK_STYLES)

    try:
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{
                "role": "user",
                "content": (
                    f'Write a short, engaging Instagram Reel caption to go with this quote by {author}:\n\n'
                    f'"{quote}"\n\n'
                    "1-2 sentences reflecting on what it means today, warm and human tone. "
                    "Do not repeat the quote itself (it's already shown on screen). "
                    f"{hook_style} "
                    "This engagement hook is the most important part — it's what turns a passive "
                    "viewer into a comment/save/share, which is the whole point of this caption. "
                    "End with 6-10 relevant hashtags, mixing philosophy/stoicism tags with reach tags "
                    "like #reels or #viral. Only use a hashtag naming a country, culture, or "
                    "nationality if you are certain it is factually correct for this specific "
                    "philosopher — when unsure, skip it and use a generic philosophy/mindset tag "
                    "instead. Return only the caption, nothing else."
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
