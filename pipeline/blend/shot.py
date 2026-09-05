"""Cameras, light and render settings.

Two rigs. The overview is a diagnostic: a high oblique that shows the whole
block so the massing can be checked against the map. The street view is the
one that matters — it previews the actual hero framing, at eye height, on a
real street centreline taken from the OSM data rather than a guessed position.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

EYE_HEIGHT_M = 1.65


def _look_at(obj: bpy.types.Object, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _camera(name: str, location: Vector, target: Vector,
            lens_mm: float) -> bpy.types.Object:
    data = bpy.data.cameras.new(name)
    data.lens = lens_mm
    obj = bpy.data.objects.new(name, data)
    obj.location = location
    bpy.context.collection.objects.link(obj)
    _look_at(obj, target)
    return obj


def overview_camera(scene_data: dict, *, elevation_deg: float = 42.0,
                    azimuth_deg: float = 215.0, lens_mm: float = 45.0,
                    margin: float = 1.04) -> bpy.types.Object:
    """High oblique framing the whole site. Diagnostic, not a hero shot.

    Fitted against the real roofline rather than the bounding box: only one
    building here reaches 43 m, so fitting a box that tall would push the
    camera back far enough to leave the block small in a sea of ground.
    """
    elevation = math.radians(elevation_deg)
    azimuth = math.radians(azimuth_deg)
    direction = Vector((
        math.sin(azimuth) * math.cos(elevation),
        -math.cos(azimuth) * math.cos(elevation),
        math.sin(elevation),
    ))

    points = []
    for building in scene_data["buildings"]:
        height = building["height_m"]
        for x, y in building["footprint"]:
            points.append(Vector((x, y, 0.0)))
            points.append(Vector((x, y, height)))

    centre = sum(points, Vector()) / len(points)
    aim = Vector((centre.x, centre.y, centre.z * 0.9))
    distance = _fit_distance(points, aim, direction, lens_mm) * margin

    return _camera("cam_overview", aim + direction * distance, aim, lens_mm)


def _fit_distance(points: list[Vector], aim: Vector, direction: Vector,
                  lens_mm: float) -> float:
    """Closest camera distance along `direction` that still frames every point.

    Rotation does not depend on distance, so in camera space each point's x
    and y are fixed and only z slides with the camera. That reduces the fit to
    a max over points rather than a search.
    """
    scene = bpy.context.scene
    res_x = scene.render.resolution_x
    res_y = scene.render.resolution_y
    sensor = 36.0

    # Blender's automatic sensor fit applies the sensor width to the long edge.
    if res_x >= res_y:
        tan_h = (sensor / 2) / lens_mm
        tan_v = tan_h * res_y / res_x
    else:
        tan_v = (sensor / 2) / lens_mm
        tan_h = tan_v * res_x / res_y

    rotation = (-direction).to_track_quat("-Z", "Y").to_matrix()
    to_camera = rotation.transposed()

    distance = 0.0
    for point in points:
        local = to_camera @ (point - aim)
        distance = max(distance,
                       local.z + abs(local.x) / tan_h,
                       local.z + abs(local.y) / tan_v)
    return distance


def find_street(scene_data: dict, name: str) -> list[tuple[float, float]] | None:
    """Longest centreline carrying a given street name."""
    matches = [r for r in scene_data["roads"]
               if r.get("name") and name.lower() in r["name"].lower()
               and not r["is_footway"]]
    if not matches:
        return None
    return max(matches, key=lambda r: len(r["centreline"]))["centreline"]


def _resample(centreline: list[tuple[float, float]],
              fraction: float) -> Vector:
    """Point at a fraction of the way along a polyline, by arc length.

    Indexing by vertex is not the same thing: OSM puts nodes where the street
    bends, so vertex 3 of 7 can be metres from the halfway point.
    """
    points = [Vector((x, y, 0.0)) for x, y in centreline]
    spans = [(points[i + 1] - points[i]).length for i in range(len(points) - 1)]
    total = sum(spans)
    if total <= 0:
        return points[0]

    travelled = 0.0
    goal = total * max(0.0, min(1.0, fraction))
    for i, span in enumerate(spans):
        if travelled + span >= goal:
            return points[i].lerp(points[i + 1], (goal - travelled) / span)
        travelled += span
    return points[-1]


def street_camera(centreline: list[tuple[float, float]], *, along: float = 0.18,
                  look_ahead: float = 0.55, lens_mm: float = 35.0,
                  rise: float = 5.0,
                  eye: float = EYE_HEIGHT_M) -> bpy.types.Object:
    """Eye-height camera standing on a street, looking down it.

    A 35mm lens rather than a wider one: at street level anything wider makes
    the nearest facade swallow the frame. `rise` tilts the view up off the
    road surface and onto the buildings, which is where the detail will be.
    """
    location = _resample(centreline, along)
    location.z = eye
    target = _resample(centreline, look_ahead)
    target.z = eye + rise
    return _camera("cam_street", location, target, lens_mm)


def sun(*, elevation_deg: float = 34.0, azimuth_deg: float = 205.0,
        strength: float = 3.2, angle_deg: float = 1.5) -> bpy.types.Object:
    """Directional key light.

    `angle` is the sun's apparent disc size — the single most important control
    for shadow softness, and the thing that most obviously reads as fake when
    left at zero.
    """
    data = bpy.data.lights.new("sun", type="SUN")
    data.energy = strength
    data.angle = math.radians(angle_deg)

    obj = bpy.data.objects.new("sun", data)
    elevation = math.radians(elevation_deg)
    azimuth = math.radians(azimuth_deg)
    obj.location = Vector((
        math.sin(azimuth) * math.cos(elevation),
        -math.cos(azimuth) * math.cos(elevation),
        math.sin(elevation),
    )) * 200.0
    bpy.context.collection.objects.link(obj)
    _look_at(obj, Vector((0, 0, 0)))
    return obj


def flat_world(colour: tuple[float, float, float] = (0.55, 0.60, 0.68),
               strength: float = 1.0) -> None:
    """Plain sky ambient. Deliberately not an HDRI: at massing stage a busy
    environment flatters bad geometry."""
    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    background = world.node_tree.nodes["Background"]
    background.inputs["Color"].default_value = (*colour, 1.0)
    background.inputs["Strength"].default_value = strength
    bpy.context.scene.world = world


def configure_render(*, samples: int = 64, resolution: tuple[int, int] = (1600, 900),
                     denoise: bool = True) -> None:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = denoise
    # Bounces cost real time on CPU and massing needs none of them.
    scene.cycles.max_bounces = 4
    scene.cycles.diffuse_bounces = 3
    scene.cycles.glossy_bounces = 2
    scene.cycles.transmission_bounces = 2

    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "None"


def render_to(path, camera: bpy.types.Object) -> None:
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.filepath = str(path)
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
