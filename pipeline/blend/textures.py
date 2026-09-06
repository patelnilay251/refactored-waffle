"""Procedural surface detail.

All node graphs, no image textures: nothing to download, nothing to cache, and
no memory spent on maps for a few hundred buildings.

Three effects do nearly all the work at street distance.

*Tonal variation* — real brickwork is never one colour. Low-frequency noise
moves the base tone around so no two stretches of wall match.

*Vertical streaking* — rain running off sills and cornices leaves dirt trails
down a facade. Stretching a noise field hard in Z gives exactly that, and it
is probably the single most recognisable thing about a weathered London
building.

*Per-instance variation* — the Object Info node's Random output differs for
every linked duplicate, so several thousand windows sharing a handful of
meshes can still each have their own glass tint and reflectivity. Variation
for free, with no extra geometry.

Coordinates come from the Object socket, which for this pipeline equals world
space: meshes are built in world coordinates with objects left at the origin.
Grain therefore runs continuously across the site instead of restarting at
every building, which is what stops the tiling from reading.
"""

from __future__ import annotations

import bpy


def _tree(material: bpy.types.Material):
    if material.node_tree is None:
        material.use_nodes = True
    return material.node_tree


def _base(name: str):
    material = bpy.data.materials.new(name)
    tree = _tree(material)
    bsdf = tree.nodes["Principled BSDF"]
    return material, tree, bsdf


def _object_coords(tree, scale: tuple[float, float, float] = (1, 1, 1)):
    coords = tree.nodes.new("ShaderNodeTexCoord")
    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = scale
    tree.links.new(coords.outputs["Object"], mapping.inputs["Vector"])
    return mapping


def _noise(tree, vector, scale: float, detail: float = 3.0,
           roughness: float = 0.5):
    noise = tree.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = detail
    noise.inputs["Roughness"].default_value = roughness
    tree.links.new(vector, noise.inputs["Vector"])
    return noise


def _ramp(tree, source, stops):
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    elements = ramp.color_ramp.elements
    while len(elements) > len(stops):
        elements.remove(elements[-1])
    for index, (position, value) in enumerate(stops):
        if index >= len(elements):
            elements.new(position)
        elements[index].position = position
        elements[index].color = (value, value, value, 1.0)
    tree.links.new(source, ramp.inputs["Fac"])
    return ramp


# Real masonry, in metres. A London stock brick is 215 x 65 with a 10 mm bed
# joint, so the course repeats every 75 mm. That is the number that matters:
# at the hero camera it lands around nine pixels, which reads clearly. The
# first version of this shader had no courses at all and its only relief was
# an 8 mm noise — under a pixel at the same distance — so the walls rendered
# as painted surfaces, which is exactly what they looked like.
BRICK = {"length": 0.225, "course": 0.075, "joint": 0.035}
ASHLAR = {"length": 0.90, "course": 0.34, "joint": 0.012}


