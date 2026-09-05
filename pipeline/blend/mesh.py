"""Turning stage-1 footprints into geometry.

Footprints arrive as closed rings in local metres, wound clockwise when viewed
from above (stage 1 normalises this). Extrusion builds the walls and caps
directly rather than going through `bmesh.ops.extrude`, which is markedly
faster across a few hundred buildings, then recalculates normals once per mesh
so a malformed ring can't leave the walls inside out.
"""

from __future__ import annotations

import bmesh
import bpy

# Soho's ground varies by roughly 3 m across the whole site, which is below
# what reads at street level, so everything sits on a flat datum for now.
GROUND_Z = 0.0


def extrude_footprint(ring: list[tuple[float, float]], height: float,
                      name: str) -> bpy.types.Object:
    """Build a closed prism from a footprint ring and a height."""
    count = len(ring)
    verts = [(x, y, GROUND_Z) for x, y in ring]
    verts += [(x, y, GROUND_Z + height) for x, y in ring]

    faces = []
    for i in range(count):
        j = (i + 1) % count
        # Wound so the wall normal faces out of a clockwise ring.
        faces.append((i, i + count, j + count, j))
    faces.append(tuple(range(count - 1, -1, -1)))          # base, facing down
    faces.append(tuple(range(count, 2 * count)))           # roof, facing up

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate(verbose=False)

    # One authoritative pass on normals, so winding bugs upstream stay harmless.
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()

    mesh.shade_flat()
    return bpy.data.objects.new(name, mesh)


def ground_plane(extent: tuple[float, float], margin: float = 40.0,
                 name: str = "ground") -> bpy.types.Object:
    """A plane comfortably larger than the site, so its edge never shows.

    Generous by default: four vertices cost nothing, and a visible ground edge
    on the horizon instantly reads as a model on a table rather than a city.
    """
    half_x = extent[0] * margin / 2
    half_y = extent[1] * margin / 2
    verts = [(-half_x, -half_y, GROUND_Z), (half_x, -half_y, GROUND_Z),
             (half_x, half_y, GROUND_Z), (-half_x, half_y, GROUND_Z)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh.validate(verbose=False)
    return bpy.data.objects.new(name, mesh)


def build_buildings(scene_data: dict, collection: bpy.types.Collection,
                    material: bpy.types.Material | None = None) -> list[bpy.types.Object]:
    """Extrude every building in a stage-1 scene file."""
    objects = []
    for building in scene_data["buildings"]:
        label = building["name"] or building["kind"]
        obj = extrude_footprint(
            building["footprint"],
            building["height_m"],
            f"bld_{building['osm_id']}_{label}"[:60],
        )
        # Carry the provenance onto the object so it survives into the .blend
        # and can be inspected or filtered in later stages.
        obj["osm_id"] = building["osm_id"]
        obj["height_source"] = building["height_source"]
        obj["kind"] = building["kind"]
        if building.get("material"):
            obj["osm_material"] = building["material"]
        if material:
            obj.data.materials.append(material)
        collection.objects.link(obj)
        objects.append(obj)
    return objects
