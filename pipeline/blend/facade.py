"""Meshing facades.

Memory strategy, since this stage is where a city model normally explodes:

* The building shell — walls, reveals, cornices — is unique per building, but
  it is cheap: a wall is a triangulated rectangle with holes, and a reveal is
  four quads per opening.
* Windows are not unique. They are *quantised* to the nearest 5 cm and cached,
  so the few thousand openings on site resolve to a few dozen actual meshes,
  each instanced by linked duplicate objects that share the mesh datablock.
  Cycles instances them again at render time. Quantising rather than scaling a
  single unit mesh keeps frame and glazing-bar thickness constant instead of
  stretching with the opening.

Winding is handled by asking for the outward direction explicitly and flipping
any face that disagrees. The alternative — letting Blender recalculate normals
— is unreliable here because a facade shell is deliberately not closed: every
window opening is a hole with reveals turning inward through it.
"""

from __future__ import annotations

import bpy
import shapely
from mathutils import Vector
from shapely.geometry import Polygon, box

from ..facades import (CORNICE_DEPTH_M, CORNICE_PROJECTION_M, REVEAL_DEPTH_M,
                       FacadeBuilding, Wall)

# Window construction, all metres.
FRAME_THICKNESS = 0.055
FRAME_PROJECTION = 0.045
BAR_THICKNESS = 0.028
BAR_PROJECTION = 0.030
SILL_PROJECTION = 0.07
SILL_DEPTH = 0.09

# Openings are rounded to this before a mesh is cached for them, then scaled
# by the small remainder so the fit stays exact. Coarse enough that a few
# thousand openings collapse onto a few dozen meshes; the residual scale stays
# under a few percent, which is invisible in frame thickness.
SIZE_QUANTUM_M = 0.15

# Material slot order used on every facade mesh.
SLOT_WALL, SLOT_TRIM = 0, 1
SLOT_FRAME, SLOT_GLASS = 0, 1


class Frame:
    """Wall-local coordinates: u along the wall, v up, n outward."""

    def __init__(self, wall: Wall):
        dx, dy = wall.direction
        nx, ny = wall.normal
        self.origin = Vector((wall.start[0], wall.start[1], 0.0))
        self.u = Vector((dx, dy, 0.0))
        self.v = Vector((0.0, 0.0, 1.0))
        self.n = Vector((nx, ny, 0.0))

    def at(self, u: float, v: float, n: float = 0.0) -> Vector:
        return self.origin + self.u * u + self.v * v + self.n * n


class Sink:
    """Accumulates vertices and faces, deduplicating shared corners."""

    def __init__(self):
        self.verts: list[tuple[float, float, float]] = []
        self.faces: list[tuple[int, ...]] = []
        self.slots: list[int] = []
        self._index: dict[tuple[int, int, int], int] = {}

    def vertex(self, point: Vector) -> int:
        key = (round(point.x * 1000), round(point.y * 1000), round(point.z * 1000))
        if key not in self._index:
            self._index[key] = len(self.verts)
            self.verts.append((point.x, point.y, point.z))
        return self._index[key]

    def face(self, points: list[Vector], outward: Vector, slot: int = 0) -> None:
        """Add a face, flipping it if it does not agree with `outward`."""
        if len(points) < 3:
            return
        normal = (points[1] - points[0]).cross(points[2] - points[0])
        if normal.dot(outward) < 0:
            points = list(reversed(points))
        indices = tuple(self.vertex(p) for p in points)
        if len(set(indices)) == len(indices):
            self.faces.append(indices)
            self.slots.append(slot)

    def to_mesh(self, name: str) -> bpy.types.Mesh | None:
        if not self.faces:
            return None
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(self.verts, [], self.faces)
        mesh.validate(verbose=False)
        if len(mesh.polygons) == len(self.slots):
            for polygon, slot in zip(mesh.polygons, self.slots):
                polygon.material_index = slot
        mesh.shade_flat()
        return mesh


