"""Stage 3 - streets and ground.

Generates carriageway and pavement surfaces from the OSM centrelines and lays
them under the stage-2 massing. This is what turns the grey void between
buildings into a street.

    python3 -m pipeline.stage3_streets [data/soho/scene.json]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import bpy

from . import streets
from .blend import materials, mesh, shot

ROOT = Path(__file__).resolve().parent.parent

HERO_STREET = "Berwick Street"

# Sat just proud of the ground plane so it wins the depth test outright rather
# than z-fighting with it.
CARRIAGEWAY_Z = 0.01

# A UK kerb stands 125 mm above the carriageway. The skirt is dropped the full
# way to the ground datum so no gap opens under the kerb face.
KERB_HEIGHT = 0.125
PAVEMENT_Z = CARRIAGEWAY_Z + KERB_HEIGHT


def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def build(scene_data: dict) -> dict:
    collection = bpy.context.collection

    buildings = mesh.build_buildings(scene_data, collection,
                                     material=materials.clay())

    ground = mesh.ground_plane(scene_data["extent_m"])
    ground.data.materials.append(materials.clay_ground())
    collection.objects.link(ground)

    surfaces = streets.build_surfaces(scene_data)

    road = mesh.polygon_slab(surfaces["carriageway"], CARRIAGEWAY_Z, 0.0, "carriageway")
    if road:
        road.data.materials.append(materials.asphalt())
        collection.objects.link(road)

    kerb = mesh.polygon_slab(surfaces["pavement"], PAVEMENT_Z, PAVEMENT_Z, "pavement")
    if kerb:
        kerb.data.materials.append(materials.paving())
        collection.objects.link(kerb)

    shot.flat_world()
    shot.sun()

    return {"buildings": buildings, "road": road, "pavement": kerb,
            "surfaces": surfaces}


def main(argv: list[str]) -> int:
    scene_path = Path(argv[1]) if len(argv) > 1 else ROOT / "data" / "soho" / "scene.json"
    scene_data = json.loads(scene_path.read_text())
    out_dir = ROOT / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"site      : {scene_data['description']}")
    reset()
    built = build(scene_data)
    surfaces = built["surfaces"]

    print(f"ways      : {surfaces['vehicle_ways']} vehicle, "
          f"{surfaces['walked_ways']} pedestrian")
    print(streets.summarise(surfaces))
    for label in ("road", "pavement"):
        obj = built[label]
        if obj:
            print(f"{label:10}: {len(obj.data.polygons)} faces, "
                  f"{len(obj.data.vertices)} verts")

    shot.configure_render(samples=64, resolution=(1600, 900))

    cameras = [("overview", shot.overview_camera(scene_data))]
    centreline = shot.find_street(scene_data, HERO_STREET)
    if centreline:
        cameras.append(("street", shot.street_camera(centreline)))

    for label, camera in cameras:
        path = out_dir / f"stage3_{scene_data['name']}_{label}.png"
        started = time.time()
        shot.render_to(path, camera)
        print(f"rendered  : {path.name} in {time.time() - started:.1f}s")

    blend_path = ROOT / "out" / "tmp" / f"stage3_{scene_data['name']}.blend"
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"saved     : {blend_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
