import os
import subprocess
import imageio_ffmpeg

from pipeline.paths import getenv_clean

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


def _ken_burns_enabled() -> bool:
    # Re-enabled: the earlier SIGKILL/exit -9 failures turned out to be caused by
    # Railway's ~15s synchronous-request ceiling (confirmed via a pure CPU-bound
    # /debug/burn test failing identically with zero ffmpeg involved), not by
    # zoompan's memory use — /post-reel now runs the pipeline in a background job
    # (pipeline/jobs.py), so the extra encoding time is no longer time-constrained.
    # Set REEL_KEN_BURNS=0 to fall back to a static frame if needed.
    return getenv_clean("REEL_KEN_BURNS", "1") not in ("0", "false", "False")


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

    # Duration is always exactly what the caller asked for — the audio (whether a
    # full song trimmed via -t, or a short clip looped via -stream_loop) is fit to
    # this length, never the other way around.
    fade_out_start = max(0.0, duration - 0.5)

    # Complex filter for stylish 9:16 vertical Reel:
    # 1. Background: scale image to fill 1080x1920, crop, apply heavy blur
    # 2. Foreground: scale image to fit nicely within 980x1700
    # 3. Overlay foreground centered on blurred background
    # 4. Ken Burns (optional, see _ken_burns_enabled): slow zoom-in on the composed
    #    frame — a static image reads as low-effort in the Reels feed; motion holds
    #    watch-time, which the algorithm weighs heavily for reach. zoompan generates
    #    the full frame sequence itself from a single input frame (via d=total_frames)
    #    — combining it with a looped "-loop 1" input instead resets its internal
    #    zoom state every frame and produces no visible motion.
    # boxblur radius kept modest (was 25:5) — full-radius blur plus zoompan's
    # per-frame regeneration was part of what OOM-killed encoding on Railway's
    # memory-constrained container.
    fps = 25
    ken_burns = _ken_burns_enabled()
    if ken_burns:
        total_frames = max(1, round(duration * fps))
        zoom_expr = "min(zoom+0.0008,1.12)"
        filter_complex = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=12:2[bg];"
            "[0:v]scale=980:1700:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,"
            f"zoompan=z='{zoom_expr}':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps}[v]"
        )
        image_input_args = ["-i", image_path]  # single frame; zoompan expands it
    else:
        filter_complex = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=12:2[bg];"
            "[0:v]scale=980:1700:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
        )
        image_input_args = ["-loop", "1", "-i", image_path]  # continuous static frame

    # ultrafast + capped threads: ffmpeg sizes its internal encoding buffers off the
    # HOST's CPU count, which on a resource-limited container vastly overshoots what
    # memory is actually available — this combo is what actually fixes the OOM-kill,
    # not just the lighter blur above.
    encode_args = ["-c:v", "libx264", "-preset", "ultrafast", "-threads", "2"]
    # Global options — must precede the first -i. -threads only caps the encoder;
    # filter threading is separate and defaults to the HOST's detected CPU count
    # (48 on Railway's shared host, though the container is capped at ~1GB memory),
    # which was very likely the real driver behind ffmpeg getting SIGKILL'd even on
    # the simplest possible encode.
    global_args = ["-y", "-filter_threads", "1", "-filter_complex_threads", "1"]

    if audio_path and os.path.exists(audio_path):
        audio_filter = f"afade=t=in:ss=0:d=0.3,afade=t=out:st={fade_out_start:.2f}:d=0.5"
        # Seek into the track before looping so long songs start at their hook/highlight
        # point instead of a possibly-silent intro; harmless (clamped to 0) for short clips.
        safe_offset = max(0.0, audio_start_offset)
        cmd = [
            FFMPEG_EXE, *global_args,
            *image_input_args,
            # Loop the audio indefinitely so short clips fill the full reel duration
            # instead of truncating the video down to the clip's own length.
            "-ss", str(safe_offset), "-stream_loop", "-1", "-i", audio_path,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "1:a",
            "-af", audio_filter,
            *encode_args,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(duration),
            output_path,
        ]
    else:
        # Fallback silent audio so Instagram accepts it as a valid video with audio stream
        cmd = [
            FFMPEG_EXE, *global_args,
            *image_input_args,
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "1:a",
            *encode_args,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-t", str(duration),
            output_path,
        ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        # ffmpeg's actual error is at the END of stderr — the start is just a
        # version/build banner, which was silently eating the whole truncation
        # budget and hiding the real failure reason. Return code -9/137 (SIGKILL)
        # with no explicit ffmpeg error usually means the OS/container OOM-killed it.
        print(f"FFmpeg error (exit {res.returncode}): {res.stderr[-1500:]}")
        raise RuntimeError(f"Failed to generate Reel video (exit code {res.returncode}): {res.stderr[-800:]}")

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
        raise RuntimeError(f"Failed to extract thumbnail: {res.stderr[-800:]}")
    return thumbnail_path


if __name__ == "__main__":
    img = os.path.join(os.path.dirname(__file__), "image.png")
    out = create_reel_video(img, duration=5.0)
    print("Test output:", out)
