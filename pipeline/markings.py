"""Road markings.

Derived from the surfaces rather than authored. Double yellows run a fixed
offset in from the kerb, so they fall straight out of buffering the
carriageway boundary inward; lane dashes come from the centrelines that were
already fetched; crossings sit on the surveyed OSM nodes.

Double yellows matter more than their size suggests. They are the single most
recognisably British thing on a street surface, and their absence is what
makes an otherwise correct UK street read as generic.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

# Distance in from the kerb to the outer yellow, and the gap between the pair.
YELLOW_OFFSET_M = 0.32
YELLOW_GAP_M = 0.16
YELLOW_WIDTH_M = 0.09

DASH_LENGTH_M = 2.0
DASH_GAP_M = 4.0
DASH_WIDTH_M = 0.10

# UK zebra bars are 500 mm wide, laid across the carriageway, each running the
# depth of the crossing in the direction of travel.
ZEBRA_BAR_W = 0.50
ZEBRA_DEPTH_M = 2.4

PEDESTRIAN_TYPES = {"pedestrian", "footway", "path", "steps", "living_street"}


def _strip(geometry, width: float):
    """A thin band centred on a line."""
    if geometry.is_empty:
        return Polygon()
    return geometry.buffer(width / 2, cap_style="flat", join_style="round")


def double_yellows(carriageway) -> Polygon:
    """Waiting restrictions along both kerbs."""
    if carriageway.is_empty:
        return Polygon()
    bands = []
    for offset in (YELLOW_OFFSET_M, YELLOW_OFFSET_M + YELLOW_GAP_M):
        inset = carriageway.buffer(-offset)
        if inset.is_empty:
            continue
        bands.append(_strip(inset.boundary, YELLOW_WIDTH_M))
    if not bands:
        return Polygon()
    # Trim anything that strayed outside the road itself.
    return unary_union(bands).intersection(carriageway)


def lane_dashes(roads: list[dict], carriageway) -> Polygon:
    """Broken centre line on two-way carriageways.

    One-way streets get nothing, which is most of Soho — putting a centre line
    down a one-way street is a mistake that reads instantly to anyone who
    drives.
    """
    if carriageway.is_empty:
        return Polygon()

    pieces = []
    for road in roads:
        if road["highway"] in PEDESTRIAN_TYPES or road["oneway"]:
            continue
        if road["width_m"] < 6.0 or len(road["centreline"]) < 2:
            continue
        line = LineString(road["centreline"])
        step = DASH_LENGTH_M + DASH_GAP_M
        travelled = 0.0
        while travelled + DASH_LENGTH_M < line.length:
            start = line.interpolate(travelled)
            end = line.interpolate(travelled + DASH_LENGTH_M)
            pieces.append(_strip(LineString([start, end]), DASH_WIDTH_M))
            travelled += step

    if not pieces:
        return Polygon()
    return unary_union(pieces).intersection(carriageway.buffer(-0.8))


def crossings(furniture: list[dict], roads: list[dict], carriageway) -> Polygon:
    """Zebra bars at surveyed crossing nodes."""
    if carriageway.is_empty:
        return Polygon()

    vehicle = [r for r in roads
               if r["highway"] not in PEDESTRIAN_TYPES and len(r["centreline"]) > 1]
    if not vehicle:
        return Polygon()

    bars = []
    for item in furniture:
        if item["kind"] != "highway=crossing":
            continue
        here = Point(item["position"])
        if not carriageway.buffer(1.0).contains(here):
            continue

        # Take the road direction from the nearest carriageway centreline.
        line = min((LineString(r["centreline"]) for r in vehicle),
                   key=lambda l: l.distance(here))
        along = line.project(here)
        ahead = line.interpolate(min(along + 1.0, line.length))
        behind = line.interpolate(max(along - 1.0, 0.0))
        dx, dy = ahead.x - behind.x, ahead.y - behind.y
        norm = math.hypot(dx, dy)
        if norm < 1e-6:
            continue
        dx, dy = dx / norm, dy / norm
        nx, ny = -dy, dx

        # Bars run along the direction of travel, repeating across the road.
        for step in range(-6, 7):
            offset = step * ZEBRA_BAR_W * 2
            cx, cy = here.x + nx * offset, here.y + ny * offset
            bar = LineString([
                (cx - dx * ZEBRA_DEPTH_M / 2, cy - dy * ZEBRA_DEPTH_M / 2),
                (cx + dx * ZEBRA_DEPTH_M / 2, cy + dy * ZEBRA_DEPTH_M / 2),
            ])
            bars.append(_strip(bar, ZEBRA_BAR_W))

    if not bars:
        return Polygon()
    return unary_union(bars).intersection(carriageway.buffer(-0.15))


def build(scene_data: dict, surfaces: dict) -> dict:
    """All markings for a scene, as polygons ready to mesh."""
    carriageway = surfaces["carriageway"]
    zebra = crossings(scene_data.get("furniture", []), scene_data["roads"],
                      carriageway)
    # Yellows stop at a crossing; so do lane dashes.
    keep_clear = zebra.buffer(0.6) if not zebra.is_empty else Polygon()

    yellow = double_yellows(carriageway)
    white = lane_dashes(scene_data["roads"], carriageway)
    if not keep_clear.is_empty:
        yellow = yellow.difference(keep_clear)
        white = white.difference(keep_clear)

    return {"yellow": yellow, "white": unary_union([white, zebra])}


def summarise(markings: dict) -> str:
    return "  ".join(f"{name} {geom.area:.0f} m2"
                     for name, geom in markings.items())
