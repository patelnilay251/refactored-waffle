"""Final post-process on the saved frame.

Vignette and grain are done here in numpy rather than in the compositor. Both
are properties of the film and the lens barrel rather than of the light in the
scene, so they belong after the render, and doing them outside Blender keeps
them trivially tweakable without re-rendering.

Grain matters more than it looks. A perfectly clean image reads as synthetic
almost regardless of how good the lighting is; a little correlated noise is
one of the cheapest realism cues available.

    python3 -m pipeline.post in.png out.png
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image


def vignette(image: np.ndarray, strength: float = 0.22,
             falloff: float = 2.4) -> np.ndarray:
    """Darken toward the corners, as a real lens does."""
    height, width = image.shape[:2]
    y, x = np.ogrid[:height, :width]
    # Normalised radius, 0 at centre and 1 at the corners.
    cx, cy = (width - 1) / 2, (height - 1) / 2
    radius = np.sqrt(((x - cx) / cx) ** 2 + ((y - cy) / cy) ** 2) / np.sqrt(2)
    mask = 1.0 - strength * np.clip(radius, 0, 1) ** falloff
    return image * mask[..., None]


def grain(image: np.ndarray, amount: float = 0.012, seed: int = 7,
          chroma: float = 0.35) -> np.ndarray:
    """Film grain, stronger in the midtones and mostly luminance.

    Real grain vanishes in the blacks and the blown highlights, so the noise
    is weighted by a curve that peaks around mid grey. Chroma noise is kept
    low: colour speckle reads as sensor noise, not film.
    """
    rng = np.random.default_rng(seed)
    luma = image.mean(axis=2, keepdims=True)
    # Peaks at 0.5, falls to zero at both ends.
    weight = 4.0 * luma * (1.0 - luma)

    mono = rng.normal(0.0, 1.0, image.shape[:2] + (1,))
    colour = rng.normal(0.0, 1.0, image.shape)
    noise = mono * (1.0 - chroma) + colour * chroma
    return image + noise * amount * weight


def process(source: Path, destination: Path, *, vignette_strength: float = 0.22,
            grain_amount: float = 0.012) -> Path:
    image = np.asarray(Image.open(source).convert("RGB"), dtype=np.float32) / 255.0
    image = vignette(image, vignette_strength)
    image = grain(image, grain_amount)
    image = np.clip(image, 0.0, 1.0)

    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((image * 255.0 + 0.5).astype(np.uint8)).save(destination)
    return destination


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    out = process(Path(argv[1]), Path(argv[2]))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
