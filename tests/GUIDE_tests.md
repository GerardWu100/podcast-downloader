# Tests Guide

## Part 1: Test Strategy

The suite is offline and contract-oriented. It substitutes subprocesses and
external clients instead of contacting media providers.

Coverage is organized around public architecture seams:

- `create_app()` and web route behavior;
- `YtDlpClient` command/retry/result contracts;
- `PodcastDownloadService` workflow outcomes;
- media classification and expansion functions;
- queue, archive, bypass, activity, and authentication stores;
- CLI, configuration, scheduler, password, and Docker bootstrap behavior.

The live SponsorBlock smoke script remains `test_sponsorblock.py` at the root
and is intentionally separate from normal collection.

## Part 2: Code Reference

- `test_api_behavior.py` and `test_security.py`: browser behavior, sessions,
  CSRF, CSP, proxy trust, upload safety, and URL command separators.
- `test_web_app.py`: explicit factory collaborator wiring without patching
  `src.api` globals.
- `test_auth_store.py`: expiry filtering and atomic authentication JSON updates.
- `test_ytdlp_client.py`: typed results, command policy, changed files, and
  alternate-cookie retries.
- `test_downloader.py`: publication, metadata recovery, retention, archive
  serialization, and queue outcomes.
- `test_url_utils_behavior.py`: media policy plus queue-store concurrency.
- `test_archive_locking.py`: archive-store concurrency.
- `test_activity_log.py`: activity-store path and locked tail behavior.
- `test_cli_behavior.py`, `test_config.py`, `test_start.py`,
  `test_docker_entrypoint.py`, `test_passwords.py`: entry and boundary behavior.

Run all offline checks from the project root:

```bash
uv run python -m pytest -q
```

## Part 3: Journal

- 2026-07-26: Private service monkeypatches for cookie retry were replaced by
  focused `YtDlpClient` contract tests; tests no longer import compatibility
  modules.
