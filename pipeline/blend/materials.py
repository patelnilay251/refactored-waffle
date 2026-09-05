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


def weathered_wall_material(osm_material: str | None, osm_id: int,
                            cache: dict) -> bpy.types.Material:
    """As `wall_material`, but with procedural drift, streaking and relief."""
    from . import textures

    tone = OSM_MATERIAL.get((osm_material or "").lower())
    if tone is None:
        tone = UNTAGGED_MIX[osm_id % len(UNTAGGED_MIX)]

    key = f"weathered_{tone}"
    if key not in cache:
        colour, roughness = WALL_TONES[tone]
        # Stone and stucco streak more visibly than brick: the dirt sits on a
        # pale ground instead of blending into it.
        streak = 0.46 if tone in ("portland_stone", "stucco") else 0.34
        cache[key] = textures.weathered_wall(key, colour, roughness,
                                             streak=streak)
    return cache[key]


def _foliage_material() -> bpy.types.Material:
    """Leaf canopy.

    The geometry is clumps of coarse spheres, and smooth shading alone leaves
    them reading as exactly that. High-frequency noise on both colour and
    normal breaks the surface up so the eye stops resolving individual clumps
    and sees a mass instead — the cheapest available substitute for leaf
    cards, which is what this really wants.
    """
    from . import textures

    material = bpy.data.materials.new("prop_foliage")
    tree = textures._tree(material)
    bsdf = tree.nodes["Principled BSDF"]

    coords = textures._object_coords(tree, (1.0, 1.0, 1.0))
    speckle = textures._noise(tree, coords.outputs["Vector"], scale=42.0,
                              detail=8.0, roughness=0.75)

    tone = tree.nodes.new("ShaderNodeMixRGB")
    tone.inputs["Color1"].default_value = (0.030, 0.052, 0.019, 1.0)
    tone.inputs["Color2"].default_value = (0.094, 0.138, 0.052, 1.0)
    tree.links.new(speckle.outputs["Fac"], tone.inputs["Fac"])
    tree.links.new(tone.outputs["Color"], bsdf.inputs["Base Color"])

    bump = tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.85
    bump.inputs["Distance"].default_value = 0.06
    tree.links.new(speckle.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    bsdf.inputs["Roughness"].default_value = 0.78
    # Leaves are thin: without some transmission a crown renders as a solid
    # dark mass, and the backlit glow is most of what says "tree".
    for socket in ("Transmission Weight", "Subsurface Weight"):
        if socket in bsdf.inputs:
            bsdf.inputs[socket].default_value = 0.16
            break
    return material


def prop_materials() -> dict[str, bpy.types.Material]:
    """Materials for rooftop clutter and street furniture."""
    foliage = _foliage_material()

    return {
        "brick": _principled("prop_brick", (0.196, 0.148, 0.112), 0.88),
        # Chimney pots are unglazed terracotta and read warm even in shade -
        # a useful spot of colour along an otherwise grey roofline.
        "terracotta": _principled("prop_terracotta", (0.315, 0.152, 0.088), 0.80),
        "metal": _principled("prop_metal", (0.105, 0.107, 0.108), 0.44),
        "bark": _principled("prop_bark", (0.148, 0.132, 0.108), 0.90),
        "foliage": foliage,
        "timber": _principled("prop_timber", (0.152, 0.102, 0.062), 0.78),
        # Post Office red, which is a deep crimson rather than a bright red.
        "postbox_red": _principled("prop_postbox", (0.288, 0.028, 0.030), 0.52),
        "canvas": _principled("prop_canvas", (0.086, 0.118, 0.096), 0.86),
    }


def road_paint(name: str, colour: tuple[float, float, float]) -> bpy.types.Material:
    """Thermoplastic road marking.

    Deliberately not bright. Road paint on a live carriageway is worn, dirty
    and part-covered; pure white lines read as freshly laid and pull the eye
    straight to the tarmac, which is not where it should go.
    """
    return _principled(name, colour, 0.62)


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
