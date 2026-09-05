"""Stage 4 - facades.

Replaces the LOD1 boxes with walls that have bays, recessed windows, sills,
shopfronts and cornices. This is the jump from massing to something that reads
as buildings.

    python3 -m pipeline.stage4_facades [data/soho/scene.json]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import bpy
from shapely.ops import unary_union

from . import facades, streets
from .blend import facade, materials, mesh, shot

ROOT = Path(__file__).resolve().parent.parent

HERO_STREET = "Berwick Street"
CARRIAGEWAY_Z = 0.01
KERB_HEIGHT = 0.125
PAVEMENT_Z = CARRIAGEWAY_Z + KERB_HEIGHT


def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def build(scene_data: dict) -> dict:
    collection = bpy.context.collection

    surfaces = streets.build_surfaces(scene_data)
    street = unary_union([surfaces["carriageway"], surfaces["pavement"]])
    laid_out = facades.lay_out(scene_data, street)

    wall_cache: dict = {}
    window_cache: dict = {}
    trim_material = materials.trim()
    opening_materials = [materials.window_frame(), materials.glass()]

    footprints = {b["osm_id"]: b["footprint"] for b in scene_data["buildings"]}

    shell_faces = openings = 0
    for building in laid_out:
        footprint = footprints[building.osm_id]
        shell = facade.build_shell(building, footprint, f"bld_{building.osm_id}")
        if shell is None:
            continue
        shell.materials.append(materials.wall_material(
            building.material, building.osm_id, wall_cache))
        shell.materials.append(trim_material)

        obj = bpy.data.objects.new(f"bld_{building.osm_id}", shell)
        obj["osm_id"] = building.osm_id
        obj["kind"] = building.kind
        collection.objects.link(obj)
        shell_faces += len(shell.polygons)

        openings += facade.place_openings(building, collection,
                                          window_cache, opening_materials)

    ground = mesh.ground_plane(scene_data["extent_m"])
    ground.data.materials.append(materials.clay_ground())
    collection.objects.link(ground)

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

    return {"laid_out": laid_out, "shell_faces": shell_faces,
            "openings": openings, "window_meshes": len(window_cache),
            "wall_materials": len(wall_cache)}


def main(argv: list[str]) -> int:
    scene_path = Path(argv[1]) if len(argv) > 1 else ROOT / "data" / "soho" / "scene.json"
    scene_data = json.loads(scene_path.read_text())
    out_dir = ROOT / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"site      : {scene_data['description']}")
    reset()

    started = time.time()
    built = build(scene_data)
    print(f"built     : in {time.time() - started:.1f}s")
    print(facades.summarise(built["laid_out"]))

    unique = sum(len(m.polygons) for m in bpy.data.meshes)
    print(f"\nshell faces    {built['shell_faces']:>8}")
    print(f"opening instances {built['openings']:>5}")
    print(f"window meshes  {built['window_meshes']:>8}  "
          f"(instancing ratio {built['openings'] / max(built['window_meshes'], 1):.0f}:1)")
    print(f"wall materials {built['wall_materials']:>8}")
    print(f"unique faces   {unique:>8}  across {len(bpy.data.meshes)} meshes")
    print(f"objects        {len(bpy.data.objects):>8}")

    shot.configure_render(samples=96, resolution=(1600, 900))

    cameras = [("overview", shot.overview_camera(scene_data))]
    centreline = shot.find_street(scene_data, HERO_STREET)
    if centreline:
        cameras.append(("street", shot.street_camera(centreline)))

    for label, camera in cameras:
        path = out_dir / f"stage4_{scene_data['name']}_{label}.png"
        started = time.time()
        shot.render_to(path, camera)
        print(f"rendered  : {path.name} in {time.time() - started:.1f}s")

    blend_path = ROOT / "out" / "tmp" / f"stage4_{scene_data['name']}.blend"
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"saved     : {blend_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
