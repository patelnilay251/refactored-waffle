"""Turning road centrelines into street surfaces.

OSM gives centrelines, not surfaces, so the carriageway has to be generated.
The hard part is normally junctions — where four buffered strips meet, naive
approaches leave gaps or overlapping slivers. Buffering with round joins and
then unioning sidesteps the problem entirely: the union *is* the junction, and
the rounding it leaves at each corner is a fair approximation of a real kerb
radius, which streets have anyway.

Pavement is then defined negatively. Rather than guessing a width, it is
whatever is left of the street void once the carriageway and the buildings are
taken out of it — so on a 9.5 m Soho street the pavement automatically comes
out at the ~1.25 m it really is, and widens where the street widens.
"""

from __future__ import annotations

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

# Smoothness of buffered ends and corners. Eight segments per quadrant is well
# past what reads at street level and keeps the union cheap.
QUAD_SEGMENTS = 8

# How far pavement may reach from the carriageway edge. Buildings clip it long
# before this on narrow streets; it only binds where a street opens out.
PAVEMENT_REACH_M = 3.0

# Footways are mapped as centrelines too, and 2.5 m is a generous pavement.
FOOTWAY_TRIM = 0.8

# Anything narrower than this after clipping is a sliver from a near-tangent
# overlap, not a surface worth meshing.
MIN_SURFACE_AREA_M2 = 0.5

# Street types with no carriageway: the whole void is paved.
PEDESTRIAN_TYPES = {"pedestrian", "footway", "path", "steps", "living_street"}

# Overpass returns whole ways, so a road clipped by the query bbox still
# arrives with its full geometry and can run hundreds of metres past the site.
# Surfaces are therefore clipped to the built area, grown by this much: paving
# stops a little beyond the last building instead of trailing off into nothing.
# Grown from the buildings rather than the bbox so the edge follows the shape
# of the block rather than cutting a straight line across every street.
CLIP_REACH_M = 14.0


def _buffered(roads: list[dict], scale: float = 1.0) -> list[Polygon]:
    shapes = []
    for road in roads:
        if len(road["centreline"]) < 2:
            continue
        line = LineString(road["centreline"])
        if line.length <= 0:
            continue
        shapes.append(line.buffer(
            road["width_m"] * scale / 2,
            quad_segs=QUAD_SEGMENTS,
            cap_style="round",
            join_style="round",
        ))
    return shapes


def _clean(geometry, buildings, limit=None):
    """Clip against buildings and the site limit, then drop slivers."""
    if geometry.is_empty:
        return geometry
    geometry = geometry.difference(buildings)
    if limit is not None:
        geometry = geometry.intersection(limit)
    if geometry.geom_type == "Polygon":
        return geometry if geometry.area >= MIN_SURFACE_AREA_M2 else Polygon()
    parts = [g for g in getattr(geometry, "geoms", [])
             if g.geom_type == "Polygon" and g.area >= MIN_SURFACE_AREA_M2]
    return unary_union(parts) if parts else Polygon()


def build_surfaces(scene_data: dict) -> dict:
    """Carriageway and pavement polygons for a stage-1 scene."""
    buildings = unary_union([Polygon(b["footprint"])
                             for b in scene_data["buildings"]])

    limit = buildings.buffer(CLIP_REACH_M, quad_segs=QUAD_SEGMENTS)

    roads = scene_data["roads"]
    vehicle = [r for r in roads if r["highway"] not in PEDESTRIAN_TYPES]
    walked = [r for r in roads if r["highway"] in PEDESTRIAN_TYPES]

    carriageway = _clean(unary_union(_buffered(vehicle)), buildings, limit)

    # Pavement: the band flanking the carriageway, plus everywhere pedestrians
    # are explicitly mapped, minus the carriageway itself.
    reach = (carriageway.buffer(PAVEMENT_REACH_M, quad_segs=QUAD_SEGMENTS)
             if not carriageway.is_empty else Polygon())
    walkways = unary_union(_buffered(walked, scale=FOOTWAY_TRIM))
    pavement = _clean(unary_union([reach, walkways]).difference(carriageway),
                      buildings, limit)

    return {
        "carriageway": carriageway,
        "pavement": pavement,
        "buildings": buildings,
        "vehicle_ways": len(vehicle),
        "walked_ways": len(walked),
    }


def summarise(surfaces: dict) -> str:
    carriageway = surfaces["carriageway"]
    pavement = surfaces["pavement"]

    def parts(geometry):
        return len(getattr(geometry, "geoms", [geometry]))

    return (f"carriageway {carriageway.area:8.0f} m2 ({parts(carriageway)} parts)\n"
            f"pavement    {pavement.area:8.0f} m2 ({parts(pavement)} parts)")
