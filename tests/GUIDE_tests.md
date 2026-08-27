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
  serialization, and queue outcomes.
- `test_url_utils_behavior.py`: media policy and queue-store concurrency.
- `test_api_routes.py`: shared-account sign-in, identical refusals for a wrong
  password and unknown name, the ban shared with the login page, every
  add-a-URL outcome, and shared YouTube normalization.
- `test_docker_build_context.py`: what `COPY . .` ships. It names the folders
  that must stay out of the image and fails when one loses its
  `.dockerignore` entry. Generated folders such as `build/` are included because
  they are missing from a clean checkout; the problem appears only on a machine
  that ran the generator first.
- `test_build_extensions.py`: the extension packaging script. It checks that
  the two manifests agree on version and permissions, that the build ships
  every shared file, and that a stale file from an earlier build is removed.
- `test_archive_locking.py` and `test_activity_log.py`: locking for the archive
  and activity log.
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
