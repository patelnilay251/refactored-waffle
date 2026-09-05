"""Placing the things that are not architecture.

Rooftops are usually the most neglected part of a city model and, from any
raised angle, a third of what the camera sees. London's are distinctive:
brick chimney stacks standing on the party walls between terraced houses, each
with a row of pots, plus later accretions of plant, tanks and aerials on the
flat commercial roofs.

Placement is deterministic — everything is seeded from the OSM id — so a
re-run produces the same city rather than a reshuffled one.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from shapely.geometry import LineString, Point, Polygon

# Chimneys belong to the older, lower stock. Above this the building is a
# post-war block and gets plant instead.
CHIMNEY_MAX_HEIGHT_M = 26.0
CHIMNEY_MIN_WALL_M = 3.0
CHIMNEY_KINDS = {"yes", "residential", "apartments", "house", "terrace",
                 "retail", "commercial", "hotel"}

# Plant needs a roof big enough to stand on.
PLANT_MIN_AREA_M2 = 160.0
PLANT_INSET_M = 2.5

STREETLIGHT_SPACING_M = 26.0
STREETLIGHT_KERB_OFFSET_M = 0.7
BOLLARD_SPACING_M = 4.2


@dataclass
class Prop:
    kind: str
    x: float
    y: float
    z: float
    yaw: float
    width: float
    depth: float
    height: float


def _rng(seed: int) -> random.Random:
    return random.Random(seed & 0xFFFFFFFF)


def _hidden_edges(footprint, polygons, tree, own_index):
    """Edges that abut a neighbour — the party walls a chimney stands on."""
    edges = []
    count = len(footprint)
    for i in range(count):
        start, end = footprint[i], footprint[(i + 1) % count]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < CHIMNEY_MIN_WALL_M:
            continue
        # Outward normal of a clockwise ring is to the edge's left.
        nx, ny = -dy / length, dx / length
        probe = Point(start[0] + dx / 2 + nx * 1.2, start[1] + dy / 2 + ny * 1.2)
        if any(index != own_index and polygons[index].contains(probe)
               for index in tree.query(probe)):
            edges.append((start, end, length, math.atan2(dy, dx)))
    return edges


def _chimneys(building, footprint, edges, rng) -> list[Prop]:
    props = []
    height = building["height_m"]
    for start, end, length, angle in edges:
        if rng.random() > 0.72:
            continue
        # Sit the stack on the party wall, a little in from the frontage.
        t = rng.uniform(0.3, 0.7)
        x = start[0] + (end[0] - start[0]) * t
        y = start[1] + (end[1] - start[1]) * t
        stack_h = rng.uniform(1.15, 1.95)
        width = rng.uniform(0.75, 1.25)
        props.append(Prop("chimney", x, y, height, angle, width, 0.5, stack_h))

        pots = max(2, int(width / 0.38))
        for p in range(pots):
            offset = (p - (pots - 1) / 2) * (width / pots)
            props.append(Prop(
                "pot",
                x + math.cos(angle) * offset, y + math.sin(angle) * offset,
                height + stack_h, angle,
                0.22, 0.22, rng.uniform(0.38, 0.62)))
    return props


def _roof_plant(building, polygon, rng) -> list[Prop]:
    if polygon.area < PLANT_MIN_AREA_M2:
        return []
    inner = polygon.buffer(-PLANT_INSET_M)
    if inner.is_empty:
        return []
    if inner.geom_type == "MultiPolygon":
        inner = max(inner.geoms, key=lambda p: p.area)

    height = building["height_m"]
    minx, miny, maxx, maxy = inner.bounds
    wanted = min(6, max(1, int(polygon.area / 320)))

    props = []
    attempts = 0
    while len(props) < wanted and attempts < wanted * 14:
        attempts += 1
        point = Point(rng.uniform(minx, maxx), rng.uniform(miny, maxy))
        if not inner.contains(point):
            continue
        roll = rng.random()
        if roll < 0.16:
            props.append(Prop("tank", point.x, point.y, height,
                              rng.uniform(0, math.pi),
                              rng.uniform(1.6, 2.4), rng.uniform(1.6, 2.4),
                              rng.uniform(1.8, 2.6)))
        elif roll < 0.30:
            props.append(Prop("aerial", point.x, point.y, height, 0.0,
                              0.06, 0.06, rng.uniform(1.8, 3.4)))
        else:
            props.append(Prop("plant", point.x, point.y, height,
                              rng.uniform(0, math.pi / 2),
                              rng.uniform(1.1, 2.6), rng.uniform(0.9, 1.9),
                              rng.uniform(0.7, 1.6)))
    return props


def rooftops(scene_data: dict) -> list[Prop]:
    """Chimneys, plant, tanks and aerials across every roof on site."""
    from shapely.strtree import STRtree

    buildings = scene_data["buildings"]
    polygons = [Polygon(b["footprint"]) for b in buildings]
    tree = STRtree(polygons)

    props: list[Prop] = []
    for index, building in enumerate(buildings):
        rng = _rng(building["osm_id"])
        polygon = polygons[index]

        if (building["height_m"] <= CHIMNEY_MAX_HEIGHT_M
                and building["kind"] in CHIMNEY_KINDS):
            edges = _hidden_edges(building["footprint"], polygons, tree, index)
            props.extend(_chimneys(building, building["footprint"], edges, rng))

        props.extend(_roof_plant(building, polygon, rng))
    return props


def street_furniture(scene_data: dict, surfaces: dict) -> list[Prop]:
    """Streetlights along the carriageway, bollards edging pedestrian streets."""
    carriageway = surfaces["carriageway"]
    pavement = surfaces["pavement"]
    props: list[Prop] = []

    for road in scene_data["roads"]:
        if len(road["centreline"]) < 2:
            continue
        line = LineString(road["centreline"])
        if line.length < 12:
            continue
        rng = _rng(road["osm_id"])
        pedestrian = road["highway"] in ("pedestrian", "footway", "living_street")

        spacing = BOLLARD_SPACING_M if pedestrian else STREETLIGHT_SPACING_M
        offset = road["width_m"] / 2 + STREETLIGHT_KERB_OFFSET_M

        steps = max(1, int(line.length / spacing))
        for step in range(steps + 1):
            distance = min(step * spacing + rng.uniform(-0.6, 0.6), line.length)
            point = line.interpolate(distance)
            ahead = line.interpolate(min(distance + 1.0, line.length))
            dx, dy = ahead.x - point.x, ahead.y - point.y
            norm = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / norm, dx / norm

            for side in (1, -1):
                x = point.x + nx * offset * side
                y = point.y + ny * offset * side
                here = Point(x, y)
                # Only place where there is actually pavement to stand on.
                if not pavement.intersects(here) or carriageway.intersects(here):
                    continue
                if pedestrian:
                    props.append(Prop("bollard", x, y, 0.135, 0.0,
                                      0.16, 0.16, 0.92))
                elif rng.random() < 0.55:
                    props.append(Prop("streetlight", x, y, 0.135,
                                      math.atan2(-ny * side, -nx * side),
                                      0.11, 0.11, rng.uniform(4.6, 5.4)))
    return props


def summarise(props: list[Prop]) -> str:
    counts: dict[str, int] = {}
    for prop in props:
        counts[prop.kind] = counts.get(prop.kind, 0) + 1
    return "  ".join(f"{k} {v}" for k, v in sorted(counts.items()))
