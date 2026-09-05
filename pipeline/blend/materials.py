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


# Wall palette. London stock brick — the yellow-brown one — is the default
# rather than red: it is what most of Soho is actually built from, and getting
# that base tone wrong is immediately obvious to anyone who knows the city.
WALL_TONES = {
    "stock_brick": ((0.286, 0.235, 0.163), 0.86),
    "red_brick": ((0.232, 0.108, 0.081), 0.86),
    "brown_brick": ((0.215, 0.155, 0.115), 0.86),
    "portland_stone": ((0.520, 0.494, 0.435), 0.78),
    "stucco": ((0.582, 0.560, 0.512), 0.74),
    "concrete": ((0.362, 0.358, 0.345), 0.82),
}

# How OSM `building:material` maps onto that palette.
OSM_MATERIAL = {
    "brick": "stock_brick",
    "brickwork": "stock_brick",
    "red_brick": "red_brick",
    "stone": "portland_stone",
    "limestone": "portland_stone",
    "sandstone": "portland_stone",
    "concrete": "concrete",
    "cement_block": "concrete",
    "plaster": "stucco",
    "render": "stucco",
    "stucco": "stucco",
    "tile": "brown_brick",
    "wood": "brown_brick",
    "metal": "concrete",
    "glass": "concrete",
}

# Weighted fallback for the 54% with no material tag, biased to what Soho is.
UNTAGGED_MIX = (["stock_brick"] * 5 + ["red_brick"] * 2 + ["brown_brick"]
                + ["stucco"] * 2 + ["portland_stone"] + ["concrete"])


def wall_material(osm_material: str | None, osm_id: int,
                  cache: dict) -> bpy.types.Material:
    """A wall material, from the OSM tag where there is one.

    Cached by tone so the whole site shares a handful of materials rather than
    carrying one per building.
    """
    tone = OSM_MATERIAL.get((osm_material or "").lower())
    if tone is None:
        tone = UNTAGGED_MIX[osm_id % len(UNTAGGED_MIX)]

    if tone not in cache:
        colour, roughness = WALL_TONES[tone]
        cache[tone] = _principled(f"wall_{tone}", colour, roughness)
    return cache[tone]


def trim(name: str = "trim") -> bpy.types.Material:
    """Painted stone: cornices, sills, shopfront fascias. Off-white rather
    than white, which would blow out against the sky."""
    return _principled(name, (0.640, 0.622, 0.585), 0.62)


def window_frame(name: str = "window_frame") -> bpy.types.Material:
    """Painted joinery, a touch brighter than the trim."""
    return _principled(name, (0.700, 0.690, 0.665), 0.50)


def glass(name: str = "glass") -> bpy.types.Material:
    """Opaque dark glass rather than real transmission.

    Refractive glass would mean tracing into every interior we have not built,
    at a cost this CPU-only budget cannot carry. A dark, glossy, slightly blue
    surface reads correctly from the street and renders for almost nothing.
    """
    material = _principled(name, (0.035, 0.042, 0.052), 0.08)
    bsdf = material.node_tree.nodes["Principled BSDF"]
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.85
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.15
    return material
