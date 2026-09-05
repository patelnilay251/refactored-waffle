"""Stage 5 - clutter, materials and atmosphere.

Adds the things that are not architecture (chimney stacks, roof plant, tanks,
aerials, bollards, streetlights), replaces the flat clay shaders with
procedural weathering, and lights the site from a real solar position with
haze for depth.

    python3 -m pipeline.stage5_dressing [data/soho/scene.json]
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import bpy
from shapely.ops import unary_union

from . import clutter, facades, solar, streets
from .blend import facade, materials, mesh, props, shot, textures

ROOT = Path(__file__).resolve().parent.parent

HERO_STREET = "Berwick Street"
CARRIAGEWAY_Z = 0.01
PAVEMENT_Z = CARRIAGEWAY_Z + 0.125

# Early September, late afternoon. Chosen against the street's own bearing:
# Berwick Street runs 149/329 degrees, so the camera looks SSE and the facade
# it sees faces WSW. At this moment the sun is 11 degrees off that facade's
# normal and low enough to be warm, lighting the top few metres while the
# canyon below stays in cool shade. A lower sun would be warmer still but
# cannot clear the opposite roofline; a higher one flattens the whole street.
HERO_TIME = datetime(2026, 9, 5, 17, 0)
HERO_UTC_OFFSET = 1.0  # BST

# Sun strength has to be read against the sky, not in isolation. Earlier stages
# lit the scene with a flat world at strength 1.0, which delivers only about
# 2 W/m2 of ambient, so a sun of 3-4 was a strong key. A physical sky texture
# is far brighter, and at that scale a sun of 4 is invisible: raising it 150x
# barely moved the image at all until the atmosphere was fixed. 150 puts the
# key roughly where a late-afternoon sun sits against this sky.
SUN_STRENGTH = 150.0

# One grade for the whole shoot, set so nothing clips.
EXPOSURE = -3.0


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
    opening_materials = [materials.window_frame(), textures.varied_glass()]
    footprints = {b["osm_id"]: b["footprint"] for b in scene_data["buildings"]}

    shell_faces = openings = 0
    for building in laid_out:
        shell = facade.build_shell(building, footprints[building.osm_id],
                                   f"bld_{building.osm_id}")
        if shell is None:
            continue
        shell.materials.append(materials.weathered_wall_material(
            building.material, building.osm_id, wall_cache))
        shell.materials.append(trim_material)

        obj = bpy.data.objects.new(f"bld_{building.osm_id}", shell)
        obj["osm_id"] = building.osm_id
        collection.objects.link(obj)
        shell_faces += len(shell.polygons)
        openings += facade.place_openings(building, collection,
                                          window_cache, opening_materials)

    ground = mesh.ground_plane(scene_data["extent_m"])
    ground.data.materials.append(materials.clay_ground())
    collection.objects.link(ground)

    road = mesh.polygon_slab(surfaces["carriageway"], CARRIAGEWAY_Z, 0.0,
                             "carriageway")
    if road:
        road.data.materials.append(
            textures.worn_ground("asphalt", (0.085, 0.085, 0.088), 0.85, 1.1))
        collection.objects.link(road)

    kerb = mesh.polygon_slab(surfaces["pavement"], PAVEMENT_Z, PAVEMENT_Z,
                             "pavement")
    if kerb:
        kerb.data.materials.append(
            textures.worn_ground("paving", (0.30, 0.288, 0.268), 0.80, 2.4))
        collection.objects.link(kerb)

    # Clutter.
    prop_list = (clutter.rooftops(scene_data)
                 + clutter.street_furniture(scene_data, surfaces))
    prop_cache: dict = {}
    placed = props.place(prop_list, collection, prop_cache,
                         materials.prop_materials())

    # Sun and sky from the site's own coordinates.
    latitude, longitude = scene_data["origin_wgs84"]
    sun = solar.sun_position(latitude, longitude, HERO_TIME, HERO_UTC_OFFSET)
    shot.sky(sun, dust=2.6)
    shot.atmosphere()
    # Warmth tracks elevation: the lower the sun, the more atmosphere it has
    # been through and the more of the blue end has been scattered out. At
    # around 24 degrees direct sunlight is near 4500K, which these
    # coefficients approximate against Blender's 6500K white.
    warmth = max(0.0, min(1.0, (40.0 - sun.elevation) / 40.0))
    shot.sun(elevation_deg=sun.elevation, azimuth_deg=sun.azimuth,
             strength=SUN_STRENGTH,
             colour=(1.0, 1.0 - 0.42 * warmth, 1.0 - 0.82 * warmth))

    return {"laid_out": laid_out, "shell_faces": shell_faces,
            "openings": openings, "props": prop_list, "placed": placed,
            "prop_meshes": len(prop_cache), "window_meshes": len(window_cache),
            "sun": sun}


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

    sun = built["sun"]
    print(f"sun       : {HERO_TIME:%d %b %Y %H:%M} "
          f"{'BST' if HERO_UTC_OFFSET else 'GMT'}  ->  {sun.describe()}")
    print(f"clutter   : {clutter.summarise(built['props'])}")
    print(f"            {built['placed']} objects from "
          f"{built['prop_meshes']} meshes "
          f"({built['placed'] / max(built['prop_meshes'], 1):.0f}:1)")

    unique = sum(len(m.polygons) for m in bpy.data.meshes)
    print(f"unique faces {unique:>9}  across {len(bpy.data.meshes)} meshes")
    print(f"objects      {len(bpy.data.objects):>9}")

    shot.configure_render(samples=128, resolution=(1600, 900),
                          exposure=EXPOSURE)

    cameras = [("overview", shot.overview_camera(scene_data))]
    centreline = shot.find_street(scene_data, HERO_STREET)
    if centreline:
        # Wide and tilted well up: at this sun elevation the canyon below
        # about 11 m never sees direct light, so the sunlit part of the
        # facade is the top few storeys and the frame has to reach them.
        cameras.append(("street", shot.street_camera(
            centreline, lens_mm=26.0, rise=16.0, along=0.16, look_ahead=0.58)))

    for label, camera in cameras:
        path = out_dir / f"stage5_{scene_data['name']}_{label}.png"
        started = time.time()
        shot.render_to(path, camera)
        print(f"rendered  : {path.name} in {time.time() - started:.1f}s")

    blend_path = ROOT / "out" / "tmp" / f"stage5_{scene_data['name']}.blend"
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"saved     : {blend_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
