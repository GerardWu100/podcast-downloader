"""Contract tests for the isolated ``yt-dlp`` audio client."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.downloads.ytdlp_client import ACTIVITY_REASON_MAX_CHARS, YtDlpClient


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

    assert result.final.returncode == 0
    assert len(result.attempts) == 2
    assert [path.name for path in result.changed_audio_files] == [
        "channel - episode [abc123].mp3"
    ]
    assert "--cookies" not in commands[0]
    assert commands[1][commands[1].index("--cookies") + 1] == str(cookies_file)
    assert commands[1][commands[1].index("--") + 1].endswith("watch?v=abc123")
    assert "--sponsorblock-remove" in commands[1]


def test_unreleased_youtube_premiere_does_not_retry_with_cookies(
    tmp_path: Path,
) -> None:
    """Cookies cannot make a scheduled stream available before its release."""
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="ERROR: [youtube] abc123: Premieres in 2 hours",
        )

    client = YtDlpClient(
        cookies_file=tmp_path / "cookies.txt",
        always_use_cookies=False,
        logger=logging.getLogger("test.ytdlp"),
        run_command=fake_run,
    )

    result = client.download(
        "https://www.youtube.com/watch?v=abc123",
        tmp_path / "work",
    )

    assert result.is_unreleased_youtube_content() is True
    assert len(commands) == 1


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

    assert result.final.returncode == 1
    assert len(result.attempts) == 1
    assert "--no-playlist" in commands[0]
    assert "--cookies" not in commands[0]
    assert "--sponsorblock-remove" not in commands[0]


def test_rumble_download_impersonates_chrome(tmp_path: Path) -> None:
    """Rumble commands should use the browser transport Cloudflare accepts."""
    client = YtDlpClient(
        cookies_file=None,
        always_use_cookies=False,
        logger=logging.getLogger("test.ytdlp"),
    )

    command = client.build_download_command(
        "https://rumble.com/v7eg1qc-america-first-ep.-1737.html",
        tmp_path / "work",
        None,
    )

    assert command[command.index("--impersonate") + 1] == "chrome"
    assert "--no-playlist" in command


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


def test_retry_runs_verbosely_and_keeps_both_attempts(tmp_path: Path) -> None:
    """A failed first attempt should retry with ``-v`` and keep both records.

    A YouTube download can fail twice for two different reasons. Keeping only
    the last attempt hides the first cause.
    """
    work_dir = tmp_path / "work"
    cookies_file = tmp_path / "cookies.txt"

    def fake_run(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        if "--cookies" in command:
            return subprocess.CompletedProcess(
                command, 1, stdout="", stderr="ERROR: cookies rejected"
            )
        return subprocess.CompletedProcess(
            command, 1, stdout="", stderr="ERROR: HTTP Error 403: Forbidden"
        )

    client = YtDlpClient(
        cookies_file=cookies_file,
        always_use_cookies=True,
        logger=logging.getLogger("test.ytdlp"),
        run_command=fake_run,
    )

    result = client.download("https://www.youtube.com/watch?v=abc123", work_dir)

    assert len(result.attempts) == 2
    assert result.attempts[0].used_cookies is True
    assert result.attempts[0].verbose is False
    assert result.attempts[1].used_cookies is False
    assert result.attempts[1].verbose is True
    assert "-v" in result.attempts[1].command

    report = result.diagnostic_report()
    assert "ERROR: cookies rejected" in report
    assert "ERROR: HTTP Error 403: Forbidden" in report
    assert "attempt 1" in report and "attempt 2" in report


def test_verbose_setting_applies_to_the_first_attempt(tmp_path: Path) -> None:
    """``verbose=True`` should add ``-v`` even when nothing fails."""
    commands: list[list[str]] = []
    work_dir = tmp_path / "work"

    def fake_run(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "creator - episode.mp3").write_text("audio", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    client = YtDlpClient(
        cookies_file=None,
        always_use_cookies=False,
        logger=logging.getLogger("test.ytdlp"),
        run_command=fake_run,
        verbose=True,
    )

    result = client.download("https://www.youtube.com/watch?v=abc123", work_dir)

    assert len(commands) == 1
    assert "-v" in commands[0]
    assert result.attempts[0].verbose is True


def test_activity_reason_prefers_the_last_error_line(tmp_path: Path) -> None:
    """Warnings before the fatal message should not become the reported cause."""
    work_dir = tmp_path / "work"
    stderr_text = (
        "WARNING: --paths is ignored since an absolute path is given\n"
        "WARNING: some other note\n"
        "ERROR: unable to download video data: HTTP Error 403: Forbidden\n"
    )

    def fake_run(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr=stderr_text)

    client = YtDlpClient(
        cookies_file=None,
        always_use_cookies=False,
        logger=logging.getLogger("test.ytdlp"),
        run_command=fake_run,
    )

    result = client.download("https://videos.example.com/watch/episode-1", work_dir)

    assert result.activity_reason() == (
        "ERROR: unable to download video data: HTTP Error 403: Forbidden"
    )


def test_activity_reason_stays_one_bounded_line(tmp_path: Path) -> None:
    """A long multi-line error must not break the one-line activity feed."""
    work_dir = tmp_path / "work"
    stderr_text = "ERROR: " + "very long detail " * 60 + "\nmore\nlines\n"

    def fake_run(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr=stderr_text)

    client = YtDlpClient(
        cookies_file=None,
        always_use_cookies=False,
        logger=logging.getLogger("test.ytdlp"),
        run_command=fake_run,
    )

    reason = client.download(
        "https://videos.example.com/watch/episode-1",
        work_dir,
    ).activity_reason()

    assert "\n" not in reason
    assert len(reason) <= ACTIVITY_REASON_MAX_CHARS
