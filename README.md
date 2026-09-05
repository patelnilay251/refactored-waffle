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

## Streets

OSM gives centrelines, not surfaces. Junctions are normally the hard part —
four buffered strips meeting leaves gaps or overlapping slivers — but buffering
with round joins and then unioning sidesteps it: the union *is* the junction,
and the rounding left at each corner approximates a real kerb radius.

Pavement is defined negatively. Rather than guessing a width, it is whatever
remains of the street void once the carriageway and the buildings are removed,
so a 9.5 m Soho street automatically yields the ~1.25 m pavement it really has.

Three things the data forced:

- **Berwick Street is `highway=pedestrian`** — the market street is fully
  paved with no carriageway, which the hero shot has to reflect.
- **A lane count is not a carriageway width.** Lexington Street carries
  `lanes=1` and derived 3.1 m, but on the ground it is one-way with parking
  down one side. `MIN_CARRIAGEWAY` floors lane-derived widths by road class.
- **Overpass returns whole ways**, so a road caught by the bbox arrives with
  its full geometry and ran hundreds of metres off-site. Surfaces are clipped
  to the built area grown by 14 m, so the edge follows the block's shape
  rather than cutting a straight line across every street.

Surfaces sit at a carriageway datum of z=0.010 — just proud of the ground plane
so it wins the depth test outright — with a 125 mm kerb to pavement at z=0.135.
Slabs are meshed by constrained Delaunay rather than as ngons, because the
pavement is one polygon with a hole punched for every building and Blender
ngons cannot carry holes.

## Facades

The jump from LOD1 boxes to something that reads as buildings. Two ideas carry
most of it.

**Most walls are never seen.** A terrace is a row sharing party walls, so each
wall is probed against its neighbours and only open ones get detail — 999 of
1,600 edges. Those are then split against the stage-3 street surface into 548
frontages and 451 rear elevations, and rears get plainer, sparser windows and
no shopfront or cornice. That is both how London is built and half the
geometry.

**Terraces are strikingly regular.** Storey heights diminish going up (7% per
floor), window height follows the storey, bays repeat at a fixed pitch, and
the ground floor is a shopfront rather than a shrunken version of the floors
above. Encoding those rules beats scattering identical windows over a box.

Each frontage carries a recessed reveal (the shadow is most of the effect), a
projecting stone sill, a painted fascia band over each shopfront, and a
cornice at the roofline. Wall material comes from `building:material` where
tagged, otherwise a weighted mix biased to London stock brick — the
yellow-brown one, which is what Soho is actually built from.

### Memory

This is where a city model normally explodes. Current site:

```
shell faces        86,609    unique per building, but cheap
opening instances   5,002
window meshes         135    instancing ratio 37:1
wall materials          6
unique faces       95,432    across 327 meshes
objects             5,195
```

Openings are **quantised to 15 cm** and cached, so a few thousand of them
resolve to ~135 meshes shared by linked duplicates; the residual is taken up
by a small scale on the instance so the fit stays exact. Quantising rather
than scaling one unit mesh keeps frame and glazing-bar thickness constant
instead of stretching with the opening. Glass is opaque and dark rather than
refractive — tracing into interiors we have not built is not affordable on a
CPU-only budget, and from the street it reads the same.

## Usage

```bash
pip install bpy shapely matplotlib
python3 -m pipeline.stage1_data      # fetch, project, resolve heights
python3 -m pipeline.preview          # render the QA preview
python3 -m pipeline.stage2_massing   # extrude and clay-render
python3 -m pipeline.stage3_streets   # carriageway, kerbs, pavement
python3 -m pipeline.stage4_facades   # bays, windows, shopfronts, cornices
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
pipeline/streets.py        centrelines -> carriageway and pavement polygons
pipeline/stage3_streets.py stage 3 -> out/stage3_*.png
pipeline/facades.py        bay/storey layout, opening rectangles
pipeline/blend/facade.py   facade meshing, window instancing
pipeline/stage4_facades.py stage 4 -> out/stage4_*.png
```

Coordinates downstream of `stage1_data` are **local metres**, +X east, +Y north,
origin at the site centre.

## Stages

- [x] **1 — Data layer.** Fetch, reproject, resolve heights, QA preview.
- [x] **2 — Massing.** LOD1 extrusion, overlap resolution, clay render from an
      overview and from eye height on Berwick Street.
- [x] **3 — Streets.** Centreline buffering, junction union, kerbs, pavement.
- [x] **4 — Facades.** Bays, recessed windows, sills, shopfronts, fascias,
      cornices; wall material from OSM tags; instanced openings.
- [ ] 5 — Clutter and materials.
- [ ] 6 — Lighting, atmosphere, hero render, grade.

## Environment

Renders on CPU — no GPU available. Cycles, 4 cores. This is the binding
constraint on the project and the reason the site is one block rather than a
skyline.
