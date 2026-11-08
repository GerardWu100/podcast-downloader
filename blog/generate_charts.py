"""Generate the two architecture diagrams used by the podcast blog post.

The script reads fixed stage and gate labels from ``blog/data/pipeline.json``
and writes two high-resolution PNG files under ``blog/images``. It does not
inspect runtime state or contact external services.

Inputs
------
``data/pipeline.json``
    JSON object with ``pipeline`` and ``gates`` lists. Each pipeline item has
    ``title`` and ``detail`` strings. Each gate has ``title``, ``condition``,
    and ``on_failure`` strings.

Outputs
-------
``images/banner.png``
    Cover image: app icon, project name, and an episode with its ad cut out.
``images/pipeline-flow.png``
    Left-to-right view of the URL-to-library pipeline.
``images/reliability-gates.png``
    Layered view of the conditions that must hold before state is committed.
"""

from __future__ import annotations

import json
import math
import textwrap
from pathlib import Path

import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

BLOG_DIR = Path(__file__).resolve().parent
DATA_FILE = BLOG_DIR / "data" / "pipeline.json"
IMAGES_DIR = BLOG_DIR / "images"
FIGURE_DPI = 220
NAVY = "#081a2d"
PANEL = "#12314a"
CYAN = "#3dd7e8"
CORAL = "#ff6b4a"
AMBER = "#f4b942"
WHITE = "#f7fbff"
MUTED = "#b6c9d8"

# Banner (cover image). The icon copies the web app's own icon in
# ``src/web/static/icon-192.png``: a blue rounded square with a download arrow.
BANNER_ICON_BLUE = "#2563eb"
# Waveform bars: x range in data units, and the stretch cut out as a sponsor read.
WAVEFORM_LEFT, WAVEFORM_RIGHT = 5.3, 15.1
AD_LEFT, AD_RIGHT = 8.7, 11.3
WAVEFORM_BAR_STEP = 0.16


def _load_chart_data() -> dict[str, list[dict[str, str]]]:
    """Load and return the frozen chart labels.

    Returns
    -------
    dict[str, list[dict[str, str]]]
        Mapping with a ``pipeline`` list and a ``gates`` list.
    """

    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _add_rounded_box(
    axis: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    detail: str,
    accent: str,
) -> None:
    """Draw one labeled rounded pipeline box.

    Parameters
    ----------
    axis:
        Matplotlib axes receiving the shape and labels.
    x, y:
        Lower-left box coordinates in axes data units.
    width, height:
        Box dimensions in axes data units.
    title:
        Short stage label.
    detail:
        Longer explanatory label shown beneath the title.
    accent:
        Hex color used for the box edge and stage marker.
    """

    box = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.02,rounding_size=0.04",
        linewidth=1.7,
        edgecolor=accent,
        facecolor=PANEL,
    )
    axis.add_patch(box)
    axis.text(
        x + width / 2,
        y + height * 0.63,
        title,
        ha="center",
        va="center",
        color=WHITE,
        fontsize=11,
        fontweight="bold",
    )
    axis.text(
        x + width / 2,
        y + height * 0.30,
        "\n".join(textwrap.wrap(detail, width=22)),
        ha="center",
        va="center",
        color=MUTED,
        fontsize=8.2,
        linespacing=1.25,
    )


