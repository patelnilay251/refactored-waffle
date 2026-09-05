"""Compositor grade.

Bloom and chromatic aberration belong here rather than in a post-process on
the saved PNG, because both are physically effects on *light* and want the
render's full dynamic range: bloom driven by an 8-bit image glows off
mid-greys instead of only off genuine highlights.

Blender 5.0 moved compositing out of `Scene.node_tree` and into a
`CompositorNodeTree` datablock assigned to `scene.compositing_node_group`, and
turned the Glare node's settings from properties into input sockets. Both are
silent breaks: the old code raises AttributeError rather than misbehaving.
"""

from __future__ import annotations

import bpy


def _socket(node, name, value) -> None:
    """Set an input socket if this build has it, ignore it if not."""
    if name in node.inputs:
        try:
            node.inputs[name].default_value = value
        except (TypeError, AttributeError):
            pass


def apply(*, bloom: float = 0.06, bloom_threshold: float = 1.6,
          dispersion: float = 0.006, lift: float = 0.008,
          gain: tuple[float, float, float] = (1.02, 1.0, 0.98)) -> None:
    """Bloom, chromatic aberration and a light grade.

    Values are deliberately small. Bloom at 6% and dispersion at 0.006 are near
    the threshold of being noticeable, which is where lens artefacts belong —
    they are meant to be felt rather than seen, and dialled up they read as a
    filter rather than as a photograph.
    """
    scene = bpy.context.scene

    group = bpy.data.node_groups.new("grade", "CompositorNodeTree")
    group.interface.new_socket("Image", in_out="OUTPUT",
                               socket_type="NodeSocketColor")
    scene.compositing_node_group = group

    nodes, links = group.nodes, group.links
    render = nodes.new("CompositorNodeRLayers")
    render.scene = scene

    glare = nodes.new("CompositorNodeGlare")
    _socket(glare, "Type", "Bloom")
    _socket(glare, "Quality", "High")
    _socket(glare, "Threshold", bloom_threshold)
    _socket(glare, "Strength", bloom)
    _socket(glare, "Size", 0.55)
    _socket(glare, "Smoothness", 0.35)

    lens = nodes.new("CompositorNodeLensdist")
    _socket(lens, "Type", "Radial")
    _socket(lens, "Dispersion", dispersion)
    _socket(lens, "Distortion", 0.0)
    _socket(lens, "Fit", True)

    balance = nodes.new("CompositorNodeColorBalance")
    # A touch of lift keeps the deepest shadows off pure black, which is what
    # a real lens does through flare and veiling glare, and warms the image
    # very slightly toward the low sun.
    if hasattr(balance, "lift"):
        balance.lift = (1.0 + lift, 1.0 + lift * 0.9, 1.0 + lift * 0.6)
    if hasattr(balance, "gain"):
        balance.gain = gain

    output = nodes.new("NodeGroupOutput")

    links.new(render.outputs["Image"], glare.inputs["Image"])
    links.new(glare.outputs[0], lens.inputs["Image"])
    links.new(lens.outputs[0], balance.inputs["Image"])
    links.new(balance.outputs[0], output.inputs[0])
