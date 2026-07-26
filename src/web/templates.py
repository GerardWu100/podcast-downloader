"""Render browser-facing HTML pages without mutating application state."""

from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi.responses import HTMLResponse

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
