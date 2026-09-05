"""Meshes for surveyed street furniture.

These stand at OSM-surveyed positions rather than scattered plausibly, so the
shapes have to be recognisable at street distance without being expensive. A
Sheffield stand is two bends of tube; a London plane is a trunk, a few limbs
and some overlapping crowns. Neither needs to survive close inspection, but
both need to read instantly from twenty metres.
"""

from __future__ import annotations

import math
import random

import bpy


def _mesh(name: str, verts, faces) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate(verbose=False)
    mesh.shade_flat()
    return mesh


def _tube(verts, faces, start, end, radius, sides=6, taper=1.0):
    """Append a capped tube between two points."""
    sx, sy, sz = start
    ex, ey, ez = end
    axis = (ex - sx, ey - sy, ez - sz)
    length = math.sqrt(sum(c * c for c in axis)) or 1.0
    axis = tuple(c / length for c in axis)

    # Any vector not parallel to the axis will do to build a frame.
    helper = (0.0, 0.0, 1.0) if abs(axis[2]) < 0.9 else (1.0, 0.0, 0.0)
    u = (axis[1] * helper[2] - axis[2] * helper[1],
         axis[2] * helper[0] - axis[0] * helper[2],
         axis[0] * helper[1] - axis[1] * helper[0])
    un = math.sqrt(sum(c * c for c in u)) or 1.0
    u = tuple(c / un for c in u)
    v = (axis[1] * u[2] - axis[2] * u[1],
         axis[2] * u[0] - axis[0] * u[2],
         axis[0] * u[1] - axis[1] * u[0])

    base = len(verts)
    for ring, (origin, scale) in enumerate(((start, 1.0), (end, taper))):
        for i in range(sides):
            angle = 2 * math.pi * i / sides
            offset = [radius * scale * (math.cos(angle) * u[k]
                                        + math.sin(angle) * v[k]) for k in range(3)]
            verts.append((origin[0] + offset[0], origin[1] + offset[1],
                          origin[2] + offset[2]))
    for i in range(sides):
        j = (i + 1) % sides
        faces.append((base + i, base + j, base + sides + j, base + sides + i))
    faces.append(tuple(range(base + sides - 1, base - 1, -1)))
    faces.append(tuple(range(base + sides, base + 2 * sides)))


def _blob(verts, faces, centre, radius, rings=4, segments=7, rng=None):
    """A coarse, slightly irregular sphere — one clump of foliage."""
    cx, cy, cz = centre
    base = len(verts)
    for r in range(1, rings):
        phi = math.pi * r / rings
        for s in range(segments):
            theta = 2 * math.pi * s / segments
            jitter = 1.0 if rng is None else rng.uniform(0.82, 1.18)
            verts.append((
                cx + radius * jitter * math.sin(phi) * math.cos(theta),
                cy + radius * jitter * math.sin(phi) * math.sin(theta),
                cz + radius * jitter * math.cos(phi) * 0.86,
            ))
    top = len(verts)
    verts.append((cx, cy, cz + radius * 0.92))
    bottom = len(verts)
    verts.append((cx, cy, cz - radius * 0.92))

    for r in range(rings - 2):
        for s in range(segments):
            a = base + r * segments + s
            b = base + r * segments + (s + 1) % segments
            faces.append((a, b, b + segments, a + segments))
    for s in range(segments):
        faces.append((top, base + (s + 1) % segments, base + s))
        last = base + (rings - 2) * segments
        faces.append((bottom, last + s, last + (s + 1) % segments))


