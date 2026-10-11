"""Fill a data folder with sample sources and activity for README screenshots.

The sources are real public finance podcasts with real episode titles and IDs,
chosen for the screenshot rather than taken from the operator's own queue, so
a screenshot never shows what the operator really listens to. The activity
covers one run two days ago and one this morning, with each badge the queue
page can show. The run results themselves are invented.

Usage::

    uv run python scripts/seed_demo_data.py <empty data folder>
    PODCAST_DATA_DIR=<that folder> uv run uvicorn src.api:app --port 8765

Every source already has a name in ``source_names.json``, so the server makes
no ``yt-dlp`` lookups while it runs.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, time, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The scheduled run hour in the checked-in config.toml.
RUN_HOUR = 6
# Days between the two runs shown, matching scheduled_run_interval_days.
DAYS_BETWEEN_RUNS = 2

# Queue URL -> name shown on the queue page; "author" adds "by ..." after a
# playlist or video.
DEMO_SOURCES: dict[str, dict[str, str]] = {
    "https://www.youtube.com/@oddsonopen": {"name": "Odds on Open"},
    "https://www.youtube.com/@TheCompoundNews": {"name": "The Compound"},
    "https://www.youtube.com/@ChatWithTradersPodcast": {"name": "Chat With Traders"},
    "https://www.youtube.com/playlist?list=PLcoICCEXGRDnnH8musCON6oY4oFkMnlHk": {
        "name": "Flirting with Models - Season 7",
        "author": "Flirting with Models",
    },
    "https://www.youtube.com/watch?v=bhj91yIl0aE": {
        "name": "Behind the Podcast: Flirting with Models | Corey Hoffstein",
        "author": "Excess Returns",
    },
}

# (minutes after the run hour, activity message) for the earlier run.
EARLIER_RUN_EVENTS = [
    (0, "Run started: 5 sources in the queue"),
    (
        3,
        "Downloaded: Odds on Open - Ex-Lehman Trader: AI Won't Give You Edge [E-kC8n9Q1_E].mp3",
    ),
    (
        6,
        "Downloaded: The Compound - Is Gen Z Completely Cooked? | TCAF 262 [yNY6Zz6D2tU].mp3",
    ),
    (8, "Skipped Short: youtube.com/shorts/Z09J2biOYX8"),
    (
        9,
        "Deleted expired MP3: The Compound - Will Higher Rates Kill the Stock Market? | Animal Spirits 484 [cgQFyAYuWeA].mp3",
    ),
    (9, "Retention cleanup deleted 1 MP3(s)"),
    (9, "Run finished: 2 successful, 0 failed"),
]

# (minutes after the run hour, activity message) for this morning's run.
TODAY_RUN_EVENTS = [
    (0, "Run started: 5 sources in the queue"),
    (
        4,
        "Downloaded: The Compound - This Is Where the Rubber Meets the Road | TCAF 263 [r1AsyhNNOno].mp3",
    ),
    (
        8,
        "Downloaded: Excess Returns - Behind the Podcast: Flirting with Models | Corey Hoffstein [bhj91yIl0aE].mp3",
    ),
    (9, "Waiting for age gate: youtube.com/watch?v=c3-j5E9F4OA"),
    (11, "Failed: youtube.com/watch?v=6lyl7flPOOU - HTTP Error 403: Forbidden"),
    (
        15,
        "Downloaded: Flirting with Models - Lucas Schuermann - Swapping Out Perpetual Futures (S7E34) [_5bYsyJUx68].mp3",
    ),
    (15, "Run finished: 3 successful, 1 failed"),
]


def _activity_lines(run_day: datetime, events: list[tuple[int, str]]) -> list[str]:
    """Turn (minute offset, message) pairs into ``[YYYY-MM-DD HH:MM] message`` lines."""
    run_start = datetime.combine(run_day.date(), time(RUN_HOUR))
    return [
        f"[{(run_start + timedelta(minutes=minutes)):%Y-%m-%d %H:%M}] {message}"
        for minutes, message in events
    ]


def seed_demo_data(data_dir: Path, today: datetime) -> None:
    """Write config, queue, names, activity, and run state into ``data_dir``.

    Parameters
    ----------
    data_dir:
        Folder the server will use as ``PODCAST_DATA_DIR``. Created if absent.
    today:
        Local date of this morning's run; the earlier run is two days before.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(PROJECT_ROOT / "config.toml", data_dir / "config.toml")

    (data_dir / "urls.txt").write_text("\n".join(DEMO_SOURCES) + "\n", encoding="utf-8")
    (data_dir / "source_names.json").write_text(
        json.dumps(DEMO_SOURCES, indent=2), encoding="utf-8"
    )

    earlier_day = today - timedelta(days=DAYS_BETWEEN_RUNS)
    activity = _activity_lines(earlier_day, EARLIER_RUN_EVENTS) + _activity_lines(
        today, TODAY_RUN_EVENTS
    )
    (data_dir / "activity.log").write_text("\n".join(activity) + "\n", encoding="utf-8")

    run_start = datetime.combine(today.date(), time(RUN_HOUR)).astimezone()
    run_end = run_start + timedelta(minutes=TODAY_RUN_EVENTS[-1][0])
    (data_dir / "run_state.json").write_text(
        json.dumps(
            {
                "started_at": run_start.isoformat(),
                "finished_at": run_end.isoformat(),
                "kind": "scheduled",
                "is_running": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dir", type=Path, help="empty folder to fill")
    args = parser.parse_args()
    seed_demo_data(args.data_dir.resolve(), datetime.now())
    print(f"Demo data written to {args.data_dir}")


if __name__ == "__main__":
    main()
