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
        strength: float = 3.2, angle_deg: float = 0.55,
        colour: tuple[float, float, float] | None = None) -> bpy.types.Object:
    """Directional key light.

    Azimuth is a compass bearing, clockwise from north, matching
    `pipeline.solar`. `angle` is the sun's apparent disc size: the real one is
    0.53 degrees, and it is the single most important control for shadow
    softness — left at zero, every shadow edge is razor sharp and the image
    reads as CG immediately.
    """
    data = bpy.data.lights.new("sun", type="SUN")
    data.energy = strength
    data.angle = math.radians(angle_deg)
    if colour:
        data.color = colour

    obj = bpy.data.objects.new("sun", data)
    elevation = math.radians(elevation_deg)
    azimuth = math.radians(azimuth_deg)
    obj.location = Vector((
        math.sin(azimuth) * math.cos(elevation),
        math.cos(azimuth) * math.cos(elevation),
        math.sin(elevation),
    )) * 400.0
    bpy.context.collection.objects.link(obj)
    _look_at(obj, Vector((0, 0, 0)))
    return obj


def _node_tree(datablock):
    """World node trees are implicit from Blender 5.0; `use_nodes` is on its
    way out but still needed on older builds."""
    if datablock.node_tree is None:
        datablock.use_nodes = True
    return datablock.node_tree


def sky(sun_position, *, dust: float = 2.2, strength: float = 1.0,
        air: float = 1.0, ozone: float = 1.4,
        ground_albedo: float = 0.16) -> bpy.types.World:
    """Physical sky, driving ambient light and the visible background.

    The sky's own sun disc is switched off and a separate sun lamp does the
    key. A disc in an environment texture is sampled as part of the whole
    hemisphere, so it converges far more slowly than a light Cycles knows how
    to aim rays at — on a CPU budget that difference is the render.

    `dust` is doing the London work: it warms and thickens the low sun and
    pushes the horizon toward the milky grey the city actually has.
    """
    world = bpy.data.worlds.new("sky")
    tree = _node_tree(world)
    background = tree.nodes["Background"]
    background.inputs["Strength"].default_value = strength

    texture = tree.nodes.new("ShaderNodeTexSky")
    # Blender 5.0 replaced the single "Nishita" model with an explicit choice
    # of scattering order; multiple scattering is the one that fills shadowed
    # streets with sky light instead of leaving them flat.
    texture.sky_type = "MULTIPLE_SCATTERING"
    texture.sun_elevation = math.radians(max(sun_position.elevation, 0.4))
    texture.sun_rotation = _sky_rotation(sun_position.azimuth)
    texture.sun_disc = False
    texture.air_density = air
    texture.aerosol_density = dust
    texture.ozone_density = ozone
    texture.ground_albedo = ground_albedo
    tree.links.new(texture.outputs["Color"], background.inputs["Color"])

    bpy.context.scene.world = world
    return world


def _sky_rotation(azimuth_deg: float) -> float:
    """Compass azimuth to sky-texture rotation.

    The sky texture measures anticlockwise from +X; a compass bearing runs
    clockwise from +Y. The two differ by a quarter turn and a sign.
    """
    return math.radians(90.0 - azimuth_deg)


def atmosphere(*, span: float = 2000.0, height: float = 600.0,
               density: float = 0.00016, anisotropy: float = 0.45,
               colour: tuple[float, float, float] = (0.66, 0.72, 0.82),
               ) -> bpy.types.Object:
    """Aerial perspective — haze accumulating with distance.

    The strongest depth cue a city image has: without it every building sits
    at the same apparent distance and the street reads as a diorama. A low sun
    through a narrow street also picks out shafts where it clears a roofline.

    This is a *bounded* box, not a world volume. Attaching a scatter shader to
    the world volume output looks like the obvious way to do it and renders
    pure black: the world volume is infinite, so every ray that escapes to the
    sky accumulates extinction over infinite distance and transmittance goes
    to zero. The box has to contain both cameras, but only just — sized at 6 km
    the sun has kilometres of volume to cross and is extinguished before it
    reaches anything, which produces a scene lit entirely by flat sky ambient.

    Shadow rays are excluded from the volume for the same reason. Physically
    the sun should be slightly dimmed by haze, but that dimming is already in
    the sky model's own sun colour, and paying for it twice costs the whole
    key light. Camera rays still cross the volume, so the haze itself is
    unaffected.

    Density is deliberately restrained: genuinely strong aerial perspective
    happens across kilometres, and forcing it at street scale reads as fog
    rather than distance.
    """
    half, top = span / 2, height

    mesh = bpy.data.meshes.new("atmosphere")
    verts = [(-half, -half, -5.0), (half, -half, -5.0),
             (half, half, -5.0), (-half, half, -5.0),
             (-half, -half, top), (half, -half, top),
             (half, half, top), (-half, half, top)]
    faces = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1),
             (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    mesh.from_pydata(verts, [], faces)
    mesh.validate(verbose=False)

    material = bpy.data.materials.new("atmosphere")
    tree = _node_tree(material)
    # No surface shader at all, so the box itself is invisible and only its
    # volume contributes.
    for node in [n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"]:
        tree.nodes.remove(node)
    output = next(n for n in tree.nodes if n.type == "OUTPUT_MATERIAL")

    scatter = tree.nodes.new("ShaderNodeVolumeScatter")
    scatter.inputs["Density"].default_value = density
    scatter.inputs["Anisotropy"].default_value = anisotropy
    scatter.inputs["Color"].default_value = (*colour, 1.0)
    tree.links.new(scatter.outputs["Volume"], output.inputs["Volume"])

    mesh.materials.append(material)
    obj = bpy.data.objects.new("atmosphere", mesh)
    obj.visible_shadow = False
    bpy.context.collection.objects.link(obj)

    # Single scattering is what makes the haze visible at all; without at
    # least one volume bounce the box only subtracts light.
    bpy.context.scene.cycles.volume_bounces = max(
        bpy.context.scene.cycles.volume_bounces, 1)
    return obj


def flat_world(colour: tuple[float, float, float] = (0.55, 0.60, 0.68),
               strength: float = 1.0) -> None:
    """Plain sky ambient. Deliberately not an HDRI: at massing stage a busy
    environment flatters bad geometry."""
    world = bpy.data.worlds.new("world")
    background = _node_tree(world).nodes["Background"]
    background.inputs["Color"].default_value = (*colour, 1.0)
    background.inputs["Strength"].default_value = strength
    bpy.context.scene.world = world


def configure_render(*, samples: int = 64, resolution: tuple[int, int] = (1600, 900),
                     denoise: bool = True, exposure: float = 0.0,
                     look: str = "None") -> None:
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
    scene.view_settings.look = look
    scene.view_settings.exposure = exposure


def depth_of_field(camera: bpy.types.Object, focus_m: float,
                   fstop: float = 5.6, blades: int = 7) -> None:
    """Physical defocus.

    Restrained on purpose: a 26mm lens at f/5.6 focused 35 m down a street has
    almost everything sharp, and that is correct. The point is not visible
    blur but the small amount on the nearest foot of pavement and the furthest
    facade, which is what tells the eye it is looking through a lens.
    `blades` gives the aperture straight edges, so out-of-focus highlights are
    polygonal rather than perfect discs.
    """
    dof = camera.data.dof
    dof.use_dof = True
    dof.focus_distance = focus_m
    dof.aperture_fstop = fstop
    dof.aperture_blades = blades


def render_to(path, camera: bpy.types.Object) -> None:
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.filepath = str(path)
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
