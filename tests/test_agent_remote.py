"""Offline tests of the portable skill's credential and request boundary."""

import base64
import importlib.util
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

HELPER_PATH = (Path(__file__).resolve().parents[1] / ".agents" / "skills"
               / "podcast-downloader-cli" / "scripts" / "remote.py")
SPEC = importlib.util.spec_from_file_location("podcast_agent_remote", HELPER_PATH)
assert SPEC and SPEC.loader
remote = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(remote)


def test_dotenv_account_and_payload(tmp_path: Path) -> None:
    """Dollar characters remain literal and the selected account stays in a header."""
    env_file = tmp_path / ".env"
    env_file.write_text("PODCAST_SERVER_URL=https://podcast.example.invalid/app\n"
                        "UI_USERNAME_2=agent\nUI_PASSWORD_2='secret${LITERAL}'\n")
    request = remote.build_request(env_file, 2, "add-url", "https://example.com/video", True)
    token = base64.b64encode(b"agent:secret${LITERAL}").decode()
    assert request.get_header("Authorization") == f"Basic {token}"
    assert request.full_url == "https://podcast.example.invalid/app/api/add-url"
    assert json.loads(request.data) == {
        "url": "https://example.com/video", "skip_age_check": True,
    }
    assert request.get_method() == "POST"


@pytest.mark.parametrize("server", ["http://example.com", "https://u:p@example.com",
                                   "https://example.com/?token=secret", ""])
def test_reject_unsafe_destination(tmp_path: Path, server: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"PODCAST_SERVER_URL={server}\nUI_USERNAME=agent\nUI_PASSWORD=secret\n")
    with pytest.raises(ValueError):
        remote.build_request(env_file, 1, "ping", None, False)


def test_redirects_do_not_forward_credentials() -> None:
    assert remote.NoRedirects().redirect_request(None, None, 302, "", {},
                                               "https://other.invalid") is None


def test_failed_write_is_not_retried_or_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("PODCAST_SERVER_URL=https://private.example.invalid\n"
                        "UI_USERNAME=agent\nUI_PASSWORD=secret\n")
    monkeypatch.setattr("sys.argv", ["remote.py", "--env-file", str(env_file),
                                    "add-url", "https://example.com/video"])
    calls = []

    class FailingOpener:
        def open(self, request: object, timeout: int) -> None:
            calls.append(request)
            raise HTTPError("https://private.example.invalid", 401, "secret", {}, None)

    monkeypatch.setattr(remote, "build_opener", lambda *args: FailingOpener())
    assert remote.main() == 1
    captured = capsys.readouterr()
    assert len(calls) == 1
    assert "401" in captured.err
    assert "private.example.invalid" not in captured.err
    assert "secret" not in captured.err
