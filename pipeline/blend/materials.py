"""Materials.

Stage 2 only needs clay: a single matte shader so that form, massing and
shadow read without colour or texture confusing the judgement. Real materials
arrive in stage 5.
"""

from __future__ import annotations

import bpy


def _principled(name: str, colour: tuple[float, float, float],
                roughness: float) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*colour, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.2
    return material


def clay(name: str = "clay") -> bpy.types.Material:
    """Neutral mid-grey. Deliberately not white: blown-out highlights hide the
    very massing errors this stage exists to catch."""
    return _principled(name, (0.62, 0.60, 0.57), 0.72)


def clay_ground(name: str = "clay_ground") -> bpy.types.Material:
    """A shade darker than the buildings so footprints stay legible."""
    return _principled(name, (0.42, 0.41, 0.39), 0.85)


def asphalt(name: str = "asphalt") -> bpy.types.Material:
    """Flat carriageway tone. Real asphalt is darker than people expect, but
    not black - weathered London tarmac sits around 8-12% reflectance."""
    return _principled(name, (0.085, 0.085, 0.088), 0.85)


def paving(name: str = "paving") -> bpy.types.Material:
    """Pavement slabs: a warm grey, lighter than the road so the kerb line
    reads without needing a separate kerb material."""
    return _principled(name, (0.30, 0.288, 0.268), 0.80)