def _panel(sink: Sink, frame: Frame, wall: Wall) -> None:
    """The wall surface itself: a rectangle with a hole per opening.

    Triangulated rather than emitted as an ngon because Blender ngons cannot
    carry holes, and a frontage is a rectangle with twenty of them.
    """
    surface = box(0.0, 0.0, wall.length, wall.height)
    holes = [box(o.u0, o.v0, o.u1, o.v1) for o in wall.openings]
    if holes:
        surface = surface.difference(shapely.union_all(holes))
    if surface.is_empty:
        return

    parts = [g for g in getattr(surface, "geoms", [surface])
             if g.geom_type == "Polygon"]
    for part in parts:
        for triangle in shapely.constrained_delaunay_triangles(part).geoms:
            ring = list(triangle.exterior.coords)[:-1]
            sink.face([frame.at(u, v) for u, v in ring], frame.n, SLOT_WALL)


def _reveals(sink: Sink, frame: Frame, wall: Wall) -> None:
    """The returns turning inward through each opening.

    This is what makes a window read as a hole in a wall rather than a picture
    of one — the shadow it casts is most of the effect.
    """
    depth = REVEAL_DEPTH_M
    for opening in wall.openings:
        u0, u1, v0, v1 = opening.u0, opening.u1, opening.v0, opening.v1
        # Head: the underside of the lintel, facing down into the opening.
        sink.face([frame.at(u0, v1), frame.at(u1, v1),
                   frame.at(u1, v1, -depth), frame.at(u0, v1, -depth)],
                  -frame.v, SLOT_WALL)
        # Sill: facing up.
        sink.face([frame.at(u0, v0), frame.at(u1, v0),
                   frame.at(u1, v0, -depth), frame.at(u0, v0, -depth)],
                  frame.v, SLOT_WALL)
        # Jambs: facing each other across the opening.
        sink.face([frame.at(u0, v0), frame.at(u0, v1),
                   frame.at(u0, v1, -depth), frame.at(u0, v0, -depth)],
                  frame.u, SLOT_WALL)
        sink.face([frame.at(u1, v0), frame.at(u1, v1),
                   frame.at(u1, v1, -depth), frame.at(u1, v0, -depth)],
                  -frame.u, SLOT_WALL)


def _prism(sink: Sink, frame: Frame, u0: float, u1: float,
           v0: float, v1: float, n0: float, n1: float, slot: int) -> None:
    """An axis-aligned box in wall-local space."""
    corners = {
        (a, b, c): frame.at(u0 if a == 0 else u1,
                            v0 if b == 0 else v1,
                            n0 if c == 0 else n1)
        for a in (0, 1) for b in (0, 1) for c in (0, 1)
    }
    faces = [
        ([(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)], frame.n),
        ([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], -frame.n),
        ([(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)], -frame.u),
        ([(1, 0, 0), (1, 0, 1), (1, 1, 1), (1, 1, 0)], frame.u),
        ([(0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1)], frame.v),
        ([(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)], -frame.v),
    ]
    for keys, outward in faces:
        sink.face([corners[k] for k in keys], outward, slot)


def _cornice(sink: Sink, frame: Frame, wall: Wall) -> None:
    if not wall.cornice or wall.height < CORNICE_DEPTH_M * 2:
        return
    _prism(sink, frame, 0.0, wall.length,
           wall.height - CORNICE_DEPTH_M, wall.height,
           0.0, CORNICE_PROJECTION_M, SLOT_TRIM)


def _fascias(sink: Sink, frame: Frame, wall: Wall) -> None:
    """The painted sign band over each shopfront.

    Without it the ground floor is glazing set straight into brickwork, which
    no London street actually does — the fascia is what separates shop from
    building, and it is the strongest horizontal line at eye level.
    """
    from ..facades import SHOPFRONT_FASCIA_M

    for opening in wall.openings:
        if opening.kind != "shopfront":
            continue
        top = min(opening.v1 + SHOPFRONT_FASCIA_M, wall.height)
        if top <= opening.v1 + 0.1:
            continue
        _prism(sink, frame, opening.u0 - 0.1, opening.u1 + 0.1,
               opening.v1, top, -REVEAL_DEPTH_M, 0.11, SLOT_TRIM)


