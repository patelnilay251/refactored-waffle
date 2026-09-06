"""Roof forms inferred from footprint shape.

OSM tags `roof:shape` on 1% of this site, so the form has to come from the
plan. Inward buffering does it: offsetting a footprint inward and lifting the
result gives a slope, and two offsets at different rates give a steep lower
pitch meeting a shallow upper one — which is a mansard, and Soho terraces are
full of them. A narrow plan naturally collapses to a ridge, giving a hipped
roof, without any special case.

Roofs are additive. They sit on top of the existing shell rather than
replacing its cap, so nothing in the facade code has to change; the cornice
already generated at the wall head reads as the parapet it would be in
reality, with the roof rising behind it.

Large modern blocks are left flat, which is not a limitation but the truth
about them.
"""

from __future__ import annotations

from shapely.geometry import Polygon

# Above this a building is a post-war block with a flat roof and plant on it.
MAX_PITCHED_HEIGHT_M = 26.0

# A plan wider than this does not get spanned by a domestic roof.
MAX_HALF_WIDTH_M = 11.0

# Below this the footprint is too slight to carry a roof worth meshing.
MIN_HALF_WIDTH_M = 0.9
MIN_AREA_M2 = 12.0

# Mansard proportions. The lower slope is steep enough to contain a storey,
# the upper shallow enough to shed water — roughly 68 and 24 degrees.
LOWER_INSET = 0.34
LOWER_PITCH = 2.5
UPPER_INSET = 0.55
UPPER_PITCH = 0.45

MAX_RISE_M = 3.6

FLAT_KINDS = {"office", "industrial", "warehouse", "commercial", "civic",
              "public", "school", "university", "hospital"}


def half_width(polygon: Polygon) -> float:
    """Approximate inradius.

    For a long rectangle, area over perimeter is half the short side, which is
    exactly the quantity that decides whether a roof can span the plan.
    """
    if polygon.length <= 0:
        return 0.0
    return polygon.area / polygon.length


def _shrink(polygon: Polygon, inset: float):
    """Buffer inward, retreating if the plan collapses."""
    for attempt in range(4):
        inner = polygon.buffer(-inset)
        if not inner.is_empty:
            if inner.geom_type == "MultiPolygon":
                inner = max(inner.geoms, key=lambda p: p.area)
            if inner.area >= 0.5:
                return inner, inset
        inset *= 0.55
    return None, 0.0


def form(footprint: list[tuple[float, float]], height: float,
         kind: str) -> list[tuple[Polygon, float]] | None:
    """Stacked rings and their heights, outermost first. None means flat.

    The first ring sits at the wall head, so the roof rises above the tagged
    height. That is deliberate: an OSM height is usually to the eaves or
    parapet, and a real roof stands above it.
    """
    polygon = Polygon(footprint)
    if not polygon.is_valid or polygon.area < MIN_AREA_M2:
        return None
    if height > MAX_PITCHED_HEIGHT_M or kind in FLAT_KINDS:
        return None

    reach = half_width(polygon)
    if reach < MIN_HALF_WIDTH_M or reach > MAX_HALF_WIDTH_M:
        return None

    levels: list[tuple[Polygon, float]] = [(polygon, height)]

    lower, used = _shrink(polygon, reach * LOWER_INSET)
    if lower is None:
        return None
    rise = min(used * LOWER_PITCH, MAX_RISE_M * 0.8)
    levels.append((lower, height + rise))

    upper, used = _shrink(lower, half_width(lower) * UPPER_INSET)
    if upper is not None:
        extra = min(used * UPPER_PITCH, MAX_RISE_M - rise)
        if extra > 0.05:
            levels.append((upper, levels[-1][1] + extra))

    return levels


def build(scene_data: dict) -> list[dict]:
    """Roof forms for every building that should have one."""
    roofs = []
    for building in scene_data["buildings"]:
        levels = form(building["footprint"], building["height_m"],
                      building["kind"])
        if levels:
            roofs.append({"osm_id": building["osm_id"], "levels": levels})
    return roofs


def summarise(roofs: list[dict], total: int) -> str:
    ridged = sum(1 for r in roofs if len(r["levels"]) == 2)
    mansard = len(roofs) - ridged
    return (f"{len(roofs)} of {total} pitched "
            f"({mansard} mansard, {ridged} hipped)  "
            f"{total - len(roofs)} left flat")
