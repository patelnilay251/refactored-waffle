"""Stage 1 preview - draw the block so the geography can be eyeballed.

Two panels: resolved height, and where that height came from. The second panel
is the one that matters for trusting the model, since a third of the block's
heights are inferred rather than measured.

    python3 -m pipeline.preview [data/soho/scene.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon as MplPolygon

ROOT = Path(__file__).resolve().parent.parent

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_MUTED = "#52514e"

# Sequential blue ramp, steps 100..700, for continuous magnitude (height).
BLUE_RAMP = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
    "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
]
HEIGHT_CMAP = LinearSegmentedColormap.from_list("height", BLUE_RAMP)

# Categorical slots 1-3: the only three that validate on an all-pairs pairlist,
# which is what a map needs since every patch is compared against every other.
PROVENANCE_STYLE = {
    "tag:height": ("#2a78d6", "Measured - height tag"),
    "tag:levels": ("#2a78d6", "Measured - floor count"),
    "inferred:terrace": ("#eb6834", "Inferred - terrace neighbours"),
    "inferred:nearby": ("#1baf7a", "Inferred - nearby streetscape"),
    "default:type": ("#e34948", "Default - building type only"),
}

ROAD_INK = "#c3c2b7"
FOOTWAY_INK = "#dedcd4"


def _blank_axes(ax, extent, title, subtitle):
    half_x, half_y = extent[0] / 2, extent[1] / 2
    ax.set_xlim(-half_x, half_x)
    ax.set_ylim(-half_y, half_y)
    ax.set_aspect("equal")
    ax.set_facecolor(SURFACE)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, color=INK, fontsize=12, weight="bold", loc="left", pad=26)
    ax.text(0, 1.008, subtitle, transform=ax.transAxes,
            color=INK_MUTED, fontsize=8.5, va="bottom")


def _draw_roads(ax, roads):
    for road in roads:
        xs = [p[0] for p in road["centreline"]]
        ys = [p[1] for p in road["centreline"]]
        footway = road["is_footway"]
        ax.plot(xs, ys,
                color=FOOTWAY_INK if footway else ROAD_INK,
                linewidth=1.0 if footway else road["width_m"] * 0.55,
                solid_capstyle="round", zorder=1)


def _scale_bar(ax, extent, length_m=50):
    """Scale bar and north arrow, on a surface plate so they stay readable
    wherever they land on the map."""
    from matplotlib.patches import FancyBboxPatch

    x0 = -extent[0] / 2 + 14
    y0 = -extent[1] / 2 + 16
    ax.add_patch(FancyBboxPatch(
        (x0 - 8, y0 - 8), length_m + 16, 24,
        boxstyle="round,pad=0,rounding_size=3",
        facecolor=SURFACE, edgecolor="none", alpha=0.92, zorder=4))
    ax.plot([x0, x0 + length_m], [y0, y0], color=INK, linewidth=2,
            solid_capstyle="butt", zorder=5)
    ax.text(x0 + length_m / 2, y0 + 4, f"{length_m} m", color=INK,
            fontsize=8, ha="center", va="bottom", zorder=5)

    nx, ny = extent[0] / 2 - 20, -extent[1] / 2 + 16
    ax.add_patch(FancyBboxPatch(
        (nx - 10, ny - 8), 20, 34,
        boxstyle="round,pad=0,rounding_size=3",
        facecolor=SURFACE, edgecolor="none", alpha=0.92, zorder=4))
    ax.annotate("", xy=(nx, ny + 16), xytext=(nx, ny),
                arrowprops=dict(arrowstyle="-|>", color=INK, linewidth=1.2),
                zorder=5)
    ax.text(nx, ny + 17, "N", color=INK, fontsize=9, weight="bold",
            ha="center", va="bottom", zorder=5)


def render(scene: dict, out_path: Path) -> Path:
    buildings = scene["buildings"]
    extent = scene["extent_m"]
    heights = [b["height_m"] for b in buildings]
    norm = Normalize(vmin=min(heights), vmax=max(heights))

    fig, (ax_h, ax_p) = plt.subplots(1, 2, figsize=(15, 8.2), facecolor=SURFACE)

    _blank_axes(ax_h, extent, "Resolved height",
                f"{len(buildings)} buildings  ·  "
                f"{min(heights):.0f}-{max(heights):.0f} m")
    _blank_axes(ax_p, extent, "Where the height came from",
                "orange and green are inferred, not measured")

    for ax in (ax_h, ax_p):
        _draw_roads(ax, scene["roads"])

    for building in buildings:
        ring = building["footprint"]
        # A hairline in the surface colour keeps party-walled terraces legible
        # as separate buildings instead of one merged blob.
        ax_h.add_patch(MplPolygon(
            ring, closed=True, facecolor=HEIGHT_CMAP(norm(building["height_m"])),
            edgecolor=SURFACE, linewidth=0.7, zorder=2))
        colour, _ = PROVENANCE_STYLE.get(building["height_source"], ("#52514e", "?"))
        ax_p.add_patch(MplPolygon(
            ring, closed=True, facecolor=colour,
            edgecolor=SURFACE, linewidth=0.7, zorder=2))

    for ax in (ax_h, ax_p):
        _scale_bar(ax, extent)

    bar = fig.colorbar(
        plt.cm.ScalarMappable(norm=norm, cmap=HEIGHT_CMAP),
        ax=ax_h, orientation="horizontal", fraction=0.045, pad=0.03,
    )
    bar.set_label("metres", color=INK_MUTED, fontsize=9)
    bar.outline.set_visible(False)
    bar.ax.tick_params(colors=INK_MUTED, labelsize=8, length=0)

    present = {b["height_source"] for b in buildings}
    seen: list[str] = []
    handles = []
    for source, (colour, label) in PROVENANCE_STYLE.items():
        if source in present and label not in seen:
            seen.append(label)
            handles.append(Patch(facecolor=colour, edgecolor=SURFACE, label=label))
    handles += [
        Line2D([0], [0], color=ROAD_INK, lw=3, label="Carriageway"),
        Line2D([0], [0], color=FOOTWAY_INK, lw=1.5, label="Footway"),
    ]
    ax_p.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02),
                ncol=3, frameon=False, fontsize=8.5, labelcolor=INK_MUTED)

    fig.suptitle(scene["description"], color=INK, fontsize=14,
                 weight="bold", x=0.5, y=0.975)
    fig.text(0.5, 0.945,
             f"Stage 1 data layer  ·  OpenStreetMap via Overpass  ·  "
             f"{extent[0]:.0f} x {extent[1]:.0f} m  ·  local metric CRS",
             color=INK_MUTED, fontsize=9, ha="center")

    fig.tight_layout(rect=(0, 0.02, 1, 0.93))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140, facecolor=SURFACE)
    plt.close(fig)
    return out_path


def main(argv: list[str]) -> int:
    scene_path = Path(argv[1]) if len(argv) > 1 else ROOT / "data" / "soho" / "scene.json"
    scene = json.loads(scene_path.read_text())
    out = render(scene, ROOT / "out" / f"stage1_{scene['name']}.png")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
