"""Meshing the clutter.

Same instancing discipline as the facades: sizes are quantised, one mesh is
built per size class and shared by linked duplicates, so a few thousand props
cost a few dozen meshes.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Vector

SIZE_QUANTUM_M = 0.25
POT_SIDES = 8
BOLLARD_SIDES = 8


def _box_mesh(name: str, width: float, depth: float, height: float,
              taper: float = 1.0) -> bpy.types.Mesh:
    """A box, optionally tapering toward the top."""
    hw, hd = width / 2, depth / 2
    tw, td = hw * taper, hd * taper
    verts = [(-hw, -hd, 0), (hw, -hd, 0), (hw, hd, 0), (-hw, hd, 0),
             (-tw, -td, height), (tw, -td, height),
             (tw, td, height), (-tw, td, height)]
    faces = [(3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate(verbose=False)
    mesh.shade_flat()
    return mesh


def _cylinder_mesh(name: str, radius: float, height: float,
                   sides: int = 8, top_scale: float = 1.0) -> bpy.types.Mesh:
    verts, faces = [], []
    for i in range(sides):
        angle = 2 * math.pi * i / sides
        verts.append((math.cos(angle) * radius, math.sin(angle) * radius, 0.0))
    for i in range(sides):
        angle = 2 * math.pi * i / sides
        verts.append((math.cos(angle) * radius * top_scale,
                      math.sin(angle) * radius * top_scale, height))
    for i in range(sides):
        j = (i + 1) % sides
        faces.append((i, j, j + sides, i + sides))
    faces.append(tuple(range(sides - 1, -1, -1)))
    faces.append(tuple(range(sides, 2 * sides)))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate(verbose=False)
    mesh.shade_flat()
    return mesh


def _streetlight_mesh(name: str, height: float) -> bpy.types.Mesh:
    """Column with a short outreach arm and a lantern — the shape reads even
    when the whole thing is thirty pixels tall."""
    verts, faces = [], []

    def prism(x0, x1, y0, y1, z0, z1):
        base = len(verts)
        verts.extend([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                      (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)])
        faces.extend([
            (base + 3, base + 2, base + 1, base + 0),
            (base + 4, base + 5, base + 6, base + 7),
            (base + 0, base + 1, base + 5, base + 4),
            (base + 1, base + 2, base + 6, base + 5),
            (base + 2, base + 3, base + 7, base + 6),
            (base + 3, base + 0, base + 4, base + 7),
        ])

    r = 0.055
    prism(-r, r, -r, r, 0.0, height)                       # column
    prism(-r, 0.95, -r * 0.8, r * 0.8, height - 0.14, height)  # outreach arm
    prism(0.62, 1.12, -0.16, 0.16, height - 0.30, height - 0.12)  # lantern

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate(verbose=False)
    mesh.shade_flat()
    return mesh


def _slanted_awning(name: str, width: float) -> bpy.types.Mesh:
    """A shop blind, dropping away from the wall.

    Wall-mounted props are built with local +X along the wall and local +Y
    pointing out of it, which is what a Z rotation of `atan2(u.y, u.x)` maps
    the wall's own basis onto.
    """
    hw = width / 2
    reach, fall = 1.15, 0.42
    verts = [(-hw, 0.02, 0.0), (hw, 0.02, 0.0),
             (hw, reach, -fall), (-hw, reach, -fall),
             (-hw, 0.02, -0.07), (hw, 0.02, -0.07),
             (hw, reach, -fall - 0.07), (-hw, reach, -fall - 0.07),
             (-hw, reach, -fall - 0.30), (hw, reach, -fall - 0.30)]
    faces = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 3, 7, 4), (1, 5, 6, 2),
             (3, 2, 6, 7), (0, 4, 5, 1), (7, 6, 9, 8)]
    return _mesh_from(name, verts, faces)


def _hanging_sign(name: str) -> bpy.types.Mesh:
    """Bracket and board projecting over the pavement."""
    verts: list = []
    faces: list = []

    def slab(x0, x1, y0, y1, z0, z1):
        base = len(verts)
        verts.extend([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                      (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)])
        faces.extend([(base + 3, base + 2, base + 1, base),
                      (base + 4, base + 5, base + 6, base + 7),
                      (base, base + 1, base + 5, base + 4),
                      (base + 1, base + 2, base + 6, base + 5),
                      (base + 2, base + 3, base + 7, base + 6),
                      (base + 3, base, base + 4, base + 7)])

    slab(-0.02, 0.02, 0.0, 0.62, 0.30, 0.34)      # bracket arm
    slab(-0.02, 0.02, 0.58, 0.62, -0.02, 0.34)    # drop
    slab(-0.03, 0.03, 0.30, 0.66, -0.44, 0.02)    # board
    return _mesh_from(name, verts, faces)


def _mesh_from(name: str, verts, faces) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate(verbose=False)
    mesh.shade_flat()
    return mesh


def _quantise(value: float) -> float:
    return max(round(value / SIZE_QUANTUM_M), 1) * SIZE_QUANTUM_M


def _mesh_for(prop, cache: dict) -> bpy.types.Mesh:
    """One mesh per (kind, quantised size)."""
    from . import streetprops

    # Surveyed furniture: one mesh per kind, or per size band where it varies.
    if prop.kind in ("bike_stand", "bench", "bin", "post_box", "sign", "awning"):
        key = (prop.kind, _quantise(prop.width))
        if key not in cache:
            name = f"prop_{prop.kind}"
            if prop.kind == "bike_stand":
                cache[key] = streetprops.sheffield_stand(name)
            elif prop.kind == "bench":
                cache[key] = streetprops.bench_mesh(name)
            elif prop.kind == "bin":
                cache[key] = streetprops.bin_mesh(name, prop.height)
            elif prop.kind == "post_box":
                cache[key] = streetprops.post_box(name)
            elif prop.kind == "sign":
                cache[key] = _hanging_sign(name)
            else:
                cache[key] = _slanted_awning(name, key[1])
        return cache[key]

    if prop.kind == "tree":
        # Trees vary individually; a handful of distinct crowns is enough for
        # nine of them, and identical trees in a row read badly.
        key = ("tree", round(prop.height * 2), int(prop.yaw * 100) % 5)
        if key not in cache:
            cache[key] = streetprops.tree_mesh(f"prop_tree_{key[1]}_{key[2]}",
                                               prop.height, seed=key[1] * 7 + key[2])
        return cache[key]

    if prop.kind == "downpipe":
        key = ("downpipe", _quantise(prop.height))
        if key not in cache:
            verts: list = []
            faces: list = []
            streetprops._tube(verts, faces, (0, 0, 0), (0, 0, key[1]), 0.055,
                              sides=6)
            cache[key] = _mesh_from(f"prop_downpipe_{key[1]}", verts, faces)
        return cache[key]

    if prop.kind in ("pot", "aerial", "bollard"):
        key = (prop.kind, round(prop.height * 4))
    else:
        key = (prop.kind, _quantise(prop.width), _quantise(prop.depth),
               _quantise(prop.height))
    if key in cache:
        return cache[key]

    name = "_".join(str(k) for k in key)
    if prop.kind == "chimney":
        mesh = _box_mesh(f"prop_{name}", key[1], key[2], key[3], taper=0.94)
    elif prop.kind == "pot":
        mesh = _cylinder_mesh(f"prop_{name}", 0.115, prop.height,
                              POT_SIDES, top_scale=0.88)
    elif prop.kind == "aerial":
        mesh = _cylinder_mesh(f"prop_{name}", 0.03, prop.height, 4)
    elif prop.kind == "bollard":
        mesh = _cylinder_mesh(f"prop_{name}", 0.08, prop.height,
                              BOLLARD_SIDES, top_scale=0.82)
    elif prop.kind == "tank":
        mesh = _box_mesh(f"prop_{name}", key[1], key[2], key[3])
    elif prop.kind == "streetlight":
        mesh = _streetlight_mesh(f"prop_{name}", prop.height)
    else:
        mesh = _box_mesh(f"prop_{name}", key[1], key[2], key[3])

    cache[key] = mesh
    return mesh


def place(props, collection: bpy.types.Collection, cache: dict,
          materials: dict) -> int:
    """Instance every prop. Returns how many objects were created."""
    slot_for = {
        "chimney": "brick", "pot": "terracotta", "aerial": "metal",
        "bollard": "metal", "tank": "metal", "plant": "metal",
        "streetlight": "metal", "downpipe": "metal", "sign": "metal",
        "bike_stand": "metal", "bench": "timber", "bin": "metal",
        "post_box": "postbox_red", "awning": "canvas",
        # A tree carries two slots: woody faces first, then foliage.
        "tree": ["bark", "foliage"],
    }

    placed = 0
    for prop in props:
        mesh = _mesh_for(prop, cache)
        if mesh is None:
            continue
        if not mesh.materials:
            wanted = slot_for.get(prop.kind, "metal")
            for key in (wanted if isinstance(wanted, list) else [wanted]):
                mesh.materials.append(materials[key])

        obj = bpy.data.objects.new(f"{prop.kind}_{placed}", mesh)
        rotation = Matrix.Rotation(prop.yaw, 4, "Z")
        obj.matrix_world = (Matrix.Translation(Vector((prop.x, prop.y, prop.z)))
                            @ rotation)
        collection.objects.link(obj)
        placed += 1
    return placed
