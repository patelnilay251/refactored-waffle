"""Stage 6 - hero render.

Everything from stage 5, at final quality: more samples, physical defocus,
denser haze so the sun actually shows in it, a compositor grade, and a film
post-process.

    python3 -m pipeline.stage6_hero [data/soho/scene.json] [--draft]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import bpy

from . import clutter, post, stage5_dressing
from .blend import grade, shot

ROOT = Path(__file__).resolve().parent.parent

# A little thicker than stage 5 for depth, but shadow rays still skip it.
#
# Letting them cross the volume was tried, to have buildings shadow the haze
# into visible shafts, and it cost the key light exactly as an oversized box
# did in stage 5: warm-lit pixels went from 14.1% to 0.0%. It would not have
# bought anything anyway. A shaft needs sun actually entering the volume the
# camera is looking through, and at 23.8 degrees elevation with the sun 40
# degrees off the street's axis it never enters this canyon at all. The
# geometry rules the effect out before the render cost does.
HERO_HAZE = 0.00026

FOCUS_M = 34.0
FSTOP = 5.6


def main(argv: list[str]) -> int:
    draft = "--draft" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]
    scene_path = Path(args[0]) if args else ROOT / "data" / "soho" / "scene.json"
    scene_data = json.loads(scene_path.read_text())
    out_dir = ROOT / "out"

    # 256 with denoising is clean at 1080p here; past that the extra samples
    # buy less than the extra hour costs on four CPU cores.
    samples = 48 if draft else 256
    resolution = (960, 540) if draft else (1920, 1080)

    print(f"site      : {scene_data['description']}")
    print(f"quality   : {samples} samples at {resolution[0]}x{resolution[1]}"
          f"{'  (draft)' if draft else ''}")

    stage5_dressing.reset()
    started = time.time()
    built = stage5_dressing.build(scene_data)

    # Replace stage 5's haze with the slightly denser hero version.
    if (existing := bpy.data.objects.get("atmosphere")) is not None:
        bpy.data.objects.remove(existing, do_unlink=True)
    shot.atmosphere(density=HERO_HAZE, span=1800.0, height=550.0)
    bpy.context.scene.cycles.volume_bounces = 2

    print(f"built     : in {time.time() - started:.1f}s")
    print(f"sun       : {built['sun'].describe()}")
    print(f"clutter   : {clutter.summarise(built['props'])}")

    shot.configure_render(samples=samples, resolution=resolution,
                          exposure=stage5_dressing.EXPOSURE)
    grade.apply()

    centreline = shot.find_street(scene_data, stage5_dressing.HERO_STREET)
    cameras = []
    if centreline:
        hero = shot.street_camera(centreline, lens_mm=26.0, rise=16.0,
                                  along=0.16, look_ahead=0.58)
        shot.depth_of_field(hero, FOCUS_M, FSTOP)
        cameras.append(("hero", hero))
    cameras.append(("overview", shot.overview_camera(scene_data)))

    for label, camera in cameras:
        raw = out_dir / "tmp" / f"stage6_{label}_raw.png"
        raw.parent.mkdir(parents=True, exist_ok=True)
        started = time.time()
        shot.render_to(raw, camera)
        elapsed = time.time() - started

        final = out_dir / f"stage6_{scene_data['name']}_{label}.png"
        post.process(raw, final,
                     vignette_strength=0.20 if label == "hero" else 0.12,
                     grain_amount=0.012)
        print(f"rendered  : {final.name} in {elapsed / 60:.1f} min")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
