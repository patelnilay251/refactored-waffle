"""Resolving a usable height for every building.

Only ~62% of Soho buildings carry `height` or `building:levels`. The rest have
to be inferred, and the inference is only defensible because of how London is
built: terraces share party walls and, crucially, share cornice lines. A gap
in a Georgian terrace is almost always the same height as the houses either
side of it. That is a far stronger prior than anything available in a city of
free-standing towers.

Every resolved height carries a `source` so the render can be audited later
and so we can visualise how much of the block is measured vs inferred.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from shapely.geometry import Polygon
from shapely.strtree import STRtree

# Metric floor models, by building class. Ground floors are taller than upper
# floors everywhere, and markedly so in commercial stock; the parapet term is
# the bit of wall that continues past the top floor's ceiling.
FLOOR_MODELS = {
    "commercial": (4.2, 3.4, 0.9),
    "residential": (3.4, 3.0, 0.6),
    "civic": (5.0, 4.2, 1.2),
}

# Which model each OSM `building=*` value uses, and the level count to assume
# when a building has no height data and no usable neighbours.
BUILDING_CLASS = {
    "commercial": ("commercial", 5),
    "retail": ("commercial", 4),
    "office": ("commercial", 6),
    "industrial": ("commercial", 3),
    "warehouse": ("commercial", 3),
    "hotel": ("commercial", 6),
    "residential": ("residential", 4),
    "apartments": ("residential", 5),
    "house": ("residential", 3),
    "terrace": ("residential", 4),
    "church": ("civic", 2),
    "cathedral": ("civic", 3),
    "civic": ("civic", 3),
    "public": ("civic", 3),
    "school": ("civic", 3),
    "university": ("civic", 4),
    "hospital": ("civic", 5),
}

# Soho is overwhelmingly mixed-use: shopfront below, flats or offices above.
# An untagged `building=yes` here is far more likely commercial than a house.
DEFAULT_CLASS = ("commercial", 4)

# Buildings whose footprints come within this distance share a party wall.
_TERRACE_TOLERANCE_M = 1.5

# How far to search for a height donor once the terrace itself yields nothing.
_NEIGHBOURHOOD_M = 30.0

_FEET = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:'|ft|feet)\s*$", re.I)
_METRES = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:m|metres|meters)?\s*$", re.I)


@dataclass
class Building:
    osm_id: int
    ring: list[tuple[float, float]]
    tags: dict[str, str]
    height: float = 0.0
    source: str = "unresolved"
    levels: int | None = None
    roof_shape: str | None = None
    roof_height: float = 0.0
    polygon: Polygon | None = field(default=None, repr=False)

    @property
    def kind(self) -> str:
        return self.tags.get("building", "yes")

    @property
    def name(self) -> str | None:
        return self.tags.get("name")

    @property
    def material(self) -> str | None:
        return self.tags.get("building:material")

    def classify(self) -> tuple[str, int]:
        return BUILDING_CLASS.get(self.kind, DEFAULT_CLASS)


def parse_length(raw: str | None) -> float | None:
    """OSM lengths are metres by default but feet notation turns up too."""
    if not raw:
        return None
    if match := _FEET.match(raw):
        return float(match.group(1)) * 0.3048
    if match := _METRES.match(raw):
        value = float(match.group(1))
        # Guard against levels accidentally entered in a height field.
        return value if 1.5 <= value <= 400 else None
    return None


def levels_to_height(levels: float, building_class: str) -> float:
    ground, upper, parapet = FLOOR_MODELS[building_class]
    return ground + max(levels - 1, 0) * upper + parapet


def _from_tags(building: Building) -> bool:
    """Resolve from explicit tags. Returns True if a height was found."""
    tags = building.tags
    building_class, _ = building.classify()

    building.roof_shape = tags.get("roof:shape")
    building.roof_height = parse_length(tags.get("roof:height")) or 0.0

    if (levels := parse_length(tags.get("building:levels"))) is not None:
        building.levels = int(levels)
    elif (raw := tags.get("building:levels")) and raw.replace(".", "").isdigit():
        building.levels = int(float(raw))

    if (height := parse_length(tags.get("height"))) is not None:
        building.height = height
        building.source = "tag:height"
        return True

    if building.levels:
        building.height = levels_to_height(building.levels, building_class)
        building.source = "tag:levels"
        return True

    return False


def _infer_from_neighbours(unknown: list[Building], known: list[Building]) -> None:
    """Borrow heights from adjoining and then nearby buildings."""
    if not known:
        return

    known_polygons = [b.polygon for b in known]
    tree = STRtree(known_polygons)

    def donors(building: Building, radius: float) -> list[float]:
        area = building.polygon.buffer(radius)
        return [known[i].height for i in tree.query(area)
                if known[i].polygon.intersects(area)]

    for building in unknown:
        # Party-wall neighbours first: same terrace, so same cornice line.
        if heights := donors(building, _TERRACE_TOLERANCE_M):
            building.height = statistics.median(heights)
            building.source = "inferred:terrace"
            continue
        # Otherwise fall back to the local streetscape.
        if heights := donors(building, _NEIGHBOURHOOD_M):
            building.height = statistics.median(heights)
            building.source = "inferred:nearby"


def _apply_defaults(buildings: list[Building]) -> None:
    for building in buildings:
        if building.source != "unresolved":
            continue
        building_class, default_levels = building.classify()
        building.height = levels_to_height(default_levels, building_class)
        building.source = "default:type"


def resolve(buildings: list[Building]) -> list[Building]:
    """Give every building a height, in place, recording provenance."""
    tagged = [b for b in buildings if _from_tags(b)]
    untagged = [b for b in buildings if b.source == "unresolved"]

    _infer_from_neighbours(untagged, tagged)
    _apply_defaults(buildings)
    return buildings


def summarise(buildings: list[Building]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for building in buildings:
        counts[building.source] = counts.get(building.source, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
