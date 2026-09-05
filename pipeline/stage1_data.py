"""Stage 1 - build the data layer.

Fetches the block from OSM, reprojects it into local metres, resolves a height
for every building, and writes both a machine-readable scene file and a preview
image. Nothing here touches Blender: the point of this stage is to confirm the
geography is right before any of it gets extruded.

    python3 -m pipeline.stage1_data [config/soho.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from shapely.geometry import Polygon
from shapely.validation import make_valid

from . import osm
from .geo import BBox, Projection
from .heights import Building, resolve, summarise

ROOT = Path(__file__).resolve().parent.parent

# Carriageway width by road class, used where OSM has no lane or width tag.
# Soho's streets are narrow; these are deliberately tighter than UK defaults.
ROAD_WIDTHS = {
    "primary": 12.0,
    "secondary": 10.0,
    "tertiary": 8.5,
    "residential": 7.0,
    "unclassified": 7.0,
    "service": 4.5,
    "living_street": 6.0,
    "pedestrian": 8.0,
    "footway": 2.5,
    "path": 2.0,
    "steps": 2.0,
    "cycleway": 2.0,
}
DEFAULT_ROAD_WIDTH = 6.0
LANE_WIDTH_M = 3.1


def load_config(path: Path) -> tuple[str, BBox, dict]:
    config = json.loads(path.read_text())
    lat, lon = config["centre"]
    return config["name"], BBox.centred_on(lat, lon, config["size_m"]), config


def build_footprints(elements: list[dict], projection: Projection) -> list[Building]:
    """Turn Overpass ways into buildings with valid, metric, CCW footprints."""
    buildings = []
    for element in elements:
        geometry = element.get("geometry")
        if not geometry or len(geometry) < 4:
            continue

        ring = projection.ring_to_local(geometry)
        # Overpass repeats the first node to close the way; shapely adds its own.
        if ring[0] == ring[-1]:
            ring = ring[:-1]
        if len(ring) < 3:
            continue

        polygon = Polygon(ring)
        if not polygon.is_valid:
            polygon = make_valid(polygon)
            if polygon.geom_type == "MultiPolygon":
                polygon = max(polygon.geoms, key=lambda p: p.area)
            if polygon.geom_type != "Polygon" or polygon.is_empty:
                continue
            ring = list(polygon.exterior.coords)[:-1]

        # Sub-4m^2 slivers are mapping noise, not buildings.
        if polygon.area < 4.0:
            continue

        # Normalise winding so extrusion normals point outward later.
        if polygon.exterior.is_ccw:
            polygon = Polygon(list(polygon.exterior.coords)[::-1])
        ring = list(polygon.exterior.coords)[:-1]

        buildings.append(
            Building(
                osm_id=element["id"],
                ring=[(round(x, 3), round(y, 3)) for x, y in ring],
                tags=element.get("tags", {}),
                polygon=polygon,
            )
        )
    return buildings


def road_width(tags: dict[str, str]) -> float:
    """Best available carriageway width, in metres."""
    from .heights import parse_length

    if (width := parse_length(tags.get("width"))) is not None:
        return width
    if (lanes := tags.get("lanes", "")).isdigit():
        return max(int(lanes), 1) * LANE_WIDTH_M
    return ROAD_WIDTHS.get(tags.get("highway", ""), DEFAULT_ROAD_WIDTH)


def build_roads(elements: list[dict], projection: Projection) -> list[dict]:
    roads = []
    for element in elements:
        geometry = element.get("geometry")
        if not geometry or len(geometry) < 2:
            continue
        tags = element.get("tags", {})
        centreline = projection.ring_to_local(geometry)
        roads.append(
            {
                "osm_id": element["id"],
                "highway": tags.get("highway"),
                "name": tags.get("name"),
                "surface": tags.get("surface"),
                "oneway": tags.get("oneway") == "yes",
                "width_m": round(road_width(tags), 2),
                "is_footway": tags.get("highway") in ("footway", "path", "steps"),
                "centreline": [(round(x, 3), round(y, 3)) for x, y in centreline],
            }
        )
    return roads


def to_scene(name: str, bbox: BBox, config: dict,
             buildings: list[Building], roads: list[dict]) -> dict:
    width, height = bbox.size_m()
    return {
        "name": name,
        "description": config.get("description", ""),
        "crs": "local tangent plane, metres, +X east +Y north",
        "origin_wgs84": list(bbox.centre),
        "bbox_wgs84": [bbox.south, bbox.west, bbox.north, bbox.east],
        "extent_m": [round(width, 1), round(height, 1)],
        "buildings": [
            {
                "osm_id": b.osm_id,
                "kind": b.kind,
                "name": b.name,
                "material": b.material,
                "height_m": round(b.height, 2),
                "height_source": b.source,
                "levels": b.levels,
                "roof_shape": b.roof_shape,
                "roof_height_m": round(b.roof_height, 2),
                "start_date": b.tags.get("start_date"),
                "footprint": b.ring,
            }
            for b in buildings
        ],
        "roads": roads,
    }


def main(argv: list[str]) -> int:
    config_path = Path(argv[1]) if len(argv) > 1 else ROOT / "config" / "soho.json"
    name, bbox, config = load_config(config_path)

    width, height = bbox.size_m()
    print(f"site      : {config.get('description', name)}")
    print(f"bbox      : {bbox.overpass()}")
    print(f"extent    : {width:.0f} x {height:.0f} m")

    print("fetching  : buildings ...", flush=True)
    buildings = build_footprints(osm.buildings(bbox), Projection.for_bbox(bbox))
    print("fetching  : roads ...", flush=True)
    roads = build_roads(osm.roads(bbox), Projection.for_bbox(bbox))

    resolve(buildings)

    print(f"\nbuildings : {len(buildings)}")
    print(f"roads     : {len(roads)} ways "
          f"({sum(1 for r in roads if r['is_footway'])} footway)")
    print("\nheight provenance:")
    total = max(len(buildings), 1)
    for source, count in summarise(buildings).items():
        print(f"  {source:<20} {count:>4}  {100 * count // total:>3}%")

    measured = sum(1 for b in buildings if b.source.startswith("tag"))
    print(f"\n  measured from OSM tags : {100 * measured // total}%")
    print(f"  inferred or defaulted  : {100 * (total - measured) // total}%")

    tall = sorted(buildings, key=lambda b: -b.height)[:5]
    print("\ntallest:")
    for b in tall:
        label = b.name or f"{b.kind} #{b.osm_id}"
        print(f"  {b.height:>6.1f} m  {label[:44]:<44} [{b.source}]")

    out_dir = ROOT / "data" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    scene_path = out_dir / "scene.json"
    scene_path.write_text(json.dumps(to_scene(name, bbox, config, buildings, roads), indent=1))
    print(f"\nwrote     : {scene_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