def generate_pipeline_flow(data: dict[str, list[dict[str, str]]]) -> None:
    """Create the left-to-right pipeline diagram.

    Parameters
    ----------
    data:
        Frozen chart data returned by :func:`_load_chart_data`.
    """

    stages = data["pipeline"]
    figure, axis = plt.subplots(figsize=(16, 6), constrained_layout=True)
    figure.patch.set_facecolor(NAVY)
    axis.set_facecolor(NAVY)
    axis.set_xlim(0, 15.8)
    axis.set_ylim(0, 5.5)
    axis.axis("off")

    axis.text(
        0.4,
        5.0,
        "A successful download is a pipeline, not an exit code",
        color=WHITE,
        fontsize=20,
        fontweight="bold",
        va="top",
    )
    axis.text(
        0.4,
        4.55,
        "External extraction is verified locally before the queue or archive changes.",
        color=MUTED,
        fontsize=11,
        va="top",
    )

    box_width = 1.75
    box_height = 1.65
    gap = 0.43
    start_x = 0.35
    y = 1.55
    accents = [CORAL, CORAL, CORAL, CYAN, CYAN, CYAN, AMBER]
    for index, (stage, accent) in enumerate(zip(stages, accents, strict=True)):
        x = start_x + index * (box_width + gap)
        _add_rounded_box(
            axis,
            x,
            y,
            box_width,
            box_height,
            stage["title"],
            stage["detail"],
            accent,
        )
        if index < len(stages) - 1:
            arrow = FancyArrowPatch(
                (x + box_width + 0.05, y + box_height / 2),
                (x + box_width + gap - 0.05, y + box_height / 2),
                arrowstyle="-|>",
                mutation_scale=13,
                linewidth=1.5,
                color=MUTED,
            )
            axis.add_patch(arrow)

    axis.text(
        0.4,
        0.55,
        "Source policy",
        color=CORAL,
        fontsize=9,
        fontweight="bold",
    )
    axis.text(6.9, 0.55, "Local proof", color=CYAN, fontsize=9, fontweight="bold")
    axis.text(13.45, 0.55, "Durable state", color=AMBER, fontsize=9, fontweight="bold")

    figure.savefig(IMAGES_DIR / "pipeline-flow.png", dpi=FIGURE_DPI, facecolor=NAVY)
    plt.close(figure)


def generate_reliability_gates(data: dict[str, list[dict[str, str]]]) -> None:
    """Create a layered diagram of the pipeline's reliability gates.

    Parameters
    ----------
    data:
        Frozen chart data returned by :func:`_load_chart_data`.
    """

    gates = data["gates"]
    figure, axis = plt.subplots(figsize=(14, 8), constrained_layout=True)
    figure.patch.set_facecolor(NAVY)
    axis.set_facecolor(NAVY)
    axis.set_xlim(0, 14)
    axis.set_ylim(0, 9)
    axis.axis("off")

    axis.text(
        0.6,
        8.55,
        "Five gates protect the library and its state",
        color=WHITE,
        fontsize=21,
        fontweight="bold",
        va="top",
    )
    axis.text(
        0.6,
        8.08,
        "Failure stays retryable; ambiguous retention metadata keeps the file.",
        color=MUTED,
        fontsize=11,
        va="top",
    )

    for index, gate in enumerate(gates):
        y = 6.75 - index * 1.33
        accent = CYAN if index < 4 else AMBER
        number_box = FancyBboxPatch(
            (0.65, y),
            0.72,
            0.72,
            boxstyle="round,pad=0.02,rounding_size=0.16",
            facecolor=accent,
            edgecolor=accent,
        )
        axis.add_patch(number_box)
        axis.text(
            1.01,
            y + 0.36,
            str(index + 1),
            ha="center",
            va="center",
            color=NAVY,
            fontsize=12,
            fontweight="bold",
        )
        gate_box = FancyBboxPatch(
            (1.65, y - 0.08),
            11.65,
            0.88,
            boxstyle="round,pad=0.03,rounding_size=0.08",
            facecolor=PANEL,
            edgecolor="#244e6a",
            linewidth=1.2,
        )
        axis.add_patch(gate_box)
        axis.text(
            1.95,
            y + 0.48,
            gate["title"],
            color=WHITE,
            fontsize=11,
            fontweight="bold",
            va="center",
        )
        axis.text(
            4.6,
            y + 0.48,
            gate["condition"],
            color=CYAN,
            fontsize=10,
            va="center",
        )
        axis.text(
            1.95,
            y + 0.12,
            f"If it fails: {gate['on_failure']}",
            color=MUTED,
            fontsize=9,
            va="center",
        )

    figure.savefig(
        IMAGES_DIR / "reliability-gates.png",
        dpi=FIGURE_DPI,
        facecolor=NAVY,
    )
    plt.close(figure)