def _wall_uv(tree):
    """Coordinates for a course pattern on a vertical wall.

    Blender's brick texture reads x and y of its input vector, so feeding it
    world position directly gives stripes on any wall whose face is normal to
    one of those axes. Walls here are always vertical, so the second axis is
    always world Z; the first is world Y on an east-facing wall and world X on
    a north-facing one. Blending the two by which component of the normal
    dominates gives a correct pattern on every orientation without needing UVs
    on the mesh.
    """
    geometry = tree.nodes.new("ShaderNodeNewGeometry")
    position = tree.nodes.new("ShaderNodeSeparateXYZ")
    normal = tree.nodes.new("ShaderNodeSeparateXYZ")
    tree.links.new(geometry.outputs["Position"], position.inputs["Vector"])
    tree.links.new(geometry.outputs["Normal"], normal.inputs["Vector"])

    def absolute(socket):
        node = tree.nodes.new("ShaderNodeMath")
        node.operation = "ABSOLUTE"
        tree.links.new(socket, node.inputs[0])
        return node.outputs[0]

    abs_x, abs_y = absolute(normal.outputs["X"]), absolute(normal.outputs["Y"])
    total = tree.nodes.new("ShaderNodeMath")
    total.operation = "ADD"
    total.inputs[1].default_value = 1e-4
    tree.links.new(abs_x, total.inputs[0])
    add_y = tree.nodes.new("ShaderNodeMath")
    add_y.operation = "ADD"
    tree.links.new(total.outputs[0], add_y.inputs[0])
    tree.links.new(abs_y, add_y.inputs[1])

    fraction = tree.nodes.new("ShaderNodeMath")
    fraction.operation = "DIVIDE"
    tree.links.new(abs_x, fraction.inputs[0])
    tree.links.new(add_y.outputs[0], fraction.inputs[1])

    facing_y = tree.nodes.new("ShaderNodeCombineXYZ")   # wall faces north/south
    tree.links.new(position.outputs["X"], facing_y.inputs["X"])
    tree.links.new(position.outputs["Z"], facing_y.inputs["Y"])
    facing_x = tree.nodes.new("ShaderNodeCombineXYZ")   # wall faces east/west
    tree.links.new(position.outputs["Y"], facing_x.inputs["X"])
    tree.links.new(position.outputs["Z"], facing_x.inputs["Y"])

    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "VECTOR"
    tree.links.new(fraction.outputs[0], mix.inputs["Factor"])
    tree.links.new(facing_y.outputs["Vector"], mix.inputs[4])
    tree.links.new(facing_x.outputs["Vector"], mix.inputs[5])
    return mix.outputs[1]


def _courses(tree, vector, spec, colour, mortar_shift: float):
    """A brick or ashlar pattern: colour with per-unit variation, plus a mask
    that is 1 in the joints for driving relief and roughness."""
    brick = tree.nodes.new("ShaderNodeTexBrick")
    brick.offset = 0.5
    brick.squash = 1.0
    brick.inputs["Scale"].default_value = 1.0
    brick.inputs["Brick Width"].default_value = spec["length"]
    brick.inputs["Row Height"].default_value = spec["course"]
    brick.inputs["Mortar Size"].default_value = spec["joint"]
    brick.inputs["Mortar Smooth"].default_value = 0.12
    # Bias spreads the two brick colours; real brickwork is never one tone.
    brick.inputs["Bias"].default_value = 0.0
    brick.inputs["Color1"].default_value = (*[c * 0.76 for c in colour], 1.0)
    brick.inputs["Color2"].default_value = (
        *[min(c * 1.18, 1.0) for c in colour], 1.0)
    brick.inputs["Mortar"].default_value = (
        *[min(c * mortar_shift, 1.0) for c in colour], 1.0)
    tree.links.new(vector, brick.inputs["Vector"])
    return brick


