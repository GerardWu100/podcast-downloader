# Tests Guide

## Part 1: Test Strategy

The suite runs offline and checks the boundaries between parts of the app. It
replaces subprocesses and external clients instead of contacting media sites.

Coverage follows the app's main boundaries:

- `create_app()` and web routes;
- `YtDlpClient` command/retry/result contracts;
- `PodcastDownloadService` workflow results;
- media classification and expansion functions;
- queue, archive, bypass, activity, and authentication stores;
- CLI, configuration, scheduler, password, and Docker bootstrap behavior.

The live SponsorBlock check lives at
`scripts/sponsorblock_smoke_check.py`. It uses the network, so it stays out of
`tests/` and is not named like a test module. Pytest therefore does not collect
it by accident.

## Part 2: Code Reference

- `test_api_behavior.py` and `test_security.py`: browser behavior, sessions,
  CSRF, CSP, proxy trust, upload safety, and URL command separators.
- `test_web_app.py`: explicit factory collaborator wiring plus a request-level
  check that route writes and scheduler requests use the injected instances,
  without patching `src.api` globals.
- `test_auth_store.py`: expiry filtering and atomic authentication JSON updates.
- `test_ytdlp_client.py`: typed results, command policy, changed files, and
  alternate-cookie retries.
- `test_downloader.py`: publication, metadata recovery, retention, archive
  serialization, and queue outcomes.
- `test_url_utils_behavior.py`: media policy plus queue-store concurrency.
- `test_archive_locking.py`: archive-store concurrency.
- `test_activity_log.py`: activity-store path and locked tail behavior.
- `test_cli_behavior.py`, `test_config.py`, `test_start.py`,
  `test_docker_entrypoint.py`, `test_passwords.py`, `test_credentials.py`: entry
  and boundary behavior, including the `.env` to `.ui_credentials.json` sync.

Regression coverage also includes non-finite configuration, strict CLI URL
modes, parsed-path YouTube classification, empty-result cookie fallback,
one-use age bypasses, stale credential removal, private authentication files,
and isolated factory sessions.

Run all offline checks from the project root:

```bash
uv run python -m pytest -q
```

## Part 3: Journal

- 2026-07-26: Private service monkeypatches for cookie retry were replaced by
  focused `YtDlpClient` contract tests; store and service tests now consume
  their typed public seams directly.
- 2026-07-26: Factory tests gained a request-level regression check for injected
  queue, bypass, activity, authentication, and scheduler collaborators.
