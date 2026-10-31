# Trail notes

## Decisions

- 2026-10-11: Declined hang recovery (a watchdog or Docker `HEALTHCHECK`), a PO-token helper container, and Watchtower auto-updates. Docker's restart policy ignores health status anyway; updates stay a manual `docker compose pull`.
- 2026-10-11: Declined a `trusted_proxy` mode setting. The strict `config.toml` loader stops at startup on an unknown key, so renaming or removing any setting breaks every existing deployment.
- 2026-10-11: Behind a proxy, the client IP is the last `X-Forwarded-For` entry. The first entry and `CF-Connecting-IP` come from the visitor, so trusting them let a guesser dodge the login ban.
- 2026-10-11: Settings moved from `config.ini` to `config.toml` because the INI loader silently fell back to defaults on typos. Notification settings stay in `notifications.json`: a web form rewriting the commented `config.toml` would erase its comments.
- 2026-10-11: The agent skill is one curl-based `SKILL.md`, because Hermes installs a skill from its `SKILL.md` URL alone. Do not split it or add a helper script.
- 2026-10-11: Removed a README comparison table with similar tools. Pinchflat matches the main features, so the table invited "just use Pinchflat".
- 2026-10-10: Removed the generated `CODE_EXPLAINED.html`; it went stale after every code change. Do not regenerate it.
- 2026-09-27: Retention deletes MP3s but never their archive entries. Expansion lists a quiet channel's newest videos however old, so removing an entry downloaded the episode again every `retention_days`.
- 2026-09-27: A source folder name is saved only after a successful lookup, never the ID fallback. A blocked lookup used to publish into a `UC...`/`PL...` folder and split the podcast in Audiobookshelf.
- 2026-09-01: The last-run record covers only whole-queue passes; single-URL and single-playlist runs are deliberately left out.
- 2026-08-28: The extension sends only the URL, never `skip_age_check`: that flag makes a one-use age bypass and forces a full-playlist run, which are server decisions.
- 2026-08-26: The API and extension reuse the web account in an `Authorization: Basic` header (the session cookie is `HttpOnly` and `SameSite=lax`). No CSRF token, CORS headers or `WWW-Authenticate`; extension settings use `storage.local`, not `sync`, so the password is not copied to other profiles.
- 2026-07-26: Add a provider interface only when a second site needs its own expansion or metadata rules; YouTube rules stay apart from generic URL checks.

## Assumptions

- 2026-10-31: The default `web_embedded` YouTube player client still returns stream URLs that need no GVS PO token. Check with a live download when `HTTP Error 403` appears after metadata succeeds.
- 2026-10-11: Through Cloudflare Tunnel, the last `X-Forwarded-For` entry equals `CF-Connecting-IP`. Check by logging both headers behind the tunnel.

## Gotchas

- 2026-10-31: Keep yt-dlp `--output` a bare filename template; with an absolute template yt-dlp ignores `--paths`. Put folders in `--paths home:` and `--paths temp:`.
- 2026-08-23: Rumble's Cloudflare returns 403 to plain requests. It needs `--impersonate chrome`, nightly yt-dlp, and the `curl-cffi` extra.
- 2026-09-27: Subtracting two datetimes that share one `ZoneInfo` gives wall-clock time, an hour off across daylight-saving changes. Use timestamps for elapsed time.
- 2026-08-26: The CSP needs `manifest-src 'self'` and `worker-src 'self'`; without them `default-src 'none'` silently blocks phone-app install. The manifest and `/sw.js` must stay public, because browsers fetch the manifest without cookies.
- 2026-08-10: `/logs` must return 401, not redirect, on an expired session, or the log box fills with login-page HTML.
- 2026-09-01: The style and script constants in `src/web/templates.py` are plain strings, not f-string parts; do not double their braces.
- 2026-08-08: Hand-edited state files may lack a final newline. Every line-per-entry file must append through the shared locked line file, which repairs it; a per-store fix missed one store.
- 2026-08-26: Every generated folder (such as `build/`) must also be in `.dockerignore`. A missing entry is invisible on a clean checkout and copies browser code into the image.
- 2026-10-11: Edit the extension only in `extension/src/`, then run `scripts/build_extensions.py`; `chrome/` and `firefox/` are committed builds.
- 2026-08-27: Firefox: the host-permission request must be the first thing awaited after the click; `btoa` throws on non-ASCII, so encode credentials as UTF-8 first; a clashing suggested shortcut is dropped silently.

## Failed approaches

- 2026-08-28: Shipping an unsigned Firefox `.zip`. *Disproved*: Firefox rejects it as "corrupt", and it could be mistaken for the signed `.xpi`. Releases ship the signed `.xpi` only.
- 2026-08-10: A five-minute download timeout. *Disproved*: full-length episodes never finished and were never archived; the default is now one hour.

## Open blockers

## Untried ideas
