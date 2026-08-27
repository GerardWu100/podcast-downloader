"""Integration-style checks for the Docker entrypoint bootstrap behavior."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_compose_uses_separate_temporary_download_volume() -> None:
    """Compose should keep scratch work outside the podcast library mount."""
    compose_file = PROJECT_ROOT / "docker-compose.yml"

    compose_text = compose_file.read_text(encoding="utf-8")

    assert "PODCAST_INTERMEDIATE_DIR=/temporary" in compose_text
    assert "$HOME/downloads/temporary:/temporary" in compose_text


def test_compose_keeps_cookies_in_data_volume_only() -> None:
    """Compose should let the mounted data directory own runtime cookies."""
    compose_file = PROJECT_ROOT / "docker-compose.yml"

    compose_text = compose_file.read_text(encoding="utf-8")

    assert "$HOME/.containers/podcast-downloader:/data" in compose_text
    assert ":/data/cookies.txt" not in compose_text


def test_compose_mounts_env_as_a_runtime_secret() -> None:
    """Plain credentials must reach first boot without entering an image layer."""
    compose_text = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "podcast_downloader_env" in compose_text
    assert "file: ./.env" in compose_text


def test_dockerfile_installs_deno_for_youtube_javascript_challenges() -> None:
    """The Docker image should include Deno so yt-dlp can solve YouTube JS."""
    dockerfile = PROJECT_ROOT / "Dockerfile"

    dockerfile_text = dockerfile.read_text(encoding="utf-8")

    assert "denoland/deno:bin" in dockerfile_text
    assert "/usr/local/bin/deno" in dockerfile_text


def test_dockerfile_installs_ytdlp_nightly_with_browser_impersonation() -> None:
    """The image should support YouTube JavaScript and Rumble impersonation."""
    dockerfile = PROJECT_ROOT / "Dockerfile"

    dockerfile_text = dockerfile.read_text(encoding="utf-8")

    assert "--prerelease allow" in dockerfile_text
    assert "yt-dlp[default,curl-cffi]" in dockerfile_text


def test_dockerfile_installs_gosu_for_non_root_application_process() -> None:
    """The image should be able to drop privileges after mounted-file setup."""
    dockerfile = PROJECT_ROOT / "Dockerfile"

    dockerfile_text = dockerfile.read_text(encoding="utf-8")

    assert "gosu" in dockerfile_text


def test_dockerfile_copies_only_runtime_sources() -> None:
    """A broad repository copy could bake an overlooked secret into an image."""
    dockerfile_text = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY . ." not in dockerfile_text
    assert "COPY src ./src" in dockerfile_text


def test_compose_configures_host_file_owner() -> None:
    """Compose should pass the host identity used for mounted output files."""
    compose_file = PROJECT_ROOT / "docker-compose.yml"

    compose_text = compose_file.read_text(encoding="utf-8")

    assert "HOST_UID=${HOST_UID:-1000}" in compose_text
    assert "HOST_GID=${HOST_GID:-1000}" in compose_text

    env_example_text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "HOST_UID=1000" in env_example_text
    assert "HOST_GID=1000" in env_example_text


def test_entrypoint_repairs_ownership_before_dropping_privileges() -> None:
    """Startup should repair old files and run the app as the host identity."""
    entrypoint_file = PROJECT_ROOT / "docker-entrypoint.sh"

    entrypoint_text = entrypoint_file.read_text(encoding="utf-8")

    assert 'chown -h "$HOST_UID:$HOST_GID"' in entrypoint_text
    assert 'exec gosu "$HOST_UID:$HOST_GID"' in entrypoint_text


def _run_entrypoint(
    data_dir: Path,
    download_dir: Path,
    *,
    env_secret_file: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the Docker entrypoint against temporary directories.

    Parameters
    ----------
    data_dir:
        Temporary stand-in for the container's ``/data`` mount.
    download_dir:
        Temporary stand-in for the finished-download mount.
    env_secret_file:
        Optional runtime secret that seeds ``data_dir/.env``.
    """
    env = os.environ.copy()
    env["PODCAST_DATA_DIR"] = str(data_dir)
    env["PODCAST_DOWNLOAD_DIR"] = str(download_dir)
    env["YT_DLP_AUTO_UPDATE"] = "false"
    env["PODCAST_ENV_SECRET_FILE"] = str(
        env_secret_file if env_secret_file is not None else data_dir / "no-secret"
    )
    return subprocess.run(
        [
            "sh",
            str(PROJECT_ROOT / "docker-entrypoint.sh"),
            sys.executable,
            "-c",
            "pass",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_entrypoint_seeds_env_from_example_when_runtime_secret_missing(
    tmp_path: Path,
) -> None:
    """First boot without a runtime secret should use the checked-in example."""
    data_dir = tmp_path / "data"
    download_dir = tmp_path / "downloads"

    result = _run_entrypoint(data_dir, download_dir)

    assert result.returncode == 0, result.stderr
    seeded_env_file = data_dir / ".env"
    example_text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert seeded_env_file.read_text(encoding="utf-8") == example_text
    assert oct(seeded_env_file.stat().st_mode & 0o777) == "0o600"
    assert "[startup] Seeded" in result.stdout


def test_entrypoint_preserves_existing_data_env(tmp_path: Path) -> None:
    """An existing mounted .env must never be overwritten by the entrypoint."""
    data_dir = tmp_path / "data"
    download_dir = tmp_path / "downloads"
    data_dir.mkdir()
    mounted_env_text = "UI_USERNAME=alice\nUI_PASSWORD=mounted-password\n"
    (data_dir / ".env").write_text(mounted_env_text, encoding="utf-8")

    result = _run_entrypoint(data_dir, download_dir)

    assert result.returncode == 0, result.stderr
    assert (data_dir / ".env").read_text(encoding="utf-8") == mounted_env_text
    assert oct((data_dir / ".env").stat().st_mode & 0o777) == "0o600"


def test_entrypoint_uses_existing_data_cookies_without_overwriting(
    tmp_path: Path,
) -> None:
    """An existing data cookie file should be treated as the runtime source."""
    data_dir = tmp_path / "data"
    download_dir = tmp_path / "downloads"
    data_dir.mkdir()
    mounted_cookie_text = "# Netscape HTTP Cookie File\nmounted\n"
    mounted_cookie_file = data_dir / "cookies.txt"
    mounted_cookie_file.write_text(mounted_cookie_text, encoding="utf-8")

    result = _run_entrypoint(data_dir, download_dir)

    assert result.returncode == 0, result.stderr
    assert mounted_cookie_file.read_text(encoding="utf-8") == mounted_cookie_text
    assert oct(mounted_cookie_file.stat().st_mode & 0o777) == "0o600"
    assert "[startup] Using mounted cookies file" in result.stdout


def test_entrypoint_does_not_create_cookies_when_data_file_is_missing(
    tmp_path: Path,
) -> None:
    """Cookies must come from the data mount or UI, never the image."""
    data_dir = tmp_path / "data"
    download_dir = tmp_path / "downloads"

    result = _run_entrypoint(data_dir, download_dir)

    assert result.returncode == 0, result.stderr
    assert not (data_dir / "cookies.txt").exists()
    assert "Seeded" not in "\n".join(
        line for line in result.stdout.splitlines() if "cookies.txt" in line
    )


def test_entrypoint_prefers_runtime_secret_when_data_env_missing(
    tmp_path: Path,
) -> None:
    """The Compose runtime secret should seed the mounted data directory."""
    data_dir = tmp_path / "data"
    download_dir = tmp_path / "downloads"
    env_secret_file = tmp_path / "podcast_downloader_env"
    secret_text = "UI_USERNAME=server-user\nUI_PASSWORD=server-password\n"
    env_secret_file.write_text(secret_text, encoding="utf-8")

    result = _run_entrypoint(
        data_dir,
        download_dir,
        env_secret_file=env_secret_file,
    )

    assert result.returncode == 0, result.stderr
    assert (data_dir / ".env").read_text(encoding="utf-8") == secret_text