def _sills(sink: Sink, frame: Frame, wall: Wall) -> None:
    """A projecting stone sill under each window. Small, but it is the thing
    that throws a shadow line across the wall and breaks up flat brickwork."""
    for opening in wall.openings:
        if opening.kind != "window":
            continue
        _prism(sink, frame, opening.u0 - 0.07, opening.u1 + 0.07,
               opening.v0 - SILL_DEPTH, opening.v0,
               -REVEAL_DEPTH_M, SILL_PROJECTION, SLOT_TRIM)


def _plain_wall(sink: Sink, frame: Frame, wall: Wall) -> None:
    sink.face([frame.at(0, 0), frame.at(wall.length, 0),
               frame.at(wall.length, wall.height), frame.at(0, wall.height)],
              frame.n, SLOT_WALL)


def window_mesh(width: float, height: float, kind: str,
                cache: dict) -> bpy.types.Mesh:
    """Frame, glazing bars and glass for one opening size.

    Sizes are quantised so a few thousand openings collapse onto a few dozen
    meshes, each shared by linked duplicates.
    """
    key = (round(width / SIZE_QUANTUM_M), round(height / SIZE_QUANTUM_M), kind)
    if key in cache:
        return cache[key]

    w = key[0] * SIZE_QUANTUM_M
    h = key[1] * SIZE_QUANTUM_M

    # A shopfront is a wider, more open grid than a domestic sash.
    if kind == "shopfront":
        columns, rows, thickness = max(2, int(w / 1.5)), 1, FRAME_THICKNESS * 1.4
    elif kind == "door":
        columns, rows, thickness = 1, 2, FRAME_THICKNESS * 1.3
    else:
        columns, rows, thickness = 2, 3, FRAME_THICKNESS

    sink = Sink()
    frame = _identity_frame()

    if kind == "door":
        # Solid leaf with recessed panels, and a glazed fanlight over it. The
        # fanlight is the giveaway detail on a Georgian street door, and it is
        # the only part of a door that should read as glass at all.
        fan = h * 0.80
        _prism(sink, frame, 0, w, 0, h, 0, FRAME_PROJECTION * 0.6, SLOT_FRAME)
        for row in range(2):
            v0 = 0.10 + row * (fan - 0.30) / 2
            v1 = v0 + (fan - 0.40) / 2
            _prism(sink, frame, 0.12, w - 0.12, v0, v1,
                   FRAME_PROJECTION * 0.6, FRAME_PROJECTION * 0.6 + 0.02,
                   SLOT_FRAME)
        _prism(sink, frame, 0, w, fan, fan + thickness, 0,
               FRAME_PROJECTION, SLOT_FRAME)
        sink.face([frame.at(thickness, fan + thickness, -0.01),
                   frame.at(w - thickness, fan + thickness, -0.01),
                   frame.at(w - thickness, h - thickness, -0.01),
                   frame.at(thickness, h - thickness, -0.01)],
                  frame.n, SLOT_GLASS)
        mesh = sink.to_mesh(f"door_{key[0]}x{key[1]}")
        cache[key] = mesh
        return mesh

    # Outer frame, as four prisms standing proud of the glass.
    _prism(sink, frame, 0, w, 0, thickness, 0, FRAME_PROJECTION, SLOT_FRAME)
    _prism(sink, frame, 0, w, h - thickness, h, 0, FRAME_PROJECTION, SLOT_FRAME)
    _prism(sink, frame, 0, thickness, 0, h, 0, FRAME_PROJECTION, SLOT_FRAME)
    _prism(sink, frame, w - thickness, w, 0, h, 0, FRAME_PROJECTION, SLOT_FRAME)

    inner_w = w - 2 * thickness
    inner_h = h - 2 * thickness
    for c in range(1, columns):
        u = thickness + inner_w * c / columns
        _prism(sink, frame, u - BAR_THICKNESS / 2, u + BAR_THICKNESS / 2,
               thickness, h - thickness, 0, BAR_PROJECTION, SLOT_FRAME)
    for r in range(1, rows):
        v = thickness + inner_h * r / rows
        _prism(sink, frame, thickness, w - thickness,
               v - BAR_THICKNESS / 2, v + BAR_THICKNESS / 2,
               0, BAR_PROJECTION, SLOT_FRAME)

    # Glass, set just behind the frame.
    sink.face([frame.at(thickness, thickness, -0.01),
               frame.at(w - thickness, thickness, -0.01),
               frame.at(w - thickness, h - thickness, -0.01),
               frame.at(thickness, h - thickness, -0.01)],
              frame.n, SLOT_GLASS)

    mesh = sink.to_mesh(f"window_{key[0]}x{key[1]}_{kind}")
    cache[key] = mesh
    return mesh


