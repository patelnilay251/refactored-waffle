"""Stage 7 - road markings, facade fittings and surveyed street furniture.

Everything stage 6 had, plus:

* double yellows, lane dashes and zebra bars, derived from the surfaces
* street doors, downpipes, hanging signs and shop blinds on frontages
* trees, cycle stands, benches, bins and a pillar box at their surveyed
  OSM positions rather than scattered plausibly

    python3 -m pipeline.stage7_detail [scene.json] [--draft]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import bpy
from shapely.ops import unary_union

from . import clutter, facades, markings, post, solar, streets
from .blend import facade, grade, materials, mesh, props, shot, textures

ROOT = Path(__file__).resolve().parent.parent

from .stage5_dressing import (EXPOSURE, HERO_STREET, HERO_TIME,
                              HERO_UTC_OFFSET, SUN_STRENGTH)

CARRIAGEWAY_Z = 0.01
PAVEMENT_Z = CARRIAGEWAY_Z + 0.125
# Markings sit a few millimetres proud of the road. Enough to win the depth
# test outright, far too little to see edge-on.
MARKING_Z = CARRIAGEWAY_Z + 0.006
HAZE = 0.00026


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

    openings = 0
    for building in laid_out:
        shell = facade.build_shell(building, footprints[building.osm_id],
                                   f"bld_{building.osm_id}")
        if shell is None:
            continue
        shell.materials.append(materials.weathered_wall_material(
            building.material, building.osm_id, wall_cache))
        shell.materials.append(trim_material)
        obj = bpy.data.objects.new(f"bld_{building.osm_id}", shell)
        collection.objects.link(obj)
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

    lines = markings.build(scene_data, surfaces)
    paint = {
        "yellow": materials.road_paint("paint_yellow", (0.290, 0.196, 0.028)),
        "white": materials.road_paint("paint_white", (0.402, 0.398, 0.378)),
    }
    for name, geometry in lines.items():
        slab = mesh.polygon_slab(geometry, MARKING_Z, 0.0, f"marking_{name}")
        if slab:
            slab.data.materials.append(paint[name])
            collection.objects.link(slab)

    prop_list = (clutter.rooftops(scene_data)
                 + clutter.street_furniture(scene_data, surfaces)
                 + clutter.from_survey(scene_data, surfaces)
                 + clutter.facade_fittings(laid_out))
    prop_cache: dict = {}
    placed = props.place(prop_list, collection, prop_cache,
                         materials.prop_materials())

    latitude, longitude = scene_data["origin_wgs84"]
    sun = solar.sun_position(latitude, longitude, HERO_TIME, HERO_UTC_OFFSET)
    shot.sky(sun, dust=2.6)
    shot.atmosphere(density=HAZE, span=1800.0, height=550.0)
    bpy.context.scene.cycles.volume_bounces = 2
    warmth = max(0.0, min(1.0, (40.0 - sun.elevation) / 40.0))
    shot.sun(elevation_deg=sun.elevation, azimuth_deg=sun.azimuth,
             strength=SUN_STRENGTH,
             colour=(1.0, 1.0 - 0.42 * warmth, 1.0 - 0.82 * warmth))

    return {"laid_out": laid_out, "openings": openings, "props": prop_list,
            "placed": placed, "prop_meshes": len(prop_cache),
            "markings": lines, "sun": sun}


DETAIL_STREET = "Broadwick Street"


def _detail_camera(scene_data: dict):
    """A street-level view chosen to actually contain the new work.

    Aimed at the centroid of the surveyed trees nearest a carriageway, so the
    frame holds markings, trees and furniture together rather than whichever
    of them the hero camera happened to miss.
    """
    from shapely.geometry import LineString, Point

    trees = [item["position"] for item in scene_data.get("furniture", [])
             if item["kind"] == "natural=tree"]
    centreline = shot.find_street(scene_data, DETAIL_STREET)
    if not trees or not centreline:
        return None

    line = LineString(centreline)
    nearby = [t for t in trees if line.distance(Point(t)) < 25]
    if not nearby:
        nearby = trees
    target = (sum(t[0] for t in nearby) / len(nearby),
              sum(t[1] for t in nearby) / len(nearby))

    camera = shot.camera_towards(centreline, target, back=32.0, lens_mm=30.0,
                                 rise=6.0)
    shot.depth_of_field(camera, 30.0, 5.6)
    return camera


def main(argv: list[str]) -> int:
    draft = "--draft" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]
    scene_path = Path(args[0]) if args else ROOT / "data" / "soho" / "scene.json"
    scene_data = json.loads(scene_path.read_text())
    out_dir = ROOT / "out"

    samples = 48 if draft else 256
    resolution = (960, 540) if draft else (1920, 1080)

    print(f"site      : {scene_data['description']}")
    bpy.ops.wm.read_factory_settings(use_empty=True)

    started = time.time()
    built = build(scene_data)
    print(f"built     : in {time.time() - started:.1f}s")
    print(f"markings  : {markings.summarise(built['markings'])}")
    print(f"clutter   : {clutter.summarise(built['props'])}")
    print(f"            {built['placed']} objects from "
          f"{built['prop_meshes']} meshes "
          f"({built['placed'] / max(built['prop_meshes'], 1):.0f}:1)")
    print(f"unique faces {sum(len(m.polygons) for m in bpy.data.meshes):>9} "
          f" across {len(bpy.data.meshes)} meshes")
    print(f"objects      {len(bpy.data.objects):>9}")

    shot.configure_render(samples=samples, resolution=resolution,
                          exposure=EXPOSURE)
    grade.apply()

    centreline = shot.find_street(scene_data, HERO_STREET)
    cameras = []
    if centreline:
        hero = shot.street_camera(centreline, lens_mm=26.0, rise=16.0,
                                  along=0.16, look_ahead=0.58)
        shot.depth_of_field(hero, 34.0, 5.6)
        cameras.append(("hero", hero))
    # A third view on a vehicle street, because the hero runs down a
    # pedestrian one: no carriageway there means no markings, and the surveyed
    # trees happen to sit behind that camera.
    detail = _detail_camera(scene_data)
    if detail:
        cameras.append(("detail", detail))
    cameras.append(("overview", shot.overview_camera(scene_data)))

    for label, camera in cameras:
        raw = out_dir / "tmp" / f"stage7_{label}_raw.png"
        raw.parent.mkdir(parents=True, exist_ok=True)
        started = time.time()
        shot.render_to(raw, camera)
        elapsed = time.time() - started
        final = out_dir / f"stage7_{scene_data['name']}_{label}.png"
        post.process(raw, final,
                     vignette_strength=0.20 if label == "hero" else 0.12)
        print(f"rendered  : {final.name} in {elapsed / 60:.1f} min")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
