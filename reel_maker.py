import os
import subprocess
import imageio_ffmpeg

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


def get_audio_duration(audio_path: str) -> float:
    """Return the duration of the audio file in seconds using FFmpeg."""
    if not audio_path or not os.path.exists(audio_path):
        return 0.0
    cmd = [FFMPEG_EXE, "-i", audio_path]
    res = subprocess.run(cmd, capture_output=True, text=True)
    for line in res.stderr.splitlines():
        if "Duration:" in line:
            parts = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = parts.split(":")
            return float(h) * 3600 + float(m) * 60 + float(s)
    return 0.0


def create_reel_video(
    image_path: str,
    audio_path: str = None,
    output_path: str = "reel.mp4",
    duration: float = 7.0,
    audio_start_offset: float = 0.0,
) -> str:
    """
    Convert image_path + audio_path into a 9:16 vertical 1080x1920 Reel MP4 video.
    Background is an aesthetically blurred version of the image, foreground is the clean image.
    """
    if not os.path.isabs(output_path):
        output_path = os.path.join(os.path.dirname(os.path.abspath(image_path)), output_path)

    print(f"Creating Reel video from {os.path.basename(image_path)}...")

    # Determine duration
    if audio_path and os.path.exists(audio_path):
        audio_len = get_audio_duration(audio_path)
        if 4.0 <= audio_len <= 15.0:
            duration = audio_len
        elif audio_len > 15.0:
            duration = min(duration, 10.0)
    else:
        duration = 7.0

    fade_out_start = max(0.0, duration - 0.5)

    # Complex filter for stylish 9:16 vertical Reel:
    # 1. Background: scale image to fill 1080x1920, crop, apply heavy blur
    # 2. Foreground: scale image to fit nicely within 980x1700
    # 3. Overlay foreground centered on blurred background
    filter_complex = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg];"
        "[0:v]scale=980:1700:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
    )

    if audio_path and os.path.exists(audio_path):
        audio_filter = f"afade=t=in:ss=0:d=0.3,afade=t=out:st={fade_out_start:.2f}:d=0.5"
        # Seek into the track before looping so long songs start at their hook/highlight
        # point instead of a possibly-silent intro; harmless (clamped to 0) for short clips.
        safe_offset = max(0.0, audio_start_offset)
        cmd = [
            FFMPEG_EXE, "-y",
            "-loop", "1", "-i", image_path,
            # Loop the audio indefinitely so short clips fill the full reel duration
            # instead of truncating the video down to the clip's own length.
            "-ss", str(safe_offset), "-stream_loop", "-1", "-i", audio_path,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "1:a",
            "-af", audio_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(duration),
            output_path,
        ]
    else:
        # Fallback silent audio so Instagram accepts it as a valid video with audio stream
        cmd = [
            FFMPEG_EXE, "-y",
            "-loop", "1", "-i", image_path,
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "1:a",
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-t", str(duration),
            output_path,
        ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"FFmpeg error: {res.stderr[:500]}")
        raise RuntimeError(f"Failed to generate Reel video: {res.stderr[:300]}")

    print(f"✅ Reel video created successfully: {output_path} ({duration:.1f}s, 1080x1920)")
    return output_path


def extract_thumbnail(video_path: str, thumbnail_path: str = None) -> str:
    """
    Grab the first frame of the video as a JPEG thumbnail. Used to hand instagrapi a
    ready-made cover image so it skips its own MoviePy-based thumbnail generation.
    """
    if thumbnail_path is None:
        thumbnail_path = os.path.splitext(video_path)[0] + "_thumb.jpg"

    cmd = [
        FFMPEG_EXE, "-y",
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        thumbnail_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to extract thumbnail: {res.stderr[:300]}")
    return thumbnail_path


if __name__ == "__main__":
    img = os.path.join(os.path.dirname(__file__), "image.png")
    out = create_reel_video(img, duration=5.0)
    print("Test output:", out)
