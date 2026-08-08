"""Render browser-facing HTML pages without mutating application state."""

from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi.responses import HTMLResponse

# Inline SVG favicon (a download arrow above a tray) shared by every page,
# served as a data URI so no static-file route is needed. Without it browsers
# request /favicon.ico and log a 404 on every page load. The URI is written in
# readable SVG with only "#", "<" and ">" percent-encoded, so the artwork can be
# edited in place. src/web/auth.py sets "img-src 'self' data:", which allows it.
FAVICON_ACCENT_COLOR = "%232563eb"  # "#2563eb", matching --accent in BASE_STYLES
FAVICON_TAG = (
    '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,'
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    f"%3Crect width='32' height='32' rx='7' fill='{FAVICON_ACCENT_COLOR}'/%3E"
    "%3Cpath d='M16 7v10m0 0l-4-4m4 4l4-4' fill='none' stroke='%23fff'"
    " stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/%3E"
    "%3Cpath d='M9 22h14' fill='none' stroke='%23fff' stroke-width='2.4'"
    " stroke-linecap='round'/%3E%3C/svg%3E"
    '" />'
)

BASE_STYLES = """
  :root {
    color-scheme:light dark;
    --bg:#f0f2f5; --surface:#fff; --input-bg:#f8f9fa; --input-focus:#fff;
    --border:#e1e4e8; --text:#1c1e21; --muted:#6b7280;
    --accent:#2563eb; --accent-hov:#1d4ed8; --accent-soft:#eff6ff;
    --accent-border:#bfdbfe; --ok-bg:#f0fdf4; --ok-text:#166534;
    --ok-border:#bbf7d0; --warn-bg:#fffbeb; --warn-text:#92400e;
    --warn-border:#fde68a; --danger:#b91c1c; --danger-hov:#991b1b;
    --danger-bg:#fef2f2; --danger-border:#fecaca;
    --log-bg:#1a2332; --log-border:#2d3a4d; --log-hover:rgba(255,255,255,.04);
    --log-text:#dbe4f0; --log-time:#8b9cb3; --log-ok:#4ade80; --log-warn:#fbbf24;
    --log-err:#f87171; --log-info:#7dd3fc; --log-dim:#8b9cb3; --log-neutral:#cbd5e1;
    --log-ok-soft:rgba(74,222,128,.14); --log-warn-soft:rgba(251,191,36,.14);
    --log-err-soft:rgba(248,113,113,.14); --log-info-soft:rgba(125,211,252,.14);
    --log-dim-soft:rgba(139,156,179,.12); --scrollbar:#3d4f66;
    --shadow:0 1px 3px rgba(0,0,0,.08),0 1px 2px rgba(0,0,0,.06); --r:10px;
  }
  body.theme-dark {
    color-scheme:dark;
    --bg:#101418; --surface:#171d23; --input-bg:#111820; --input-focus:#0f1720;
    --border:#2a3440; --text:#e5edf5; --muted:#9aa8b6;
    --accent:#60a5fa; --accent-hov:#3b82f6; --accent-soft:#12263d;
    --accent-border:#255783; --ok-bg:#0f2f1d; --ok-text:#86efac;
    --ok-border:#166534; --warn-bg:#30230d; --warn-text:#facc15;
    --warn-border:#854d0e; --danger:#fca5a5; --danger-hov:#fecaca;
    --danger-bg:#2a1215; --danger-border:#7f1d1d;
    --log-bg:#0a0e14; --log-border:#1e293b; --log-hover:rgba(255,255,255,.035);
    --log-text:#e2e8f0; --log-time:#94a3b8; --log-ok:#34d399; --log-warn:#fcd34d;
    --log-err:#fb7185; --log-info:#93c5fd; --log-dim:#64748b; --log-neutral:#cbd5e1;
    --log-ok-soft:rgba(52,211,153,.16); --log-warn-soft:rgba(252,211,77,.16);
    --log-err-soft:rgba(251,113,133,.16); --log-info-soft:rgba(147,197,253,.16);
    --log-dim-soft:rgba(100,116,139,.18); --scrollbar:#334155;
    --shadow:0 1px 2px rgba(0,0,0,.35),0 10px 24px rgba(0,0,0,.24);
  }
  @media (prefers-color-scheme:dark) {
    body:not(.theme-light) {
      color-scheme:dark;
      --bg:#101418; --surface:#171d23; --input-bg:#111820; --input-focus:#0f1720;
      --border:#2a3440; --text:#e5edf5; --muted:#9aa8b6;
      --accent:#60a5fa; --accent-hov:#3b82f6; --accent-soft:#12263d;
      --accent-border:#255783; --ok-bg:#0f2f1d; --ok-text:#86efac;
      --ok-border:#166534; --warn-bg:#30230d; --warn-text:#facc15;
      --warn-border:#854d0e; --danger:#fca5a5; --danger-hov:#fecaca;
      --danger-bg:#2a1215; --danger-border:#7f1d1d;
      --log-bg:#0a0e14; --log-border:#1e293b; --log-hover:rgba(255,255,255,.035);
      --log-text:#e2e8f0; --log-time:#94a3b8; --log-ok:#34d399; --log-warn:#fcd34d;
      --log-err:#fb7185; --log-info:#93c5fd; --log-dim:#64748b; --log-neutral:#cbd5e1;
      --log-ok-soft:rgba(52,211,153,.16); --log-warn-soft:rgba(252,211,77,.16);
      --log-err-soft:rgba(251,113,133,.16); --log-info-soft:rgba(147,197,253,.16);
      --log-dim-soft:rgba(100,116,139,.18); --scrollbar:#334155;
      --shadow:0 1px 2px rgba(0,0,0,.35),0 10px 24px rgba(0,0,0,.24);
    }
  }
  *,*::before,*::after { box-sizing:border-box; margin:0; padding:0; }
  body {
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:var(--bg); color:var(--text); line-height:1.5; font-size:14px;
  }
  .card {
    background:var(--surface); border:1px solid var(--border);
    border-radius:var(--r); padding:22px 24px; box-shadow:var(--shadow);
  }
  .card-label {
    font-size:.7rem; font-weight:700; text-transform:uppercase;
    letter-spacing:.06em; color:var(--muted); margin-bottom:14px; display:block;
  }
  input[type="text"],input[type="password"] {
    width:100%; padding:9px 12px; font-size:.875rem; border:1px solid var(--border);
    border-radius:7px; outline:none; background:var(--input-bg); color:var(--text);
    transition:border-color .15s,box-shadow .15s,background .15s;
  }
  input[type="file"] {
    width:100%; padding:7px 10px; font-size:.82rem; border:1px solid var(--border);
    border-radius:7px; outline:none; background:var(--input-bg); color:var(--text);
  }
  input[type="text"]:focus,input[type="password"]:focus {
    border-color:var(--accent); background:var(--input-focus);
    box-shadow:0 0 0 3px rgba(37,99,235,.12);
  }
  input::placeholder { color:var(--muted); opacity:.72; }
  .btn {
    padding:9px 20px; font-size:.875rem; font-weight:600;
    background:var(--accent); color:#fff; border:none; border-radius:7px;
    cursor:pointer; transition:background .15s; white-space:nowrap;
  }
  .btn:hover { background:var(--accent-hov); }
  .msg-ok   { background:var(--ok-bg); color:var(--ok-text); border:1px solid var(--ok-border); }
  .msg-warn { background:var(--warn-bg); color:var(--warn-text); border:1px solid var(--warn-border); }
  .msg-err  { background:var(--danger-bg); color:var(--danger); border:1px solid var(--danger-border); }
  .msg-ok,.msg-warn,.msg-err {
    border-radius:7px; padding:9px 14px; font-size:.82rem; margin-bottom:12px;
  }
  .bypass-row { margin-top:10px; }
.bypass-row label {
  display:flex; align-items:center; gap:6px; cursor:pointer;
  font-size:.78rem; color:var(--muted); font-weight:normal;
}

/* The refresh keeps the existing controls and terminology while improving
   hierarchy, touch targets, focus visibility, and small-screen behavior. */
:root {
  --bg-accent:#e7eef9; --surface-raised:#fff; --border-strong:#cbd5e1;
  --shadow:0 1px 2px rgba(23,32,51,.05),0 12px 30px rgba(23,32,51,.06);
  --shadow-focus:0 0 0 3px rgba(37,99,235,.16); --r:14px;
}
body.theme-dark {
  --bg:#0d121a; --bg-accent:#151e2b; --surface:#151c25;
  --surface-raised:#19222d; --border:#293543; --border-strong:#39495c;
  --shadow:0 1px 2px rgba(0,0,0,.32),0 16px 34px rgba(0,0,0,.22);
  --shadow-focus:0 0 0 3px rgba(96,165,250,.18);
}
@media (prefers-color-scheme:dark) {
  body:not(.theme-light) {
    --bg:#0d121a; --bg-accent:#151e2b; --surface:#151c25;
    --surface-raised:#19222d; --border:#293543; --border-strong:#39495c;
    --shadow:0 1px 2px rgba(0,0,0,.32),0 16px 34px rgba(0,0,0,.22);
    --shadow-focus:0 0 0 3px rgba(96,165,250,.18);
  }
}
html { min-height:100%; background:var(--bg); }
body {
  min-height:100vh;
  background:
    radial-gradient(circle at 15% -10%, var(--bg-accent), transparent 38rem),
    var(--bg);
}
.card { padding:22px; }
.card-label { letter-spacing:.08em; }
input[type=text],input[type=password] {
  min-height:42px; padding:10px 12px; border-color:var(--border-strong);
  border-radius:9px;
}
input[type=file] {
  min-height:42px; border-color:var(--border-strong); border-radius:9px;
}
input:focus,select:focus,button:focus-visible,a:focus-visible {
  outline:none; border-color:var(--accent); box-shadow:var(--shadow-focus);
}
.btn {
  min-height:42px; border-radius:9px;
  transition:background .15s,transform .15s;
}
.btn:active { transform:translateY(1px); }
.msg-ok,.msg-warn,.msg-err { border-radius:9px; padding:10px 13px; }
.text-link { color:var(--accent); text-decoration:none; font-weight:600; }
.text-link:hover { text-decoration:underline; text-underline-offset:3px; }
"""


