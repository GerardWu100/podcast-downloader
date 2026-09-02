# Tests guide

## Test strategy

The suite runs offline. It checks how the application areas work together and
replaces subprocesses and external services, so it never contacts media sites.

It covers:

- the application factory and web routes;
- `yt-dlp` commands, retries, and results;
- download workflow results;
- media classification and URL expansion;
- queue, archive, bypass, activity, and authentication stores;
- the command line, configuration, scheduler, password handling, and Docker
  bootstrap.

The live SponsorBlock check is
`scripts/sponsorblock_smoke_check.py`. It uses the network and stays outside
`tests/`, so Pytest does not collect it by accident.

## Code reference

- `test_api_behavior.py` and `test_security.py`: browser behavior, sessions,
  Cross-Site Request Forgery (CSRF), Content Security Policy (CSP), proxy
  trust, safe uploads, and command separators.
- `test_web_app.py`: application-factory wiring and request checks without
  patching `src.api` globals.
- `test_auth_store.py`: expiry filtering and atomic authentication updates.
- `test_ytdlp_client.py`: result types, command policy, changed files, and
  cookie retries.
- `test_downloader.py`: publication, metadata recovery, retention, archive
  serialization, queue outcomes, and per-source age-gate behavior.
- `test_url_utils_behavior.py`: media policy and queue-store concurrency.
- `test_api_routes.py`: shared-account sign-in, identical refusals for a wrong
  password and unknown name, the ban shared with the login page, every
  add-a-URL outcome, and shared YouTube normalization.
- `test_docker_build_context.py`: defense-in-depth exclusions for secrets,
  developer folders, and generated output. `test_docker_entrypoint.py` also
  checks that the Dockerfile copies only named runtime sources and that Compose
  supplies `.env` as a runtime secret.
- `test_build_extensions.py`: the packaging script. Checks that the two
  manifests agree on version and permissions, that each build carries the
  manifest its browser needs, that a stale file cannot survive a rebuild,
  and, for signing, that the unlisted channel is used and the API secret
  never reaches the command line where `/proc` would expose it.
- `test_archive_locking.py` and `test_activity_log.py`: locking for the archive
  and activity log.
- `test_schedule.py`: which calendar days are run days, the next and previous
  run times, the wording of "7 hours ago", and the last-run record.
- `test_cookie_file.py`: cookie-file parsing, which cookie sets the expiry, and
  the four sentences the settings page can show about it.
- `test_run_report.py`: which finished runs are worth a notification, which are
  ordinary, and the rule a watchdog uses to call a run overdue.
- `test_human_time.py`: the wording of "7 hours ago" and "in 4 days", including
  where it switches from minutes to hours to days.
- `test_cli_behavior.py`, `test_config.py`, `test_start.py`,
  `test_docker_entrypoint.py`, `test_passwords.py`, and `test_credentials.py`:
  command and startup boundaries, including `.env` credential synchronization.

Regression tests also cover non-finite settings, strict URL modes, YouTube path
parsing, empty cookie-fallback results, one-use age bypasses, stale credentials,
private authentication files, and isolated factory sessions.

Run the offline suite from the project root:

```bash
uv run python -m pytest -q
```

## Journal

- 2026-07-26: Replaced private monkeypatches with focused public-contract tests for cookie retries and stores.
- 2026-07-26: Added request-level factory tests for injected stores and scheduler behavior.
- 2026-08-26: Added API coverage for the extension without an HTTP client dependency.
- 2026-09-01: Added coverage for the silent-failure alerts, the health endpoint, and a scheduler that survives a missing yt-dlp.
- 2026-09-01: Added cookie-expiry coverage and run-bracket coverage for the activity feed.
- 2026-09-01: Scheduler tests moved from "waits N hours" to "waits until the next 06:00 run day", and gained the missed-run catch-up and the Run button.
- 2026-09-02: Added end-to-end contract coverage for the saved-source Run now request, including direct-video bypass, playlist age filtering, scheduler dispatch, and deletion logging.