def generate_banner() -> None:
    """Cover image: app icon, project name, and an episode with its ad cut out.

    Data units run x 0..16 and y 0..6, matching the 16x6-inch figure saved at
    100 dpi as a 1600x600 PNG. Bar heights come from a fixed sum of sines, so
    the output is identical on every run.
    """
    figure, axes = plt.subplots(figsize=(16, 6))
    figure.subplots_adjust(0, 0, 1, 1)
    figure.patch.set_facecolor(NAVY)
    axes.set_xlim(0, 16)
    axes.set_ylim(0, 6)
    axes.axis("off")

    # App icon: blue rounded square, white download arrow above a baseline.
    axes.add_patch(FancyBboxPatch((1.0, 1.35), 3.3, 3.3, boxstyle="round,pad=0,rounding_size=0.7",
                                  facecolor=BANNER_ICON_BLUE, edgecolor="none"))  # fmt: skip
    stroke = {"color": "white", "linewidth": 16, "solid_capstyle": "round", "solid_joinstyle": "round"}
    axes.plot([2.65, 2.65], [3.95, 2.55], **stroke)
    axes.plot([2.0, 2.65, 3.3], [3.2, 2.55, 3.2], **stroke)
    axes.plot([1.85, 3.45], [2.0, 2.0], **stroke)

    axes.text(5.2, 4.15, "Podcast Downloader", fontsize=44, fontweight="bold",
              color=WHITE, va="center", family="DejaVu Sans")  # fmt: skip

    # Episode waveform: vertical bars centred on y = 2.1, skipping the ad stretch.
    centre_y = 2.1
    bar_x = WAVEFORM_LEFT
    while bar_x <= WAVEFORM_RIGHT:
        if not AD_LEFT - 0.15 < bar_x < AD_RIGHT + 0.15:
            height = 0.25 + 0.55 * abs(math.sin(bar_x * 2.3) * math.cos(bar_x * 0.9) + 0.35 * math.sin(bar_x * 7.1))
            axes.plot([bar_x, bar_x], [centre_y - height, centre_y + height], color=CYAN,
                      linewidth=5, solid_capstyle="round")  # fmt: skip
        bar_x += WAVEFORM_BAR_STEP

    # The sponsor read: a coral "AD" block, struck through to show it is removed.
    axes.add_patch(FancyBboxPatch((AD_LEFT, centre_y - 0.7), AD_RIGHT - AD_LEFT, 1.4,
                                  boxstyle="round,pad=0,rounding_size=0.18", facecolor="none",
                                  edgecolor=CORAL, linewidth=3, linestyle="--"))  # fmt: skip
    # Slash first, then the letters with a navy outline, so "AD" stays readable on top.
    axes.plot([AD_LEFT + 0.35, AD_RIGHT - 0.35], [centre_y - 0.5, centre_y + 0.5], color=CORAL,
              linewidth=6, solid_capstyle="round", zorder=2)  # fmt: skip
    axes.text((AD_LEFT + AD_RIGHT) / 2, centre_y, "AD", fontsize=34, fontweight="bold",
              color=CORAL, ha="center", va="center", family="DejaVu Sans", zorder=3,
              path_effects=[path_effects.withStroke(linewidth=12, foreground=NAVY)])  # fmt: skip

    figure.savefig(IMAGES_DIR / "banner.png", dpi=100, facecolor=figure.get_facecolor())
    plt.close(figure)


def main() -> None:
    """Generate all blog charts from frozen local inputs."""

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    generate_banner()
    data = _load_chart_data()
    generate_pipeline_flow(data)
    generate_reliability_gates(data)


if __name__ == "__main__":
    main()
