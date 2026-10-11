# Podcast Downloader

Turn YouTube channels, playlists, and videos into **sponsor-free MP3 podcasts**
for [Audiobookshelf](https://www.audiobookshelf.org/). Add a channel once; new
episodes show up in your podcast app on their own.

```mermaid
flowchart LR
    A["YouTube channel,<br/>playlist, or video"] -->|"paste the URL once"| B["Podcast Downloader<br/>checks every 2 days"]
    B --> C["Waits until SponsorBlock<br/>has marked the sponsors"]
    C --> D["Downloads the audio,<br/>cuts the sponsors,<br/>saves an MP3"]
    D --> E["MP3 folder"]
    E --> F["Audiobookshelf"]
    F --> G["Your phone"]
```

![The web page: add a source, see the queue, and read what each run did](docs/images/web-ui.png)

## Install

You need a computer that stays on, with [Docker](https://docs.docker.com/engine/install/).
Nothing else: no clone, no build, no config file to write. The image works on
ordinary PCs and servers (amd64) and on Raspberry Pi or ARM servers (arm64).

### Option A: Docker Compose (recommended)

Save this as `docker-compose.yml` in an empty folder:

```yaml
services:
  podcast-downloader:
    image: ghcr.io/gerardwu100/podcast-downloader:latest
    container_name: podcast-downloader
    restart: unless-stopped
    ports:
      - "6847:8000"           # web page at http://<server>:6847
    environment:
      - TZ=America/Toronto    # your time zone; runs start at 06:00 on this clock
    volumes:
      - ~/.containers/podcast-downloader:/data   # settings, queue, cookies, logs
      - ~/downloads/podcasts:/downloads          # the MP3 library
      - ~/downloads/temporary:/temporary         # files still being processed
```

Then start it from that folder:

```bash
docker compose up -d
```

A [fully commented version](docker-compose.example.yml) of this file is in the
repository too. It also joins a Docker network named `single`, where a reverse
proxy or Apprise can reach it.

### Option B: one `docker run` command

```bash
docker run -d --name podcast-downloader --restart unless-stopped \
  -p 6847:8000 \
  -e TZ=America/Toronto \
  -v ~/.containers/podcast-downloader:/data \
  -v ~/downloads/podcasts:/downloads \
  -v ~/downloads/temporary:/temporary \
  ghcr.io/gerardwu100/podcast-downloader:latest
```

### Before you start: two things to check

| Check | Why | What to change |
|---|---|---|
| The left side of each `/data`, `/downloads`, `/temporary` line | Those are the folders on your computer | Any folder you like. Point Audiobookshelf at the `/downloads` one. |
| Run `id -u` and `id -g` | The MP3 files should belong to you | If either is not `1000`, add `HOST_UID` and `HOST_GID` with those numbers next to `TZ` |

Then open **`http://<server address>:6847`**. There is no login by default.

### Update

| Installed with | Update with |
|---|---|
| Compose | `docker compose pull && docker compose up -d` |
| `docker run` | `docker pull ghcr.io/gerardwu100/podcast-downloader:latest`, then `docker rm -f podcast-downloader`, then the same `docker run` command again |

Your settings, queue, and MP3s live in the folders, not in the container, so
updating never loses them. Nothing updates on its own.

## Use it

1. **Add a source.** Paste a channel, playlist, or video URL and select **Add**.
2. **Wait, or run now.** Runs start at 06:00 every other day. **Run queue now**
   starts one immediately.
3. **Listen.** In Audiobookshelf, add a podcast library that points at the MP3
   folder. Each channel becomes its own podcast.

```text
~/downloads/podcasts/
├── lexfridman/                  ← one folder per channel or playlist
│   ├── Lex Fridman - Episode 480 [a1b2c3d4e5f].mp3
│   └── Lex Fridman - Episode 481 [l1m2n3o4p5q].mp3
├── hubermanlab/
│   └── Huberman Lab - Sleep and Focus [f6g7h8i9j0k].mp3
└── singles/                     ← videos you added one by one
```

The activity panel shows what each run did. **Activity** is the short story,
**Detailed log** is the full output. Select a count such as **1 failed** to see
only those lines.

To put it on your phone's home screen, open the page over HTTPS in Chrome or
Safari and choose **Install app** or **Add to Home Screen**.

## Settings

| Setting | Default | Where |
|---|---|---|
| Delete channel episodes after N days | 30 days; videos added one by one are kept | Settings page |
| YouTube cookies, for when YouTube blocks downloads | none | Settings page |
| Alerts to Telegram, email, or Discord when something breaks | off | Settings page |
| Run time and how often | 06:00, every 2 days | `config.toml` |
| How many recent videos to check per channel | 2 | `config.toml` |

`config.toml` is in your settings folder (`~/.containers/podcast-downloader/`).
Edit it, then restart the container. Numbers and `true`/`false` are written
bare and text goes in quotes. A typo stops the container with a message that
names the setting, so check `docker logs podcast-downloader` if it will not
start.

### Add a password

With no login, anyone who can open the page can use it. That is fine on a home
network. Before you open it to the internet, put it behind HTTPS (a reverse
proxy such as Caddy or Cloudflare Tunnel) and turn the login on:

1. Edit `.env` in your settings folder. The first start created it.
2. Set `UI_USERNAME` and `UI_PASSWORD`.
3. Restart the container.

## Browser extension

Add the video you are watching with one click, without copying the URL.

| Browser | Install |
|---|---|
| Firefox 140+ | Download `podcast-downloader-firefox-<version>.xpi` from the [latest release](https://github.com/GerardWu100/podcast-downloader/releases/latest), drag it onto Firefox, and select **Add** |
| Chrome, Edge, Brave | Unzip `podcast-downloader-chrome-<version>.zip` from the [latest release](https://github.com/GerardWu100/podcast-downloader/releases/latest). Open `chrome://extensions`, turn on **Developer mode**, select **Load unpacked**, and choose the folder |

Click the toolbar icon and enter the page address, such as
`http://192.168.1.20:6847`, and your login. With the login off, any name and
password work. Select **Save**, then **Test connection**. After that:

- Click the icon or press `Alt+Shift+D` to add the current page.
- Right-click a YouTube or Rumble link to add it.

## Troubleshooting

| What you see | What to do |
|---|---|
| Downloads fail with `HTTP 403` or "Sign in to confirm you're not a bot" | YouTube is blocking the server. Export cookies from a browser where you are signed in to YouTube (`yt-dlp --cookies-from-browser chrome --cookies cookies.txt`) and upload the file on the Settings page. |
| The Settings page says cookies expire soon | Export and upload fresh cookies the same way. |
| A new video shows **Wait** | Normal. A new video waits a day so SponsorBlock can mark the sponsors. To skip the wait for one video, tick **Run now** when you add it. |
| The container keeps restarting | Run `docker logs podcast-downloader`. A bad `config.toml` line is named in the last lines. |
| The MP3 files belong to root or another user | Set `HOST_UID` and `HOST_GID` (see *Before you start*) and restart. |

## Learn more

The **[wiki](https://github.com/GerardWu100/podcast-downloader/wiki)** explains
how it works and how to change it: the download pipeline, every setting and
command-line flag, the login model, alerts, the extension's API, and how to run
and test the code from a checkout. It is built from the [`docs/`](docs/)
folder.

## License

[MIT](LICENSE)
