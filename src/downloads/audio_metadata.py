"""Write project-owned tags into MP3 files.

Audiobookshelf reads podcast publication dates from embedded audio metadata, so
the downloader stamps a local completion timestamp into each successful MP3.
The same pass also records the source URL in the comment tag for later
debugging and file provenance.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

FFMPEG_METADATA_TIMEOUT_SECONDS = 120
ID3V2_VERSION_WITH_FULL_DATE = "4"
METADATA_TEMP_SUFFIX = ".download-date.tmp"
PUBLISH_TEMP_SUFFIX = ".publish.tmp"


class AudioMetadataWriter:
    """Write project tags while keeping one audio file at one stable path.

    Parameters
    ----------
    run_command:
        Callable compatible with ``subprocess.run``. The service passes a
        module-level wrapper so tests can monkeypatch the service's subprocess
        object and still intercept ffmpeg calls.
    """

    def __init__(
        self,
        run_command: Callable[..., subprocess.CompletedProcess[str]],
    ) -> None:
        """Create a metadata writer around a subprocess runner."""
        self.run_command = run_command

    def write_download_metadata(
        self,
        audio_file: Path,
        download_date_metadata: str,
        source_url_metadata: str,
        channel_display_name: str | None = None,
    ) -> None:
        """Overwrite project-managed MP3 metadata with ``ffmpeg``.

        Parameters
        ----------
        audio_file:
            Existing MP3 file to update.
        download_date_metadata:
            ISO-8601 timestamp string written to the MP3 ``date`` metadata
            field.
        source_url_metadata:
            URL written to the MP3 ``comment`` metadata field. YouTube URLs are
            normalized before reaching this writer; non-YouTube URLs are
            written as provided by the queue/download service.
        channel_display_name:
            Optional human-readable channel name written to the MP3 ``artist``
            and ``album`` tags so library apps such as Audiobookshelf show the
            expected podcast name instead of an opaque YouTube ID.

        Raises
        ------
        RuntimeError
            Raised when ``ffmpeg`` fails or does not create the temporary output
            file. The caller leaves the queue entry in place so a later run can
            retry the metadata pass.
        """
        temp_audio_file = audio_file.with_name(
            f".{audio_file.name}{METADATA_TEMP_SUFFIX}",
        )
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_file),
            "-map",
            "0",
            "-map_metadata",
            "0",
            "-codec",
            "copy",
            "-id3v2_version",
            ID3V2_VERSION_WITH_FULL_DATE,
            "-metadata",
            f"date={download_date_metadata}",
            "-metadata",
            f"comment={source_url_metadata}",
        ]
        if channel_display_name:
            command.extend(
                [
                    "-metadata",
                    f"artist={channel_display_name}",
                    "-metadata",
                    f"album={channel_display_name}",
                ],
            )
        command.extend(
            [
                "-f",
                "mp3",
                str(temp_audio_file),
            ],
        )

        try:
            # ffmpeg can echo malformed tag bytes. Replace those bytes so a
            # diagnostic message cannot stop the metadata copy.
            result = self.run_command(
                command,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=FFMPEG_METADATA_TIMEOUT_SECONDS,
                check=False,
            )
            if result.returncode != 0 or not temp_audio_file.exists():
                error_text = result.stderr.strip() or result.stdout.strip()
                error_message = (
                    "ffmpeg could not write MP3 metadata for "
                    f"{audio_file}: {error_text}"
                )
                raise RuntimeError(error_message)

            # Stage the tagged audio in a second hidden temporary file, then
            # swap it into place. The original MP3 is never opened for writing,
            # so a failure part-way through leaves the untagged file intact
            # instead of truncating it. Neither temporary name ends in ".mp3",
            # so library scanners still see exactly one audio file.
            publish_temp_file = audio_file.with_name(
                f".{audio_file.name}{PUBLISH_TEMP_SUFFIX}",
            )
            try:
                with temp_audio_file.open("rb") as tagged_audio:
                    with publish_temp_file.open("wb") as staged_audio:
                        shutil.copyfileobj(tagged_audio, staged_audio)
                # os.replace is atomic within one filesystem: readers see either
                # the old file or the fully written tagged file, never a partial one.
                os.replace(publish_temp_file, audio_file)
            finally:
                publish_temp_file.unlink(missing_ok=True)
        finally:
            # A failed ffmpeg run can leave a partial temporary file behind.
            temp_audio_file.unlink(missing_ok=True)
