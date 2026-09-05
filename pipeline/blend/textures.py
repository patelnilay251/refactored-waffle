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


def weathered_wall(name: str, colour: tuple[float, float, float],
                   roughness: float, *, streak: float = 0.36,
                   grain: float = 0.22) -> bpy.types.Material:
    """A wall with tonal drift, rain streaking and varied roughness."""
    material, tree, bsdf = _base(name)

    # Low-frequency drift across the brickwork.
    broad = _object_coords(tree, (0.08, 0.08, 0.08))
    drift = _noise(tree, broad.outputs["Vector"], scale=2.4, detail=4.0)

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
    tree.links.new(grime.outputs["Color"], bsdf.inputs["Base Color"])

    # Roughness follows the grain, so highlights break up rather than sheeting.
    rough = tree.nodes.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = max(roughness - grain, 0.25)
    rough.inputs["To Max"].default_value = min(roughness + grain * 0.5, 1.0)
    tree.links.new(drift.outputs["Fac"], rough.inputs["Value"])
    tree.links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])

    # A little relief, so raking light catches the surface.
    bump = tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.16
    bump.inputs["Distance"].default_value = 0.01
    fine = _noise(tree, _object_coords(tree, (14, 14, 14)).outputs["Vector"],
                  scale=9.0, detail=5.0)
    tree.links.new(fine.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

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
                roughness: float, scale: float = 1.6) -> bpy.types.Material:
    """Road or pavement with patching, wear and joint-scale variation."""
    material, tree, bsdf = _base(name)

    coords = _object_coords(tree, (0.05, 0.05, 0.05))
    patches = _noise(tree, coords.outputs["Vector"], scale=scale, detail=5.0)

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