def tree_mesh(name: str, height: float, seed: int) -> bpy.types.Mesh:
    """A London plane: straight bole, a few limbs, overlapping crowns."""
    rng = random.Random(seed)
    verts: list = []
    faces: list = []

    bole = height * rng.uniform(0.36, 0.46)
    radius = height * 0.028
    _tube(verts, faces, (0, 0, 0), (0, 0, bole), radius, sides=8, taper=0.7)

    limbs = rng.randint(3, 5)
    crown_z = bole + height * 0.16
    for i in range(limbs):
        angle = 2 * math.pi * i / limbs + rng.uniform(-0.4, 0.4)
        reach = height * rng.uniform(0.14, 0.22)
        tip = (math.cos(angle) * reach, math.sin(angle) * reach,
               crown_z + height * rng.uniform(0.02, 0.10))
        _tube(verts, faces, (0, 0, bole * 0.92), tip, radius * 0.45,
              sides=5, taper=0.5)

    # Everything past here is foliage — the split point between material slots.
    woody_faces = len(faces)

    # A canopy built from many small clumps rather than a few large spheres.
    # Half a dozen big blobs render as exactly what they are: faceted
    # polyhedra floating over a stick. Thirty small ones at varied radii give
    # a broken silhouette and self-shadowing, which is what actually reads as
    # foliage from across a street.
    centre_z = crown_z + height * 0.20
    spread_xy = height * 0.30
    spread_z = height * 0.20
    for _ in range(rng.randint(95, 135)):
        # Bias toward the outside of the crown; the middle is branches.
        radial = rng.uniform(0.30, 1.0) ** 0.55
        theta = rng.uniform(0, math.tau)
        phi = math.acos(rng.uniform(-0.85, 1.0))
        cx = spread_xy * radial * math.sin(phi) * math.cos(theta)
        cy = spread_xy * radial * math.sin(phi) * math.sin(theta)
        cz = centre_z + spread_z * radial * math.cos(phi)
        # Small enough to overlap heavily. Clumps that do not overlap read as
        # a bunch of grapes; the mass has to close up into one canopy.
        _blob(verts, faces, (cx, cy, cz),
              height * rng.uniform(0.030, 0.058),
              rings=3, segments=5, rng=rng)

    mesh = _mesh(name, verts, faces)
    if len(mesh.polygons) == len(faces):
        for index in range(woody_faces, len(faces)):
            mesh.polygons[index].material_index = 1
            # Smooth shading hides the facets on clumps this coarse; the trunk
            # and limbs stay flat, where the facets are correct.
            mesh.polygons[index].use_smooth = True
    return mesh


def sheffield_stand(name: str = "bike_stand") -> bpy.types.Mesh:
    """The inverted-U cycle stand, ~750 mm tall and 700 mm wide."""
    verts: list = []
    faces: list = []
    radius, half, height = 0.026, 0.35, 0.75
    _tube(verts, faces, (-half, 0, 0), (-half, 0, height - 0.09), radius)
    _tube(verts, faces, (half, 0, 0), (half, 0, height - 0.09), radius)
    steps = 5
    for i in range(steps):
        a0 = math.pi * i / steps
        a1 = math.pi * (i + 1) / steps
        _tube(verts, faces,
              (-half * math.cos(a0), 0, height - 0.09 + 0.09 * math.sin(a0)),
              (-half * math.cos(a1), 0, height - 0.09 + 0.09 * math.sin(a1)),
              radius)
    return _mesh(name, verts, faces)


def bench_mesh(name: str = "bench") -> bpy.types.Mesh:
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

    for i in range(3):                                   # seat slats
        y = -0.22 + i * 0.17
        slab(-0.85, 0.85, y, y + 0.12, 0.40, 0.45)
    for i in range(2):                                   # back slats
        z = 0.62 + i * 0.16
        slab(-0.85, 0.85, 0.22, 0.28, z, z + 0.12)
    for x in (-0.72, 0.72):                              # legs
        slab(x - 0.04, x + 0.04, -0.24, 0.30, 0.0, 0.42)
        slab(x - 0.04, x + 0.04, 0.22, 0.30, 0.42, 0.80)
    return _mesh(name, verts, faces)


def bin_mesh(name: str = "bin", height: float = 0.95) -> bpy.types.Mesh:
    verts: list = []
    faces: list = []
    _tube(verts, faces, (0, 0, 0.06), (0, 0, height), 0.22, sides=10, taper=1.08)
    _tube(verts, faces, (0, 0, 0), (0, 0, 0.06), 0.06, sides=6)
    return _mesh(name, verts, faces)


def post_box(name: str = "post_box") -> bpy.types.Mesh:
    """A Type A pillar box: 1.4 m of red cast iron with a domed cap."""
    verts: list = []
    faces: list = []
    _tube(verts, faces, (0, 0, 0), (0, 0, 1.22), 0.30, sides=12)
    _tube(verts, faces, (0, 0, 1.22), (0, 0, 1.32), 0.33, sides=12, taper=0.94)
    _blob(verts, faces, (0, 0, 1.32), 0.29, rings=3, segments=12)
    return _mesh(name, verts, faces)
