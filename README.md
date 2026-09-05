# refactored-waffle

Procedural photoreal render of a real London block, built from open geodata.

Target site: **Berwick Street / Broadwick Street, Soho** — a 200 × 200 m
extract, rendered at street level in Blender/Cycles.

## Why Soho

Choice of site was made on measured OSM tag coverage across central London,
not on vibes:

| District | Buildings | Height data | Roof shape | Material | Named |
|---|---|---|---|---|---|
| **Soho** | 509 | 62% | 1% | **46%** | 47% |
| Canary Wharf | 34 | 70% | 17% | 11% | 50% |
| Shoreditch | 203 | 58% | 1% | 8% | 32% |
| Westminster | 52 | 51% | 5% | 17% | 26% |
| South Bank | 18 | 50% | 16% | 16% | 66% |
| City / Bank | 69 | 40% | 7% | 20% | 33% |

Soho wins on `building:material` tagging — the rarest and most useful tag for a
material pass — and its low-rise terraced stock suits a street-level camera,
which keeps the weakly-tagged roofs out of frame.

## Data sources

| Layer | Source | Notes |
|---|---|---|
| Footprints, heights, roads | OpenStreetMap via Overpass | mirrors in `pipeline/osm.py` |
| Imagery | Esri World Imagery | reachable, unauthenticated |

Deliberately **not** used, having been probed and ruled out:

- **EA National LiDAR** (25 cm–2 m DSM/DTM, free under OGL) would give exact
  heights and real roof geometry. Its WMS serves only coverage-extent index
  layers; there is no WCS, the ArcGIS ImageServer route returns `Invalid URL`,
  and bulk access is via an interactive portal. Not scriptable.
- **OS OpenData** — OpenMap Local has footprints but no heights; Terrain 50 is
  50 m resolution. Heights live in the licensed MasterMap Building Height
  Attribute.
- **Google Photorealistic 3D Tiles / Cesium ion** — both require API keys.

## Heights

Only ~62% of buildings carry `height` or `building:levels`. The rest are
inferred, in priority order:

1. `height` tag, unit-parsed (metres or feet)
2. `building:levels` × a per-class floor model (taller ground floor, parapet)
3. **Terrace neighbours** — buildings within 1.5 m share a party wall, and in
   London they share a cornice line too, so the median neighbour height is a
   strong prior
4. Nearby streetscape within 30 m
5. Building-type default

Every building records a `height_source`, so inferred geometry stays auditable.
On the current site nothing reaches step 5:

```
tag:levels          130   68%
inferred:terrace     46   24%
inferred:nearby      13    6%
```

## Overlapping footprints

OSM permits building outlines to overlap, and four pairs here did — two of them
by over 80 m², i.e. the same building mapped twice. Extruded as-is that makes
two solids sharing a volume, and because a building often *inherits* its
neighbour's height during inference, the roof caps land exactly coplanar and
Cycles z-fights them into black holes.

`resolve_overlaps` clips each footprint against the larger ones already
accepted and drops whatever barely survives. All four pairs here were true
duplicates: 4 dropped, 0 clipped, and near-black artifact pixels went from
8,596 to 0.

## Usage

```bash
pip install bpy shapely matplotlib
python3 -m pipeline.stage1_data      # fetch, project, resolve heights
python3 -m pipeline.preview          # render the QA preview
python3 -m pipeline.stage2_massing   # extrude and clay-render
```

Overpass responses are cached under `data/cache/` by query hash; re-runs do not
re-hit the API.

## Layout

```
config/soho.json           site definition (centre, extent)
pipeline/geo.py            lat/lon <-> local metres
pipeline/osm.py            Overpass client, mirror fallthrough, cache
pipeline/heights.py        height resolution and inference
pipeline/stage1_data.py    stage 1 -> data/soho/scene.json
pipeline/preview.py        QA preview -> out/
pipeline/blend/mesh.py     footprint extrusion, ground
pipeline/blend/materials.py clay shaders
pipeline/blend/shot.py     cameras, sun, world, render settings
pipeline/stage2_massing.py stage 2 -> out/stage2_*.png
```

Coordinates downstream of `stage1_data` are **local metres**, +X east, +Y north,
origin at the site centre.

## Stages

- [x] **1 — Data layer.** Fetch, reproject, resolve heights, QA preview.
- [x] **2 — Massing.** LOD1 extrusion, overlap resolution, clay render from an
      overview and from eye height on Berwick Street.
- [ ] 3 — Roads and ground. Centreline buffering, junctions, footways.
- [ ] 4 — Facades. Procedural bays, windows, shopfronts, cornices.
- [ ] 5 — Clutter and materials.
- [ ] 6 — Lighting, atmosphere, hero render, grade.

## Environment

Renders on CPU — no GPU available. Cycles, 4 cores. This is the binding
constraint on the project and the reason the site is one block rather than a
skyline.
