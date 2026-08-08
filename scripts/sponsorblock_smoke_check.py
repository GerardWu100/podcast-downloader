#!/usr/bin/env python3
"""Manual SponsorBlock check against a live YouTube video.

This hits the network and downloads a real file, so it is deliberately kept out
of ``tests/`` and out of the offline suite. Run it by hand when you want to see
whether SponsorBlock still trims sponsor segments as the downloader expects:

    uv run --with "yt-dlp[default]" python scripts/sponsorblock_smoke_check.py

Success looks like an MP3 in ``downloads/`` that is shorter than the source
video by roughly the length of its sponsor segments.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# A video that SponsorBlock has segments for. Replace it if the video is ever
# taken down or its segments are removed.
SAMPLE_VIDEO_URL = "https://www.youtube.com/watch?v=5KmpT-BoVf4"
OUTPUT_DIRECTORY = PROJECT_ROOT / "downloads"
OUTPUT_BASENAME = "sponsorblock_smoke_check"

# Mirror the production SponsorBlock categories used by the downloader CLI.
SPONSORBLOCK_CATEGORIES = {"sponsor", "selfpromo"}
AUDIO_CODEC = "mp3"
AUDIO_QUALITY_KBPS = "192"


def main() -> None:
    """Download one video with sponsor trimming and report what was produced."""
    try:
        import yt_dlp
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Install the live-only dependency for this run: "
            'uv run --with "yt-dlp[default]" python '
            "scripts/sponsorblock_smoke_check.py"
        ) from exc

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output_template = str(OUTPUT_DIRECTORY / f"{OUTPUT_BASENAME}.%(ext)s")

    ydl_options = {
        "format": "bestaudio/best",
        "sponsorblock_remove": SPONSORBLOCK_CATEGORIES,
        "outtmpl": output_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": AUDIO_CODEC,
                "preferredquality": AUDIO_QUALITY_KBPS,
            }
        ],
        "writeinfojson": False,
        "writedescription": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
    }

    print(f"Removing SponsorBlock categories: {sorted(SPONSORBLOCK_CATEGORIES)}")
    print(f"Downloading {SAMPLE_VIDEO_URL} to {OUTPUT_DIRECTORY}")

    with yt_dlp.YoutubeDL(ydl_options) as downloader:
        downloader.download([SAMPLE_VIDEO_URL])

    produced = sorted(OUTPUT_DIRECTORY.glob(f"{OUTPUT_BASENAME}.*"))
    if not produced:
        raise SystemExit("No output file was produced; SponsorBlock check failed.")
    for audio_file in produced:
        print(f"Wrote {audio_file} ({audio_file.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