class _IdentityFrame:
    """Build frame for a cached window mesh.

    Axes map straight onto local x/y/z — u->x, v->y, n->z — so that the
    placement matrix can carry the wall's own u/v/n as its columns without any
    reshuffling. Getting this wrong swaps window height with window depth, and
    the frames project out of the wall like shelves.
    """

    origin = Vector((0.0, 0.0, 0.0))
    u = Vector((1.0, 0.0, 0.0))
    v = Vector((0.0, 1.0, 0.0))
    n = Vector((0.0, 0.0, 1.0))

    def at(self, u: float, v: float, n: float = 0.0) -> Vector:
        return self.origin + self.u * u + self.v * v + self.n * n


def _identity_frame() -> _IdentityFrame:
    return _IdentityFrame()


def build_shell(building: FacadeBuilding, footprint: list[tuple[float, float]],
                name: str) -> bpy.types.Mesh | None:
    """Walls, reveals, sills, cornices, roof and base for one building."""
    sink = Sink()
    detailed = {(tuple(w.start), tuple(w.end)): w for w in building.walls}

    count = len(footprint)
    for i in range(count):
        start = footprint[i]
        end = footprint[(i + 1) % count]
        wall = detailed.get((tuple(start), tuple(end)))
        if wall is None:
            # Hidden party wall: a bare quad, no openings, no trim.
            wall = Wall(start, end,
                        (Vector(end) - Vector(start)).length, building.height)
            _plain_wall(sink, Frame(wall), wall)
            continue

        frame = Frame(wall)
        if wall.openings:
            _panel(sink, frame, wall)
            _reveals(sink, frame, wall)
            _sills(sink, frame, wall)
            _fascias(sink, frame, wall)
        else:
            _plain_wall(sink, frame, wall)
        _cornice(sink, frame, wall)

    up = Vector((0, 0, 1))
    roof = [Vector((x, y, building.height)) for x, y in footprint]
    base = [Vector((x, y, 0.0)) for x, y in footprint]
    sink.face(roof, up, SLOT_WALL)
    sink.face(base, -up, SLOT_WALL)

    return sink.to_mesh(name)


def place_openings(building: FacadeBuilding, collection: bpy.types.Collection,
                   cache: dict, materials: list[bpy.types.Material]) -> int:
    """Instance a window mesh into every opening. Returns how many were placed."""
    placed = 0
    for wall in building.walls:
        frame = Frame(wall)
        for opening in wall.openings:
            mesh = window_mesh(opening.width, opening.height, opening.kind, cache)
            if mesh is None:
                continue
            if not mesh.materials:
                for material in materials:
                    mesh.materials.append(material)

            obj = bpy.data.objects.new(f"win_{building.osm_id}_{placed}", mesh)
            # Linked duplicate: the object is a transform, the mesh is shared.
            obj.matrix_world = _placement(frame, opening)
            collection.objects.link(obj)
            placed += 1
    return placed


def _placement(frame: Frame, opening):
    """Transform putting a cached window mesh into an opening.

    The mesh was built at a quantised size, so u and v are scaled by the small
    remainder to fill the opening exactly. Depth is left unscaled — stretching
    it would change how far the frame stands proud of the reveal.
    """
    from mathutils import Matrix

    w = max(round(opening.width / SIZE_QUANTUM_M), 1) * SIZE_QUANTUM_M
    h = max(round(opening.height / SIZE_QUANTUM_M), 1) * SIZE_QUANTUM_M
    su = opening.width / w
    sv = opening.height / h

    origin = frame.at(opening.u0, opening.v0, -REVEAL_DEPTH_M + 0.02)
    u, v, n = frame.u * su, frame.v * sv, frame.n
    return Matrix((
        (u.x, v.x, n.x, origin.x),
        (u.y, v.y, n.y, origin.y),
        (u.z, v.z, n.z, origin.z),
        (0.0, 0.0, 0.0, 1.0),
    ))
