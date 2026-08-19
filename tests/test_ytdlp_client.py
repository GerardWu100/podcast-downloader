"""Contract tests for the isolated ``yt-dlp`` audio client."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.downloads.ytdlp_client import YtDlpClient


def test_youtube_download_retries_with_cookies_and_reports_changed_audio(
    tmp_path: Path,
) -> None:
    """A plain YouTube failure should retry once with configured cookies."""
    commands: list[list[str]] = []
    work_dir = tmp_path / "work"
    cookies_file = tmp_path / "cookies.txt"

    def fake_run(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if len(commands) == 1:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="blocked")

        output_file = work_dir / "channel - episode [abc123].mp3"
        output_file.write_text("audio", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

    client = YtDlpClient(
        cookies_file=cookies_file,
        always_use_cookies=False,
        logger=logging.getLogger("test.ytdlp"),
        run_command=fake_run,
    )

    result = client.download(
        "https://www.youtube.com/watch?v=abc123",
        work_dir,
    )

    assert result.returncode == 0
    assert result.attempts == 2
    assert [path.name for path in result.changed_audio_files] == [
        "channel - episode [abc123].mp3"
    ]
    assert "--cookies" not in commands[0]
    assert commands[1][commands[1].index("--cookies") + 1] == str(cookies_file)
    assert commands[1][commands[1].index("--") + 1].endswith("watch?v=abc123")
    assert "--sponsorblock-remove" in commands[1]


def test_non_youtube_download_disables_playlist_without_cookie_retry(
    tmp_path: Path,
) -> None:
    """A direct non-YouTube URL should run once without provider policy."""
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")

    client = YtDlpClient(
        cookies_file=tmp_path / "cookies.txt",
        always_use_cookies=True,
        logger=logging.getLogger("test.ytdlp"),
        run_command=fake_run,
    )

    result = client.download(
        "https://videos.example.com/watch/episode-1",
        tmp_path / "work",
    )

    assert result.returncode == 1
    assert result.attempts == 1
    assert "--no-playlist" in commands[0]
    assert "--cookies" not in commands[0]
    assert "--sponsorblock-remove" not in commands[0]


def test_download_command_pins_youtube_player_client_and_relative_output(
    tmp_path: Path,
) -> None:
    """YouTube commands should pin the player client and keep paths usable.

    ``--paths`` is ignored by ``yt-dlp`` when ``--output`` is absolute, so the
    template must stay a bare filename. The pinned player client avoids the
    stream URLs that answer with HTTP 403 without a PO token.
    """
    work_dir = tmp_path / "work"
    client = YtDlpClient(
        cookies_file=None,
        always_use_cookies=False,
        logger=logging.getLogger("test.ytdlp"),
        youtube_player_client="web_embedded",
    )

    command = client.build_download_command(
        "https://www.youtube.com/watch?v=abc123",
        work_dir,
        None,
    )

    output_template = command[command.index("--output") + 1]
    assert not Path(output_template).is_absolute()
    assert f"home:{work_dir}" in command
    assert f"temp:{work_dir}" in command
    assert (
        command[command.index("--extractor-args") + 1]
        == "youtube:player_client=web_embedded"
    )


def test_blank_player_client_leaves_the_choice_to_ytdlp(tmp_path: Path) -> None:
    """An empty setting should omit ``--extractor-args`` entirely."""
    client = YtDlpClient(
        cookies_file=None,
        always_use_cookies=False,
        logger=logging.getLogger("test.ytdlp"),
        youtube_player_client="",
    )

    command = client.build_download_command(
        "https://www.youtube.com/watch?v=abc123",
        tmp_path / "work",
        None,
    )

    assert "--extractor-args" not in command
