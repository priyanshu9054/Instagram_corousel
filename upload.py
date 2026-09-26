import os
import sys
import time
import base64
import requests
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

IG_USER_ID = os.getenv("Id")
ACCESS_TOKEN = os.getenv("Token")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
IMAGE_PATH = os.path.join(os.path.dirname(__file__), "image.png")

GRAPH_API = "https://graph.facebook.com/v19.0"


def generate_caption(image_path: str) -> str:
    """Use Groq vision model (qwen/qwen3.8-27b) or OpenAI to generate an Instagram caption + hashtags."""
    if GROQ_API_KEY:
        print("Generating caption with Groq...")
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=GROQ_API_KEY,
        )
        model = "qwen/qwen3.8-27b"
    elif OPENAI_API_KEY:
        print("Generating caption with GPT-4o...")
        client = OpenAI(api_key=OPENAI_API_KEY)
        model = "gpt-4o"
    else:
        print("Error: Neither GROQ_API_KEY nor OPENAI_API_KEY found in environment.")
        sys.exit(1)

    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_data}",
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Write an engaging Instagram caption for this image. "
                            "Keep it concise, natural, and end with 5-10 relevant hashtags. "
                            "Return only the caption text and hashtags, nothing else."
                        ),
                    },
                ],
            }
        ],
        max_tokens=300,
    )

    caption = resp.choices[0].message.content.strip()
    print(f"Caption:\n{caption}\n")
    return caption


def upload_to_public_host(image_path: str) -> str:
    """Upload image to a temporary public host and return the URL."""
    print("Uploading image to temporary host...")

    # catbox.moe — free, no account needed
    with open(image_path, "rb") as f:
        resp = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": f},
            timeout=30,
        )
    if resp.ok and resp.text.startswith("https://"):
        url = resp.text.strip()
        print(f"Public URL: {url}")
        return url

    # fallback: litterbox.catbox.moe (1 day expiry)
    with open(image_path, "rb") as f:
        resp = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "1d"},
            files={"fileToUpload": f},
            timeout=30,
        )
    if resp.ok and resp.text.startswith("https://"):
        url = resp.text.strip()
        print(f"Public URL (litterbox): {url}")
        return url

    raise RuntimeError(f"All image hosts failed. Last response: {resp.text}")


def create_media_container(image_url: str, caption: str) -> str:
    """Step 1: Create a media container on Instagram."""
    print("Creating Instagram media container...")
    resp = requests.post(
        f"{GRAPH_API}/{IG_USER_ID}/media",
        params={
            "image_url": image_url,
            "caption": caption,
            "access_token": ACCESS_TOKEN,
        },
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        print(f"Error: {data['error']}")
        sys.exit(1)
    creation_id = data["id"]
    print(f"Container ID: {creation_id}")
    return creation_id


def wait_for_container(creation_id: str, retries: int = 10, delay: int = 3):
    """Poll until the container status is FINISHED."""
    print("Waiting for container to be ready...")
    for _ in range(retries):
        resp = requests.get(
            f"{GRAPH_API}/{creation_id}",
            params={"fields": "status_code", "access_token": ACCESS_TOKEN},
            timeout=15,
        )
        status = resp.json().get("status_code", "")
        print(f"  Status: {status}")
        if status == "FINISHED":
            return
        if status == "ERROR":
            print("Container processing failed.")
            sys.exit(1)
        time.sleep(delay)
    print("Timed out waiting for container.")
    sys.exit(1)


def publish_media(creation_id: str) -> str:
    """Step 2: Publish the media container."""
    print("Publishing post...")
    resp = requests.post(
        f"{GRAPH_API}/{IG_USER_ID}/media_publish",
        params={"creation_id": creation_id, "access_token": ACCESS_TOKEN},
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        print(f"Error: {data['error']}")
        sys.exit(1)
    post_id = data["id"]
    print(f"Posted! Post ID: {post_id}")
    return post_id


def main():
    if not os.path.exists(IMAGE_PATH):
        print(f"image.png not found at {IMAGE_PATH}")
        sys.exit(1)

    caption = generate_caption(IMAGE_PATH)
    image_url = upload_to_public_host(IMAGE_PATH)
    creation_id = create_media_container(image_url, caption)
    wait_for_container(creation_id)
    publish_media(creation_id)
    print("Done.")


if __name__ == "__main__":
    main()
