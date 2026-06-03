#!/usr/bin/env python3
"""Manual SponsorBlock smoke script.

This file is intentionally not a pytest test module. Run it directly when you
want to validate SponsorBlock behavior against a live YouTube video.
"""

from __future__ import annotations

import yt_dlp


def main() -> None:
    """Run a live download to inspect SponsorBlock handling manually."""
    # Mirror the production SponsorBlock categories used by the downloader CLI.
    ydl_opts = {
        "format": "bestaudio/best",
        "sponsorblock_remove": "all",
        "outtmpl": "./downloads/test_string.%(ext)s",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "writeinfojson": False,
        "writedescription": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
    }

    print("Testing SponsorBlock configuration...")
    print(f"sponsorblock_remove option: {ydl_opts.get('sponsorblock_remove')}")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        print("Starting download...")
        ydl.download(["https://www.youtube.com/watch?v=5KmpT-BoVf4"])
        print("Download completed")


if __name__ == "__main__":
    main()