def render_help_page(
    header_factory: Callable[[str | None], dict[str, str]],
) -> HTMLResponse:
    """Render the short, public usage and cookie-setup reference page.

    Returns
    -------
    fastapi.responses.HTMLResponse
        Static help page with the same light and dark themes as the main UI.
    """
    script_nonce = secrets.token_urlsafe(16)
    return HTMLResponse(
        content=f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Podcast Downloader Help</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  {FAVICON_TAG}
  <style>
        {BASE_STYLES}
    body {{ padding:36px 16px; }}
    .help-page {{ width:100%; max-width:720px; margin:0 auto; }}
    .help-nav {{
      display:flex; align-items:center; justify-content:space-between;
      margin-bottom:18px;
    }}
    .help-nav a {{
      color:var(--accent); text-decoration:none; font-size:.82rem; font-weight:650;
    }}
    .help-nav a:hover {{ text-decoration:underline; text-underline-offset:3px; }}
    .theme-toggle {{
      min-height:36px; padding:6px 12px; border:1px solid var(--border);
      border-radius:8px; background:var(--surface); color:var(--muted);
      cursor:pointer; font-size:.78rem; font-weight:600;
    }}
    .help-card h1 {{ margin:0 0 6px; font-size:1.45rem; letter-spacing:-.02em; }}
    .lead {{ margin:0 0 24px; color:var(--muted); }}
    .help-card h2 {{ margin:24px 0 8px; font-size:1rem; }}
    .help-card p {{ margin:0 0 10px; }}
    .help-card ol,.help-card ul {{ margin:8px 0 0; padding-left:20px; }}
    .help-card li + li {{ margin-top:7px; }}
    .help-card code {{
      padding:2px 5px; border:1px solid var(--border); border-radius:5px;
      background:var(--input-bg); font-size:.82em;
    }}
    .note {{
      margin-top:12px; padding:11px 13px; border:1px solid var(--warn-border);
      border-radius:9px; background:var(--warn-bg); color:var(--warn-text);
      font-size:.82rem;
    }}
    @media (max-width:520px) {{
      body {{ padding:20px 12px; }}
      .help-card {{ padding:19px; }}
    }}
  </style>
</head>
<body>
  <main class="help-page">
    <nav class="help-nav" aria-label="Help page navigation">
      <a href="/">← Back to downloader</a>
      <button class="theme-toggle" id="theme-toggle" type="button">Dark</button>
    </nav>
    <article class="card help-card">
      <h1>How Podcast Downloader works</h1>
      <p class="lead">A short guide to the queue, downloads, and YouTube cookies.</p>

      <h2>Basic behavior</h2>
      <ul>
        <li>Add a YouTube channel, playlist, livestream, or direct video URL.</li>
        <li>Channels and playlists stay monitored in <code>urls.txt</code>.</li>
        <li>Finished audio is saved as MP3 with SponsorBlock segments removed when available.</li>
        <li>Activity shows concise results; Download log contains diagnostic detail.</li>
      </ul>

      <h2>Main functions</h2>
      <ul>
        <li><strong>Add:</strong> append a supported URL to the queue.</li>
        <li><strong>Download now:</strong> bypass the age wait for a direct YouTube video, or fetch a full playlist.</li>
        <li><strong>Remove:</strong> stop monitoring a queued URL.</li>
        <li><strong>Upload:</strong> replace the YouTube cookie file used by <code>yt-dlp</code>.</li>
      </ul>

      <h2>Adding YouTube cookies</h2>
      <ol>
        <li>Export browser cookies in Netscape format as a text file.</li>
        <li>Open the YouTube cookies card in the downloader.</li>
        <li>Select the exported file and choose Upload.</li>
      </ol>
      <p class="note">
        Cookie exports can contain private sign-in data. Keep the file private.
        See the official
        <a class="text-link" href="https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp">yt-dlp cookie instructions</a>.
      </p>
    </article>
  </main>
  <script nonce="{script_nonce}">
    const savedTheme = localStorage.getItem('podcast-theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const themeButton = document.getElementById('theme-toggle');
    function applyTheme(theme) {{
      document.body.classList.toggle('theme-dark', theme === 'dark');
      document.body.classList.toggle('theme-light', theme === 'light');
      themeButton.textContent = theme === 'dark' ? 'Light' : 'Dark';
    }}
    applyTheme(savedTheme || (prefersDark ? 'dark' : 'light'));
    themeButton.addEventListener('click', () => {{
      const nextTheme = document.body.classList.contains('theme-dark') ? 'light' : 'dark';
      localStorage.setItem('podcast-theme', nextTheme);
      applyTheme(nextTheme);
    }});
  </script>
</body>
</html>""",
        headers=header_factory(script_nonce),
    )


def render_login_page(
    *,
    message_html: str,
    safe_csrf_session: str,
    safe_token: str,
    script_nonce: str,
    headers: dict[str, str],
) -> HTMLResponse:
    """Render the login page from already escaped values."""
    return HTMLResponse(
        content=f"""<!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8" /><title>Podcast Downloader</title>
      <meta name="viewport" content="width=device-width,initial-scale=1" />
      {FAVICON_TAG}
      <style>
    {BASE_STYLES}
    body {{ display:flex; align-items:center; justify-content:center; min-height:100vh; padding:24px; }}
    .card {{ width:100%; max-width:360px; }}
    .theme-toggle {{
      position:fixed; top:16px; right:16px; padding:7px 10px; border:1px solid var(--border);
      border-radius:7px; background:var(--surface); color:var(--muted); cursor:pointer;
      font-size:.78rem; font-weight:600;
    }}
    .theme-toggle:hover {{ color:var(--text); border-color:var(--accent); }}
    h1 {{ font-size:1.1rem; font-weight:700; margin-bottom:4px; }}
    .sub {{ font-size:.82rem; color:var(--muted); margin-bottom:24px; }}
    label {{ display:block; font-size:.72rem; font-weight:700; text-transform:uppercase;
             letter-spacing:.05em; color:var(--muted); margin-bottom:6px; }}
    .btn {{ margin-top:14px; width:100%; padding:10px; }}
    .help-link {{ display:block; margin-top:18px; text-align:center; font-size:.78rem; }}
      </style>
    </head>
    <body>
      <button class="theme-toggle" id="theme-toggle" type="button">Dark</button>
      <div class="card">
    <h1>Podcast Downloader</h1>
    <p class="sub">Sign in to manage your queue.</p>
    {message_html}
    <form method="post" action="/login">
      <input type="hidden" name="csrf_token" value="{safe_token}" />
      <input type="hidden" name="csrf_session" value="{safe_csrf_session}" />
      <label for="password">Password</label>
      <input id="password" name="password" type="password"
        autocomplete="current-password" autocapitalize="none"
        spellcheck="false" required autofocus />
      <button type="submit" class="btn">Sign in</button>
    </form>
    <a class="help-link text-link" href="/help">How it works</a>
      </div>
      <script nonce="{script_nonce}">
    const savedTheme = localStorage.getItem('podcast-theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const themeButton = document.getElementById('theme-toggle');

    function applyTheme(theme) {{
      document.body.classList.toggle('theme-dark', theme === 'dark');
      document.body.classList.toggle('theme-light', theme === 'light');
      themeButton.textContent = theme === 'dark' ? 'Light' : 'Dark';
    }}

    applyTheme(savedTheme || (prefersDark ? 'dark' : 'light'));
    themeButton.addEventListener('click', () => {{
      const nextTheme = document.body.classList.contains('theme-dark') ? 'light' : 'dark';
      localStorage.setItem('podcast-theme', nextTheme);
      applyTheme(nextTheme);
    }});
      </script>
    </body>
    </html>""",
        headers=headers,
    )


def render_queue_page(
    *,
    bypass_row_html: str,
    count: int,
    last_activity: str,
    msg_html: str,
    queue_html: str,
    safe_token: str,
    script_nonce: str,
    headers: dict[str, str],
) -> HTMLResponse:
    """Render the authenticated queue page from prepared values."""
    return HTMLResponse(
        content=f"""<!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8" />
      <title>Podcast Downloader</title>
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      {FAVICON_TAG}
      <style>
    {BASE_STYLES}
    body {{ padding:38px 18px 54px; }}
    .page {{ max-width:900px; margin:0 auto; display:flex; flex-direction:column; gap:18px; }}
    header {{
      display:flex; justify-content:space-between; align-items:center;
      margin-bottom:2px; padding:0 2px;
    }}
    .header-actions {{ display:flex; align-items:center; gap:8px; }}
    .brand h1 {{ font-size:1.42rem; font-weight:750; letter-spacing:-.025em; }}
    .brand p  {{ font-size:.78rem; color:var(--muted); }}
    .theme-toggle {{
      font-size:.78rem; color:var(--muted); background:var(--surface);
      padding:6px 12px; border:1px solid var(--border); border-radius:6px;
      cursor:pointer; transition:color .15s,border-color .15s;
    }}
    .theme-toggle:hover {{ color:var(--text); border-color:var(--accent); }}
    .logout-btn {{
      font-size:.78rem; color:var(--muted); background:var(--surface); text-decoration:none;
      padding:6px 12px; border:1px solid var(--border); border-radius:6px;
      cursor:pointer; transition:color .15s,border-color .15s;
    }}
    .logout-btn:hover {{ color:#dc2626; border-color:#dc2626; }}
    .card-row {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; }}
    .badge {{
      background:var(--accent-soft); color:var(--accent); border:1px solid var(--accent-border);
      font-size:.7rem; font-weight:700; padding:2px 8px; border-radius:999px;
    }}
    .input-row {{ display:flex; gap:8px; }}
    .input-row input {{ flex:1; }}
    .file-row {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; align-items:center; }}
    .q-list {{ list-style:none; }}
    .q-item {{ display:flex; align-items:flex-start; gap:9px; padding:8px 0; border-bottom:1px solid var(--border); }}
    .q-item:last-child {{ border-bottom:none; }}
    .q-dot {{ width:6px; height:6px; background:var(--accent); border-radius:50%; margin-top:5px; flex-shrink:0; opacity:.5; }}
    .q-url {{ flex:1; font-size:.8rem; color:var(--muted); word-break:break-all; }}
    .remove-form {{ flex-shrink:0; }}
    .btn-remove {{
      padding:5px 10px; font-size:.75rem; font-weight:600; background:var(--surface);
      color:var(--danger); border:1px solid var(--danger-border); border-radius:6px; cursor:pointer;
      transition:background .15s,border-color .15s,color .15s;
    }}
    .btn-remove:hover {{ background:var(--danger-bg); border-color:var(--danger-border); color:var(--danger-hov); }}
    .empty {{ font-size:.85rem; color:var(--muted); font-style:italic; }}
    .log-bar {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; gap:12px; flex-wrap:wrap; }}
    .log-controls {{ display:flex; align-items:center; gap:10px; font-size:.78rem; color:var(--muted); }}
    .log-controls label {{ display:flex; align-items:center; gap:4px; cursor:pointer; font-weight:normal; }}
    #log-ts {{
      font-variant-numeric:tabular-nums; font-size:.72rem; color:var(--muted);
      background:var(--input-bg); border:1px solid var(--border); border-radius:999px;
      padding:2px 10px;
    }}
    .log-source {{
      font-size:.75rem; font-weight:600; color:var(--text); background:var(--input-bg);
      border:1px solid var(--border); border-radius:999px; padding:5px 12px; cursor:pointer;
      transition:border-color .15s,box-shadow .15s;
    }}
    .log-source:focus {{ outline:none; border-color:var(--accent); box-shadow:0 0 0 3px rgba(37,99,235,.12); }}
    .btn-ghost {{
      padding:5px 12px; font-size:.75rem; font-weight:600; background:transparent;
      color:var(--accent); border:1px solid var(--accent-border); border-radius:999px;
      cursor:pointer; transition:all .15s;
    }}
    .btn-ghost:hover {{ background:var(--accent-soft); }}
    #log-box {{
      background:var(--log-bg); color:var(--log-text); border:1px solid var(--log-border);
      font-family:"SF Mono","Fira Code","Consolas",monospace;
      font-size:.74rem; line-height:1.45; border-radius:10px; padding:6px 0;
      height:340px; overflow-y:auto; word-break:break-word;
      box-shadow:inset 0 1px 0 rgba(255,255,255,.04);
    }}
    #log-box::-webkit-scrollbar {{ width:6px; }}
    #log-box::-webkit-scrollbar-thumb {{ background:var(--scrollbar); border-radius:999px; }}
    .log-empty {{
      display:flex; align-items:center; justify-content:center; min-height:280px;
      padding:24px; color:var(--log-dim); font-style:italic; text-align:center;
    }}
    .log-line {{
      display:flex; align-items:flex-start; gap:10px; padding:7px 14px;
      border-left:3px solid transparent; transition:background .12s;
    }}
    .log-line + .log-line {{ border-top:1px solid rgba(255,255,255,.04); }}
    .log-line:hover {{ background:var(--log-hover); }}
    .log-line--ok {{ border-left-color:var(--log-ok); }}
    .log-line--warn {{ border-left-color:var(--log-warn); }}
    .log-line--err {{ border-left-color:var(--log-err); }}
    .log-line--info {{ border-left-color:var(--log-info); }}
    .log-line--dim {{ border-left-color:var(--log-dim); }}
    .log-line--neutral {{ border-left-color:rgba(255,255,255,.12); }}
    .log-time {{
      flex-shrink:0; min-width:64px; font-size:.68rem; color:var(--log-time);
      font-variant-numeric:tabular-nums; padding-top:1px;
    }}
    .log-badge,.log-level {{
      flex-shrink:0; min-width:42px; text-align:center;
      font-size:.58rem; font-weight:700; letter-spacing:.05em; text-transform:uppercase;
      padding:2px 6px; border-radius:999px; margin-top:1px;
    }}
    .log-badge--ok,.log-level--ok {{ color:var(--log-ok); background:var(--log-ok-soft); }}
    .log-badge--warn,.log-level--warn {{ color:var(--log-warn); background:var(--log-warn-soft); }}
    .log-badge--err,.log-level--err {{ color:var(--log-err); background:var(--log-err-soft); }}
    .log-badge--info,.log-level--info {{ color:var(--log-info); background:var(--log-info-soft); }}
    .log-badge--dim,.log-level--dim {{ color:var(--log-dim); background:var(--log-dim-soft); }}
    .log-badge--neutral,.log-level--neutral {{ color:var(--log-neutral); background:var(--log-dim-soft); }}
    .log-msg {{ flex:1; color:var(--log-text); white-space:pre-wrap; }}
    .log-line--ok .log-msg {{ color:var(--log-ok); }}
    .log-line--warn .log-msg {{ color:var(--log-warn); }}
    .log-line--err .log-msg {{ color:var(--log-err); }}
    .log-line--info .log-msg {{ color:var(--log-info); }}
    .log-line--dim .log-msg {{ color:var(--log-dim); }}
    .brand p {{ margin-top:3px; font-size:.8rem; }}
    .theme-toggle,.nav-link {{
      font-size:.78rem; color:var(--muted); background:var(--surface);
      padding:6px 12px; border:1px solid var(--border); border-radius:6px;
      cursor:pointer; transition:color .15s,border-color .15s;
      text-decoration:none; line-height:1.5;
    }}
    .theme-toggle:hover,.nav-link:hover {{ color:var(--text); border-color:var(--accent); }}
    .status-strip {{
      display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); overflow:hidden;
      background:var(--surface-raised); border:1px solid var(--border);
      border-radius:var(--r); box-shadow:var(--shadow);
    }}
    .status-item {{ min-width:0; padding:15px 18px; }}
    .status-item + .status-item {{ border-left:1px solid var(--border); }}
    .status-label {{
      display:block; margin-bottom:4px; color:var(--muted); font-size:.67rem;
      font-weight:700; letter-spacing:.07em; text-transform:uppercase;
    }}
    .status-value {{
      display:flex; align-items:center; gap:7px; min-width:0;
      color:var(--text); font-size:.83rem; font-weight:650;
      font-variant-numeric:tabular-nums; white-space:nowrap; overflow:hidden;
      text-overflow:ellipsis;
    }}
    .status-dot {{
      width:8px; height:8px; flex:0 0 auto; border-radius:50%;
      background:#22c55e; box-shadow:0 0 0 3px rgba(34,197,94,.13);
    }}
    .card {{ transition:border-color .15s,box-shadow .15s; }}
    .card:hover {{ border-color:var(--border-strong); }}
    @media (max-width:640px) {{
      body {{ padding:22px 12px 36px; }}
      .page {{ gap:14px; }}
      header {{ align-items:flex-start; gap:14px; }}
      .header-actions {{ flex-wrap:wrap; justify-content:flex-end; }}
      .status-strip {{ grid-template-columns:1fr; }}
      .status-item {{ padding:12px 16px; }}
      .status-item + .status-item {{
        border-left:0; border-top:1px solid var(--border);
      }}
      .input-row,.file-row {{ display:flex; flex-direction:column; }}
      .input-row .btn,.file-row .btn {{ width:100%; }}
      .q-item {{ display:grid; grid-template-columns:auto minmax(0,1fr); }}
      .remove-form {{ grid-column:2; }}
      .log-bar {{ align-items:flex-start; }}
      .log-controls {{ flex-wrap:wrap; }}
      .log-line {{ gap:7px; padding:8px 10px; }}
      .log-time {{ min-width:56px; }}
    }}
    @media (max-width:440px) {{
      header {{ flex-direction:column; }}
      .header-actions {{ width:100%; justify-content:flex-start; }}
      .card {{ padding:18px; }}
      .log-time {{ display:none; }}
    }}
      </style>
    </head>
    <body>
      <div class="page">
    <header>
      <div class="brand">
        <h1>Podcast Downloader</h1>
        <p>YouTube to MP3</p>
      </div>
      <div class="header-actions">
        <a class="nav-link" href="/help">Help</a>
        <button class="theme-toggle" id="theme-toggle" type="button">Dark</button>
        <form method="post" action="/logout" style="margin:0">
          <input type="hidden" name="csrf_token" value="{safe_token}" />
          <button type="submit" class="logout-btn">Logout</button>
        </form>
      </div>
    </header>

    <section class="status-strip" aria-label="System status">
      <div class="status-item">
        <span class="status-label">Service</span>
        <span class="status-value"><span class="status-dot"></span>Online</span>
      </div>
      <div class="status-item">
        <span class="status-label">Monitored URLs</span>
        <span class="status-value">{count}</span>
      </div>
      <div class="status-item">
        <span class="status-label">Last activity</span>
        <span class="status-value">{last_activity}</span>
      </div>
    </section>

    <div class="card">
      <span class="card-label">Add to queue</span>
      {msg_html}
      <form method="post" action="/add-url">
        <input type="hidden" name="csrf_token" value="{safe_token}" />
        <div class="input-row">
          <input id="url" name="url" type="text"
            placeholder="https://www.youtube.com/watch?v=...  or  /@channel"
            autocomplete="off" autocapitalize="none" spellcheck="false" required />
          <button type="submit" class="btn">Add</button>
        </div>
        {bypass_row_html}
      </form>
    </div>

    <div class="card">
      <div class="card-row">
        <span class="card-label" style="margin:0">Monitored URLs (<code>urls.txt</code>)</span>
        <span class="badge">{count}</span>
      </div>
      {queue_html}
    </div>

    <div class="card">
      <div class="log-bar">
        <div class="log-controls">
          <span class="card-label" style="margin:0">Logs</span>
          <select id="log-source" class="log-source" aria-label="Log source">
            <option value="activity" selected>Activity</option>
            <option value="download">Download log</option>
          </select>
        </div>
        <div class="log-controls">
          <span id="log-ts"></span>
          <label><input type="checkbox" id="auto-cb" checked> Auto</label>
          <button class="btn-ghost" id="refresh-logs" type="button">Refresh</button>
        </div>
      </div>
      <div id="log-box"><div class="log-empty">Loading logs…</div></div>
    </div>

    <div class="card">
      <span class="card-label">YouTube cookies</span>
      <form method="post" action="/upload-cookies" enctype="multipart/form-data">
        <input type="hidden" name="csrf_token" value="{safe_token}" />
        <div class="file-row">
          <input id="cookie-file" name="cookie_file" type="file"
            accept=".txt,text/plain" required />
          <button type="submit" class="btn">Upload</button>
        </div>
      </form>
    </div>
      </div>

      <script nonce="{script_nonce}">
    let timer = null;
    const savedTheme = localStorage.getItem('podcast-theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const themeButton = document.getElementById('theme-toggle');

    function applyTheme(theme) {{
      document.body.classList.toggle('theme-dark', theme === 'dark');
      document.body.classList.toggle('theme-light', theme === 'light');
      themeButton.textContent = theme === 'dark' ? 'Light' : 'Dark';
    }}

    applyTheme(savedTheme || (prefersDark ? 'dark' : 'light'));
    themeButton.addEventListener('click', () => {{
      const nextTheme = document.body.classList.contains('theme-dark') ? 'light' : 'dark';
      localStorage.setItem('podcast-theme', nextTheme);
      applyTheme(nextTheme);
    }});

    function esc(s) {{
      return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }}

    function classifyActivity(message) {{
      if (/^Downloaded:/i.test(message)) return 'ok';
      if (/^Failed:/i.test(message)) return 'err';
      if (/^Waiting for age gate:/i.test(message)) return 'warn';
      if (/^Skipped Short:/i.test(message)) return 'warn';
      if (/^Run finished:/i.test(message) || /^Playlist run finished:/i.test(message)) return 'info';
      if (/^Retention cleanup|^Deleted expired/i.test(message)) return 'dim';
      if (/^No activity yet\\./i.test(message)) return 'empty';
      return 'neutral';
    }}

    function classifyDownload(level, message) {{
      const upper = level.toUpperCase();
      if (upper === 'ERROR' || upper === 'CRITICAL') return 'err';
      if (upper === 'WARNING') return 'warn';
      if (upper === 'DEBUG') return 'dim';
      if (/failed|error|timed out/i.test(message)) return 'err';
      if (/waiting|skipped/i.test(message)) return 'warn';
      if (/downloaded|finished|success/i.test(message)) return 'ok';
      return 'info';
    }}

    function activityBadge(kind) {{
      const labels = {{ ok: 'Done', err: 'Fail', warn: 'Wait', info: 'Run', dim: 'Keep', neutral: 'Log' }};
      return labels[kind] || 'Log';
    }}

    function renderLogLine(kind, timeLabel, badge, message, fullTimestamp) {{
      const safeTime = esc(timeLabel);
      const safeBadge = esc(badge);
      const safeMessage = esc(message);
      const safeTitle = fullTimestamp ? ' title="' + esc(fullTimestamp) + '"' : '';
      return (
        '<div class="log-line log-line--' + kind + '"' + safeTitle + '>' +
          '<span class="log-time">' + safeTime + '</span>' +
          '<span class="log-badge log-badge--' + kind + '">' + safeBadge + '</span>' +
          '<span class="log-msg">' + safeMessage + '</span>' +
        '</div>'
      );
    }}

    function renderDownloadLine(kind, timeLabel, level, message, fullTimestamp) {{
      const safeTime = esc(timeLabel);
      const safeLevel = esc(level);
      const safeMessage = esc(message);
      const safeTitle = fullTimestamp ? ' title="' + esc(fullTimestamp) + '"' : '';
      return (
        '<div class="log-line log-line--' + kind + '"' + safeTitle + '>' +
          '<span class="log-time">' + safeTime + '</span>' +
          '<span class="log-level log-level--' + kind + '">' + safeLevel + '</span>' +
          '<span class="log-msg">' + safeMessage + '</span>' +
        '</div>'
      );
    }}

    function renderLogLines(raw, source) {{
      const lines = raw.split('\\n');
      if (!lines.length || (lines.length === 1 && !lines[0].trim())) {{
        return '<div class="log-empty">No entries yet.</div>';
      }}

      const rendered = lines.map(line => {{
        if (!line.trim()) return '';

        if (source === 'download') {{
          if (/^No log entries yet\\./i.test(line)) {{
            return '<div class="log-empty">' + esc(line) + '</div>';
          }}

          const downloadMatch = line.match(/^\\[([^\\]]+)\\]\\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL):\\s*(.*)$/);
          if (downloadMatch) {{
            const timestamp = downloadMatch[1];
            const level = downloadMatch[2];
            const message = downloadMatch[3];
            const kind = classifyDownload(level, message);
            const timeLabel = timestamp.includes(' ') ? timestamp.split(' ')[1] : timestamp;
            return renderDownloadLine(kind, timeLabel, level, message, timestamp);
          }}
        }} else {{
          if (/^No activity yet\\./i.test(line)) {{
            return '<div class="log-empty">' + esc(line) + '</div>';
          }}

          const activityMatch = line.match(/^\\[([^\\]]+)\\]\\s*(.*)$/);
          if (activityMatch) {{
            const timestamp = activityMatch[1];
            const message = activityMatch[2];
            const kind = classifyActivity(message);
            const timeLabel = timestamp.includes(' ') ? timestamp.split(' ')[1] : timestamp;
            return renderLogLine(kind, timeLabel, activityBadge(kind), message, timestamp);
          }}
        }}

        const fallbackKind =
          /Failed|Error|Timed out/i.test(line) ? 'err' :
          /Waiting|Skipped/i.test(line) ? 'warn' :
          /Downloaded|finished/i.test(line) ? 'ok' :
          'neutral';
        return renderLogLine(fallbackKind, '—', activityBadge(fallbackKind), line, '');
      }}).filter(Boolean);

      return rendered.join('') || '<div class="log-empty">No entries yet.</div>';
    }}

    const logSourceSelect = document.getElementById('log-source');

    async function loadLogs() {{
      try {{
        const source = logSourceSelect.value;
        const r = await fetch('/logs?source=' + encodeURIComponent(source));
        if (!r.ok) return;
        const text = await r.text();
        const box = document.getElementById('log-box');
        const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
        box.innerHTML = renderLogLines(text, source);
        if (atBottom) box.scrollTop = box.scrollHeight;
        document.getElementById('log-ts').textContent = new Date().toLocaleTimeString();
      }} catch (_) {{}}
    }}

    function setAuto(on) {{
      clearInterval(timer);
      if (on) timer = setInterval(loadLogs, 15000);
    }}

    document.getElementById('auto-cb').addEventListener('change', e => setAuto(e.target.checked));
    document.getElementById('refresh-logs').addEventListener('click', loadLogs);
    logSourceSelect.addEventListener('change', loadLogs);
    loadLogs();
    setAuto(true);
      </script>
    </body>
    </html>
    """,
        headers=headers,
    )
