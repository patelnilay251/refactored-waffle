"""Stage 2 - massing.

Extrudes the stage-1 footprints into LOD1 volumes and renders them in clay.
The point is to confirm the geography survives the trip into 3D before any
effort goes into detail: right block shapes, right relative heights, streets
that read as streets.

    python3 -m pipeline.stage2_massing [data/soho/scene.json]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import bpy

from .blend import materials, mesh, shot

ROOT = Path(__file__).resolve().parent.parent

# The street the hero shot will eventually run down.
HERO_STREET = "Berwick Street"


def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def build(scene_data: dict) -> dict:
    collection = bpy.context.collection

    clay = materials.clay()
    buildings = mesh.build_buildings(scene_data, collection, material=clay)

    ground = mesh.ground_plane(scene_data["extent_m"])
    ground.data.materials.append(materials.clay_ground())
    collection.objects.link(ground)

    shot.flat_world()
    shot.sun()

    return {"buildings": buildings, "ground": ground}


def main(argv: list[str]) -> int:
    scene_path = Path(argv[1]) if len(argv) > 1 else ROOT / "data" / "soho" / "scene.json"
    scene_data = json.loads(scene_path.read_text())
    out_dir = ROOT / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"site      : {scene_data['description']}")
    reset()

    built = build(scene_data)
    total_verts = sum(len(o.data.vertices) for o in built["buildings"])
    print(f"buildings : {len(built['buildings'])} objects, {total_verts} verts")

    shot.configure_render(samples=64, resolution=(1600, 900))

    cameras = [("overview", shot.overview_camera(scene_data))]

    centreline = shot.find_street(scene_data, HERO_STREET)
    if centreline:
        cameras.append(("street", shot.street_camera(centreline)))
        print(f"street    : {HERO_STREET}, {len(centreline)} centreline points")
    else:
        print(f"street    : {HERO_STREET} not found - skipping street view")

    for label, camera in cameras:
        path = out_dir / f"stage2_{scene_data['name']}_{label}.png"
        started = time.time()
        shot.render_to(path, camera)
        print(f"rendered  : {path.name} in {time.time() - started:.1f}s")

    blend_path = ROOT / "out" / "tmp" / f"stage2_{scene_data['name']}.blend"
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"saved     : {blend_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