def weathered_wall(name: str, colour: tuple[float, float, float],
                   roughness: float, *, streak: float = 0.36,
                   grain: float = 0.22,
                   courses: dict | None = None,
                   mortar_shift: float = 1.55,
                   bevel: float = 0.006) -> bpy.types.Material:
    """A wall with masonry courses, tonal drift, rain streaking and relief."""
    material, tree, bsdf = _base(name)

    uv = _wall_uv(tree)

    # Low-frequency drift across the brickwork.
    broad = _object_coords(tree, (0.08, 0.08, 0.08))
    drift = _noise(tree, broad.outputs["Vector"], scale=2.4, detail=4.0)

    joints = None
    if courses:
        pattern = _courses(tree, uv, courses, colour, mortar_shift)
        joints = pattern.outputs["Fac"]
        # Drift only nudges the pattern. Wired straight to the mix factor it
        # reaches 1.0 in places, replacing the brickwork entirely with flat
        # colour — which both washes out the courses just added and lifts the
        # whole wall several stops.
        nudge = tree.nodes.new("ShaderNodeMath")
        nudge.operation = "MULTIPLY"
        nudge.inputs[1].default_value = 0.30
        tree.links.new(drift.outputs["Fac"], nudge.inputs[0])

        tone = tree.nodes.new("ShaderNodeMixRGB")
        tone.blend_type = "MIX"
        tree.links.new(pattern.outputs["Color"], tone.inputs["Color1"])
        tone.inputs["Color2"].default_value = (
            *[min(c * 1.12, 1.0) for c in colour], 1.0)
        tree.links.new(nudge.outputs[0], tone.inputs["Fac"])
    else:
        darker = tuple(c * 0.68 for c in colour)
        lighter = tuple(min(c * 1.22, 1.0) for c in colour)
        tone = tree.nodes.new("ShaderNodeMixRGB")
        tone.blend_type = "MIX"
        tone.inputs["Color1"].default_value = (*darker, 1.0)
        tone.inputs["Color2"].default_value = (*lighter, 1.0)
        tree.links.new(drift.outputs["Fac"], tone.inputs["Fac"])

    # Rain streaking: the same noise field crushed in Z so it runs downward.
    # The scales matter more than they look. Mapping scale multiplies the noise
    # scale, so the feature size is 1/(mapping * noise) metres: these give
    # trails roughly 0.7 m apart running about 5 m down. Crushing Z harder
    # turns rain streaks into fine vertical corduroy, which reads as a fabric
    # weave rather than a dirty wall.
    streaked = _object_coords(tree, (0.5, 0.5, 0.06))
    trails = _noise(tree, streaked.outputs["Vector"], scale=3.0, detail=6.0,
                    roughness=0.68)
    # Only the darkest part of the field becomes grime, so streaks stay
    # occasional instead of covering the whole elevation.
    mask = _ramp(tree, trails.outputs["Fac"],
                 [(0.30, 1.0), (0.52, 0.0)])

    grime = tree.nodes.new("ShaderNodeMixRGB")
    grime.blend_type = "MULTIPLY"
    grime.inputs["Color2"].default_value = (0.62, 0.60, 0.56, 1.0)
    tree.links.new(tone.outputs["Color"], grime.inputs["Color1"])

    strength = tree.nodes.new("ShaderNodeMath")
    strength.operation = "MULTIPLY"
    strength.inputs[1].default_value = streak
    tree.links.new(mask.outputs["Color"], strength.inputs[0])
    tree.links.new(strength.outputs["Value"], grime.inputs["Fac"])

    # Per-building variation. All the stock-brick buildings share one material
    # for memory, so without this the whole terrace is literally the same
    # colour. Object Info's Random differs per object, which is exactly the
    # granularity wanted.
    info = tree.nodes.new("ShaderNodeObjectInfo")
    vary = tree.nodes.new("ShaderNodeHueSaturation")
    hue = tree.nodes.new("ShaderNodeMapRange")
    hue.inputs["To Min"].default_value = 0.472
    hue.inputs["To Max"].default_value = 0.528
    value = tree.nodes.new("ShaderNodeMapRange")
    value.inputs["To Min"].default_value = 0.84
    value.inputs["To Max"].default_value = 1.14
    tree.links.new(info.outputs["Random"], hue.inputs["Value"])
    tree.links.new(info.outputs["Random"], value.inputs["Value"])
    tree.links.new(hue.outputs["Result"], vary.inputs["Hue"])
    tree.links.new(value.outputs["Result"], vary.inputs["Value"])
    tree.links.new(grime.outputs["Color"], vary.inputs["Color"])
    tree.links.new(vary.outputs["Color"], bsdf.inputs["Base Color"])

    # Roughness follows the grain, and mortar is rougher than the brick it
    # beds.
    rough = tree.nodes.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = max(roughness - grain, 0.25)
    rough.inputs["To Max"].default_value = min(roughness + grain * 0.5, 1.0)
    tree.links.new(drift.outputs["Fac"], rough.inputs["Value"])
    rough_out = rough.outputs["Result"]
    if joints is not None:
        joint_rough = tree.nodes.new("ShaderNodeMath")
        joint_rough.operation = "ADD"
        joint_rough.use_clamp = True
        scaled = tree.nodes.new("ShaderNodeMath")
        scaled.operation = "MULTIPLY"
        scaled.inputs[1].default_value = 0.14
        tree.links.new(joints, scaled.inputs[0])
        tree.links.new(rough_out, joint_rough.inputs[0])
        tree.links.new(scaled.outputs[0], joint_rough.inputs[1])
        rough_out = joint_rough.outputs[0]
    tree.links.new(rough_out, bsdf.inputs["Roughness"])

    # Relief, innermost first. A shader bevel rounds the shading normal at
    # every arris without adding a polygon; perfectly sharp edges are one of
    # the loudest CG tells, and cornices and sills are nothing but arrises.
    normal = None
    if bevel > 0:
        bevel_node = tree.nodes.new("ShaderNodeBevel")
        bevel_node.inputs["Radius"].default_value = bevel
        bevel_node.samples = 3
        normal = bevel_node.outputs["Normal"]

    # Surface grain sized to actually resolve: ~35 mm features, not 8 mm.
    fine_bump = tree.nodes.new("ShaderNodeBump")
    fine_bump.inputs["Strength"].default_value = 0.22
    fine_bump.inputs["Distance"].default_value = 0.006
    fine = _noise(tree, _object_coords(tree, (3.2, 3.2, 3.2)).outputs["Vector"],
                  scale=9.0, detail=6.0)
    tree.links.new(fine.outputs["Fac"], fine_bump.inputs["Height"])
    if normal is not None:
        tree.links.new(normal, fine_bump.inputs["Normal"])
    normal = fine_bump.outputs["Normal"]

    if joints is not None:
        # Mortar sits back from the brick face, so height is low in the joint.
        recess = tree.nodes.new("ShaderNodeMath")
        recess.operation = "SUBTRACT"
        recess.inputs[0].default_value = 1.0
        tree.links.new(joints, recess.inputs[1])

        joint_bump = tree.nodes.new("ShaderNodeBump")
        joint_bump.inputs["Strength"].default_value = 0.62
        joint_bump.inputs["Distance"].default_value = 0.012
        tree.links.new(recess.outputs[0], joint_bump.inputs["Height"])
        tree.links.new(normal, joint_bump.inputs["Normal"])
        normal = joint_bump.outputs["Normal"]

    tree.links.new(normal, bsdf.inputs["Normal"])
    return material


