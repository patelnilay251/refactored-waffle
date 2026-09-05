"""Facade layout - deciding where every opening goes.

Pure geometry, no Blender, so the layout can be inspected and counted before
anything is meshed.

Two ideas do most of the work here.

The first is that most walls are never seen. A terrace is a row of buildings
sharing party walls, and only the street frontage and the odd flank are
visible; generating windows on the rest would multiply the scene for nothing.
Walls are tested against their neighbours and only street-facing ones get
detail.

The second is that Georgian and Victorian terraces are strikingly regular.
Floor heights diminish going up, window proportions follow the floor, bays
repeat at roughly a constant pitch, and the ground floor is a shopfront rather
than a smaller version of the floors above. Encoding those rules gets far
closer to the real thing than scattering identical windows over a box.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree

# --- Wall selection -------------------------------------------------------

# How far out from a wall to test for a neighbour. Larger than the worst OSM
# tracing slop, smaller than the narrowest alley worth rendering.
VISIBILITY_PROBE_M = 1.2

# Below this a wall is a return or a chamfer, not a frontage worth glazing.
MIN_FRONTAGE_M = 2.5

# --- Vertical rhythm ------------------------------------------------------

GROUND_FLOOR_M = {"commercial": 4.2, "residential": 3.5, "civic": 5.0}
UPPER_FLOOR_M = {"commercial": 3.4, "residential": 3.0, "civic": 4.2}
PARAPET_M = {"commercial": 0.9, "residential": 0.6, "civic": 1.2}

# Storey heights fall as they rise: the first floor is the grand one and each
# floor above is shorter. Roughly 7% per floor matches London terraces.
DIMINUTION = 0.93

# --- Horizontal rhythm ----------------------------------------------------

# Target bay pitch. Actual pitch is the wall length divided by a whole number
# of bays, so frontages stay symmetrical.
BAY_PITCH_M = 3.4
MIN_BAY_M = 2.2

# --- Openings -------------------------------------------------------------

WINDOW_WIDTH_RATIO = 0.46        # of the bay
WINDOW_HEIGHT_RATIO = 0.60       # of the storey
WINDOW_SILL_RATIO = 0.26         # up from floor level
REVEAL_DEPTH_M = 0.18            # how far the glass sits back from the wall

SHOPFRONT_STALLRISER_M = 0.55    # solid panel below the glazing
SHOPFRONT_FASCIA_M = 0.65        # sign band above it
SHOPFRONT_PILASTER_M = 0.28      # solid pier between neighbouring shopfronts

CORNICE_PROJECTION_M = 0.32
CORNICE_DEPTH_M = 0.45

# Building kinds that get a shopfront rather than a domestic ground floor.
RETAIL_KINDS = {"commercial", "retail", "yes", "office", "hotel", "industrial"}


@dataclass
class Opening:
    """A rectangle on a wall, in wall-local coordinates.

    `u` runs along the wall from its start point, `v` runs up from the ground.
    """

    u0: float
    u1: float
    v0: float
    v1: float
    kind: str

    @property
    def width(self) -> float:
        return self.u1 - self.u0

    @property
    def height(self) -> float:
        return self.v1 - self.v0


@dataclass
class Wall:
    start: tuple[float, float]
    end: tuple[float, float]
    length: float
    height: float
    openings: list[Opening] = field(default_factory=list)
    cornice: bool = True
    # A wall giving onto a street gets the full treatment. One facing a yard or
    # a light well is a rear elevation: plainer windows, no shopfront, no
    # cornice - which is both how London is actually built and cheaper.
    frontage: bool = True

    @property
    def direction(self) -> tuple[float, float]:
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        return dx / self.length, dy / self.length

    @property
    def normal(self) -> tuple[float, float]:
        """Outward normal. Footprints are wound clockwise seen from above, so
        the outward side of an edge is to its left."""
        dx, dy = self.direction
        return -dy, dx


@dataclass
class FacadeBuilding:
    osm_id: int
    kind: str
    height: float
    storeys: int
    walls: list[Wall]
    material: str | None = None


def storey_heights(total: float, storeys: int, building_class: str) -> list[float]:
    """Floor-to-floor heights, ground first, summing to below the parapet."""
    parapet = PARAPET_M[building_class]
    usable = max(total - parapet, 2.5)

    if storeys <= 1:
        return [usable]

    ground = min(GROUND_FLOOR_M[building_class], usable * 0.55)
    remaining = usable - ground

    # Distribute what is left with each floor a little shorter than the last.
    weights = [DIMINUTION ** i for i in range(storeys - 1)]
    scale = remaining / sum(weights)
    return [ground] + [w * scale for w in weights]


def _bay_count(length: float) -> int:
    count = max(1, round(length / BAY_PITCH_M))
    while count > 1 and length / count < MIN_BAY_M:
        count -= 1
    return count


def _shopfront(u0: float, bay: float, storey: float) -> Opening:
    inset = min(SHOPFRONT_PILASTER_M, bay * 0.2)
    top = storey - SHOPFRONT_FASCIA_M
    return Opening(u0 + inset, u0 + bay - inset,
                   SHOPFRONT_STALLRISER_M, max(top, SHOPFRONT_STALLRISER_M + 0.8),
                   "shopfront")


def _window(u0: float, bay: float, base: float, storey: float,
            shrink: float) -> Opening:
    width = bay * WINDOW_WIDTH_RATIO
    height = storey * WINDOW_HEIGHT_RATIO * shrink
    sill = base + storey * WINDOW_SILL_RATIO
    centre = u0 + bay / 2
    return Opening(centre - width / 2, centre + width / 2,
                   sill, sill + height, "window")


def _door(u0: float, bay: float) -> Opening:
    """A street door beside the shopfronts.

    Terraces are not an unbroken run of glass: every few bays there is a door
    to the flats or offices above, and its narrower, taller proportion is a
    large part of what gives a London ground floor its rhythm.
    """
    width = min(1.05, bay * 0.42)
    centre = u0 + bay / 2
    return Opening(centre - width / 2, centre + width / 2, 0.02, 2.45, "door")


def lay_out_wall(wall: Wall, storeys: list[float], retail: bool,
                 rng=None) -> None:
    """Fill a wall with a bay grid of openings."""
    if wall.length < MIN_FRONTAGE_M:
        return

    bays = _bay_count(wall.length)
    bay = wall.length / bays
    wall.cornice = wall.frontage

    base = 0.0
    for floor, storey in enumerate(storeys):
        for b in range(bays):
            u0 = b * bay
            if floor == 0 and retail and wall.frontage:
                # Roughly one bay in four is a door rather than a shopfront.
                if rng is not None and rng.random() < 0.26:
                    wall.openings.append(_door(u0, bay))
                else:
                    wall.openings.append(_shopfront(u0, bay, storey))
                continue
            # Upper windows shrink with height, following the storey.
            shrink = DIMINUTION ** max(floor - 1, 0)
            opening = _window(u0, bay, base, storey, shrink)
            if not wall.frontage:
                # Rear elevations: fewer, meaner openings.
                if b % 2:
                    continue
                opening = _window(u0, bay, base, storey, shrink * 0.82)
            wall.openings.append(opening)
        base += storey


def visible_walls(footprint: list[tuple[float, float]], height: float,
                  neighbours: STRtree, polygons: list[Polygon],
                  own_index: int, street=None) -> list[Wall]:
    """Walls of a footprint that face open space rather than another building."""
    walls = []
    count = len(footprint)

    for i in range(count):
        start = footprint[i]
        end = footprint[(i + 1) % count]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 0.5:
            continue

        wall = Wall(start, end, length, height)
        nx, ny = wall.normal
        midpoint = Point(start[0] + dx / 2 + nx * VISIBILITY_PROBE_M,
                         start[1] + dy / 2 + ny * VISIBILITY_PROBE_M)

        blocked = any(index != own_index and polygons[index].contains(midpoint)
                      for index in neighbours.query(midpoint))
        if blocked:
            continue

        wall.frontage = street is None or street.intersects(midpoint)
        walls.append(wall)

    return walls


def lay_out(scene_data: dict, street=None) -> list[FacadeBuilding]:
    """Facade layout for every building in a stage-1 scene.

    Pass the stage-3 street surface to have walls giving onto a street treated
    as frontage and everything else as a rear elevation.
    """
    from .heights import BUILDING_CLASS, DEFAULT_CLASS

    buildings = scene_data["buildings"]
    polygons = [Polygon(b["footprint"]) for b in buildings]
    tree = STRtree(polygons)

    laid_out = []
    for index, building in enumerate(buildings):
        building_class, _ = BUILDING_CLASS.get(building["kind"], DEFAULT_CLASS)
        height = building["height_m"]

        storeys = building.get("levels")
        if not storeys:
            upper = UPPER_FLOOR_M[building_class]
            ground = GROUND_FLOOR_M[building_class]
            storeys = max(1, round((height - ground - PARAPET_M[building_class])
                                   / upper) + 1)
        storeys = max(1, min(int(storeys), 20))

        walls = visible_walls(building["footprint"], height, tree, polygons,
                              index, street)
        heights = storey_heights(height, storeys, building_class)
        retail = building["kind"] in RETAIL_KINDS

        rng = random.Random(building["osm_id"] & 0xFFFFFFFF)
        for wall in walls:
            lay_out_wall(wall, heights, retail, rng)

        laid_out.append(FacadeBuilding(
            osm_id=building["osm_id"],
            kind=building["kind"],
            height=height,
            storeys=storeys,
            walls=walls,
            material=building.get("material"),
        ))

    return laid_out


def summarise(laid_out: list[FacadeBuilding]) -> str:
    walls = [w for b in laid_out for w in b.walls]
    front = [w for w in walls if w.frontage]
    openings = [o for w in walls for o in w.openings]
    windows = sum(1 for o in openings if o.kind == "window")
    return (f"walls      {len(walls):5}  ({len(front)} frontage, "
            f"{len(walls) - len(front)} rear)\n"
            f"frontage   {sum(w.length for w in front):5.0f} m\n"
            f"windows    {windows:5}\n"
            f"shopfronts {len(openings) - windows:5}")