def varied_glass(name: str = "glass") -> bpy.types.Material:
    """Dark glass whose tint and reflectivity differ per instance.

    Object Info's Random output is per linked duplicate, so thousands of
    windows sharing a few dozen meshes still read as individually different —
    some near-black, some catching more sky, a few brighter as though a blind
    or a lit room sits behind them.
    """
    material, tree, bsdf = _base(name)

    info = tree.nodes.new("ShaderNodeObjectInfo")

    tint = _ramp(tree, info.outputs["Random"],
                 [(0.0, 0.02), (0.55, 0.05), (0.86, 0.16), (1.0, 0.36)])
    tree.links.new(tint.outputs["Color"], bsdf.inputs["Base Color"])

    rough = tree.nodes.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = 0.03
    rough.inputs["To Max"].default_value = 0.22
    tree.links.new(info.outputs["Random"], rough.inputs["Value"])
    tree.links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])

    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.2
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.9
    return material


def worn_ground(name: str, colour: tuple[float, float, float],
                roughness: float, scale: float = 1.6, *,
                slab: float = 0.0, bevel: float = 0.004) -> bpy.types.Material:
    """Road or pavement with patching, wear and joint-scale variation.

    `slab` lays a paving grid of that size in metres. York stone flags run
    about 600 mm, and their joints are the reason a pavement reads as a
    pavement rather than a grey plane — the same mistake the walls made.
    """
    material, tree, bsdf = _base(name)

    coords = _object_coords(tree, (0.05, 0.05, 0.05))
    patches = _noise(tree, coords.outputs["Vector"], scale=scale, detail=5.0)

    if slab > 0:
        return _paved(material, tree, bsdf, colour, roughness, patches, slab,
                      bevel)

    darker = tuple(c * 0.72 for c in colour)
    lighter = tuple(min(c * 1.30, 1.0) for c in colour)

    tone = tree.nodes.new("ShaderNodeMixRGB")
    tone.inputs["Color1"].default_value = (*darker, 1.0)
    tone.inputs["Color2"].default_value = (*lighter, 1.0)
    tree.links.new(patches.outputs["Fac"], tone.inputs["Fac"])
    tree.links.new(tone.outputs["Color"], bsdf.inputs["Base Color"])

    rough = tree.nodes.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = max(roughness - 0.18, 0.2)
    rough.inputs["To Max"].default_value = min(roughness + 0.1, 1.0)
    tree.links.new(patches.outputs["Fac"], rough.inputs["Value"])
    tree.links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])

    bump = tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.10
    fine = _noise(tree, _object_coords(tree, (9, 9, 9)).outputs["Vector"],
                  scale=12.0, detail=6.0)
    tree.links.new(fine.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    return material


def _paved(material, tree, bsdf, colour, roughness, patches, slab, bevel):
    """Slabbed pavement: a flag grid with recessed joints, over the patching.

    The grid is laid in world XY, so it runs continuously across the whole
    site instead of restarting at every mesh island — pavement is one surface
    in reality and the joints should not betray where our polygons end.
    """
    geometry = tree.nodes.new("ShaderNodeNewGeometry")
    flat = tree.nodes.new("ShaderNodeSeparateXYZ")
    tree.links.new(geometry.outputs["Position"], flat.inputs["Vector"])
    plane = tree.nodes.new("ShaderNodeCombineXYZ")
    tree.links.new(flat.outputs["X"], plane.inputs["X"])
    tree.links.new(flat.outputs["Y"], plane.inputs["Y"])

    flags = tree.nodes.new("ShaderNodeTexBrick")
    flags.offset = 0.5
    flags.inputs["Scale"].default_value = 1.0
    flags.inputs["Brick Width"].default_value = slab
    flags.inputs["Row Height"].default_value = slab * 0.82
    flags.inputs["Mortar Size"].default_value = 0.018
    flags.inputs["Mortar Smooth"].default_value = 0.2
    flags.inputs["Color1"].default_value = (*[c * 0.86 for c in colour], 1.0)
    flags.inputs["Color2"].default_value = (
        *[min(c * 1.20, 1.0) for c in colour], 1.0)
    flags.inputs["Mortar"].default_value = (
        *[c * 0.62 for c in colour], 1.0)
    tree.links.new(plane.outputs["Vector"], flags.inputs["Vector"])

    # Patching darkens and lightens whole areas over the top of the flags.
    wear = tree.nodes.new("ShaderNodeMixRGB")
    wear.blend_type = "MULTIPLY"
    wear.inputs["Fac"].default_value = 0.35
    tree.links.new(flags.outputs["Color"], wear.inputs["Color1"])
    tree.links.new(patches.outputs["Color"], wear.inputs["Color2"])
    tree.links.new(wear.outputs["Color"], bsdf.inputs["Base Color"])

    rough = tree.nodes.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = max(roughness - 0.16, 0.2)
    rough.inputs["To Max"].default_value = min(roughness + 0.10, 1.0)
    tree.links.new(patches.outputs["Fac"], rough.inputs["Value"])
    tree.links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])

    normal = None
    if bevel > 0:
        bevel_node = tree.nodes.new("ShaderNodeBevel")
        bevel_node.inputs["Radius"].default_value = bevel
        bevel_node.samples = 3
        normal = bevel_node.outputs["Normal"]

    grit = tree.nodes.new("ShaderNodeBump")
    grit.inputs["Strength"].default_value = 0.18
    grit.inputs["Distance"].default_value = 0.004
    fine = _noise(tree, _object_coords(tree, (4.0, 4.0, 4.0)).outputs["Vector"],
                  scale=11.0, detail=6.0)
    tree.links.new(fine.outputs["Fac"], grit.inputs["Height"])
    if normal is not None:
        tree.links.new(normal, grit.inputs["Normal"])

    recess = tree.nodes.new("ShaderNodeMath")
    recess.operation = "SUBTRACT"
    recess.inputs[0].default_value = 1.0
    tree.links.new(flags.outputs["Fac"], recess.inputs[1])

    joint = tree.nodes.new("ShaderNodeBump")
    joint.inputs["Strength"].default_value = 0.55
    joint.inputs["Distance"].default_value = 0.010
    tree.links.new(recess.outputs[0], joint.inputs["Height"])
    tree.links.new(grit.outputs["Normal"], joint.inputs["Normal"])
    tree.links.new(joint.outputs["Normal"], bsdf.inputs["Normal"])
    return material
