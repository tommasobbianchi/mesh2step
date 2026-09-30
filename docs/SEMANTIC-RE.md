# Semantic reverse engineering: VLM → LLM → exact build

Status: design, 2026-09-30. Owner's brief: find an economical, fast pipeline where a vision model describes the part
semantically and a language model deconstructs it (fillets/chamfers → holes/cuts → extrusions → base sketches →
sketch shapes) **without calculations**; small measurements only confirm proportions. **No brute-force methods.**

## Why a change of approach

Everything built so far recognises geometry by agreement or by search, and the results say so:

- **Exact agreement** (engine, edgebuild, feature builders): planes to 1e-5 of the diagonal, exact circles. Real
  CAD exports pass; every scan and remesh fails. All 4 of the owner's real-world files came back as one planar face
  per triangle (2026-09-29).
- **Noise-tolerant fitting** (denoise.py, scanbuild.py, branch feat/scan-oc): recognises 36 % curved area on the
  mechpart scan, but needs a growing ladder of rules (seeds, merges, tangency, corner repair, orientation, slivers).
  Three models in a row failed to make its output valid, and one passed its gate by faceting every curved face.
- **Search** (design-history engine: hypothesis forks, cells ILP, finishing chains): hundreds of seconds per part,
  and a HiGHS presolve that ignores its time limit.

The rule count has no ceiling, because real parts vary without limit. A designer does not recover a part that way.
A designer reads it: "a flange, four bolt holes, a boss with a bore, ribs, everything filleted".

## Principle

**Models decide STRUCTURE and RELATIONS, deterministic code supplies NUMBERS.** This is already the stated contract
of tools/tree/tree.py ("the LLM and the owner decide its STRUCTURE, deterministic code fills its numbers"). This design
applies it end to end:

| Who | Does | Never does |
|---|---|---|
| VLM | names the part and its features, their placement and relations | measures anything |
| LLM | orders the deconstruction, writes sketches as shapes and relations, states proportions, asks questions | computes coordinates, fits, searches |
| Probes (code) | answer the LLM's specific questions with one number each | discover geometry on their own |
| Kernel (OCCT) | builds the tree exactly | fits anything |

## Hard constraints

1. **No brute force.** No hypothesis enumeration, no ILP/solver search, no RANSAC or region growing, no ladders of
   retry variants. If a step seems to need a search, the description is incomplete: ask a sharper question.
2. **No computation by models.** Kinds, order, relations and proportions only. Every number comes from a probe that
   answers a question the model asked.
3. **Economical.** Target cents per part: a first tree with at most 1 VLM call + 1 LLM call, each correction round
   1 VLM + 1 LLM call, at most 3 rounds. For comparison, the Opus AI rebuild costs a median of $2.59.
4. **Fast.** First tree in about 60 s wall time, each round in about 15 s.
5. **General.** No rule for one part. Judged only on sets (below).

## Pipeline

```
mesh ─► S0 triage ─► S1 look (render → VLM) ─► S2 deconstruct (LLM) ─► S3 confirm (probes)
                                                      ▲                         │
                                                      │                         ▼
                              S6 differences ◄─ S5 verify ◄─ S4 build (tree → OCCT / FreeCAD)
```

### S0 Triage (code, < 1 s)
Units and scale sanity: bbox in mm, flagging parts over 1 m or under 1 mm (the convogliatore at 4.1 m and the
universal key at 2.6 m are real cases). Bodies, watertightness, merged vertices (textured OBJs split per UV seam).
Principal axes: the frame every later stage speaks in, so "top" and "front" mean the same thing to all of them.

### S1 Look (render + VLM)
- Renderer: the existing `~/.claude/skills/deepseek-vision/scripts/render.py` (7 orthographic/iso views, mm scale bar,
  crops), extended with 1-2 **sections** through the principal axes. Sections show wall thickness, bores and
  pockets that no silhouette shows.
- **Resolution: 4 x 4 tiles per view (owner, 2026-09-30).** The DeepSeek API downsizes every image to about 800 px, and
  at that size a feature under about 1 % of the part's extent is not in the image at all. So each view is rendered at
  3200 x 3200 and sent as **16 tiles of 800 x 800** (a small overlap, so no feature is cut in half at a seam), plus
  the whole view at 800 px for orientation. Every tile carries a burned-in label: view id, row/column, and the mm
  range it covers in the S0 frame, so the model can say where a feature is ("PZ r2c3") and S3 can turn that into
  coordinates. At 150 mm that is about 0.05 mm per pixel, 16x finer than one 800 px image. Sections are tiled the same
  way.
- Cost of the first look: 7 views x (16 tiles + 1 overview) = 119 images. That is the price of seeing everything
  once. Later rounds send only the tiles and crops around S5's differences, never all 119 again. Cost per look is a
  measured metric of the bake-off.
- VLM output, **Inventory** (strict JSON):
  ```json
  {"part": "flange", "function": "bearing housing", "base": {"kind": "plate", "plane": "XY", "outline": "square, chamfered corners"},
   "features": [
     {"id": "B1", "kind": "boss", "on": "base top", "shape": "cylinder", "relation": "centered", "confidence": 0.9},
     {"id": "H1", "kind": "through-hole", "count": 4, "pattern": "square", "relation": "near corners", "confidence": 0.8},
     {"id": "P1", "kind": "pocket", "count": 6, "relation": "between ribs", "confidence": 0.6},
     {"id": "R1", "kind": "fillet", "where": "all rib roots", "confidence": 0.5}],
   "symmetry": ["mirror X", "mirror Y"], "unsure": ["lettering on pockets: embossed or engraved?"]}
  ```
  `unsure` is a first-class answer. Measured limits of deepseek-v4-flash-vision: reliable at naming a part and reading
  its gross topology; "has cylindrical faces" right on only 6/10 parts; designed polygons called cylinders on 12/26
  (skill VALIDATION.md). So the Inventory is a hypothesis for the LLM, not a fact.

### S2 Deconstruct (LLM)
Input: Inventory + the S0 frame. Output, the **Plan**:
1. The undo order: finishes (fillets, chamfers) → subtractive features (holes, cuts, pockets, slots) → additive
   features (bosses, ribs) → the base body, down to its sketch.
2. Every sketch as **shapes and relations**, from a closed vocabulary: rectangle, rounded rectangle, circle, slot,
   regular polygon, polyline; concentric, symmetric about, tangent, equal, pattern (linear, circular, square), mirror.
3. **Named parameters with stated proportions**: "boss D ≈ 0.55 × plate width", "4 holes d, pitch p ≈ 0.8 × width".
4. **Questions**: which parameters need a probe, each phrased as a probe call (S3).

The Plan compiles to the existing tree format (tools/tree/tree.py: pad/pocket/revolve with sketch loops,
round/chamfer), so nothing new is needed to build it.

### S3 Confirm (probes, deterministic, milliseconds each)
A **closed toolbox** of noise-tolerant measurements (medians and sections, never single vertices). Each call answers
one named parameter:

| Probe | Returns |
|---|---|
| `bbox()` | extents in the S0 frame |
| `section(axis, at)` | the section outline, simplified to lines and arcs, plus its circles (centre, diameter) |
| `diameter(near, axis)` | the diameter of the round feature nearest a point |
| `distance(a, b)` | the distance between two named features' reference points |
| `thickness(at, axis)` | wall or plate thickness through a point |
| `height(feature)` | a feature's extent along the extrusion axis |
| `count(kind, region)` | the number of holes or bosses a section shows in a region |

Budget: at most 20 probes per round. A probe that contradicts a stated proportion by more than 10 % is not silently
applied. It goes back to S2 as a question ("you said the boss is centred; the probe says it sits 8 mm off centre").
This is the only place numbers enter the pipeline.

### S4 Build (code, existing)
Plan + probe values → a sketch library (deterministic templates: rounded rect(w, h, r), bolt circle(n, d, pcd), and so
on) → tree JSON → `tree.compile_tree` (exact OCCT solid) and `fcstd.py` (editable FreeCAD PartDesign body). No fitting.

### S5 Verify (code)
Two-sided deviation between the built solid and the mesh: mesh → solid and solid → mesh, by sampling. Also volume,
validity, and the S1 renders of the built part next to the mesh. Deviation is clustered into **differences**, each
with a location in S0-frame words ("back face, lower left"), a sign (missing material / extra material), a size, and
an auto-crop.

### S6 Differences → next round
Only the differences go back: crops to the VLM ("what is here on the mesh that the model lacks?"), the VLM's answers
plus the probe data to the LLM ("amend the Plan"). Stop when the deviation is within tolerance, or after 3 rounds; the
tree is then delivered with the remaining differences listed, not hidden.

## Model roles and the bake-off

Default: **DeepSeek vision** for S1 (cheap, already wired), fed 4 x 4 tiles so its 800 px cap no longer limits
what it can see. Local **Qwen3-VL** (qwen3-vl:30b-a3b and 8b are installed on nativedev's 3090, $0 per call, dynamic
resolution with a settable pixel budget) takes the same tiles and is the zero-cost candidate. S2 needs consistent structured reasoning more than vision.
A Claude model (Sonnet 5, or Haiku 4.5 if it holds) is the leading candidate; the Opus rebuild is evidence Claude
reasons well about CAD, and one call per round keeps the cost down.

This is decided by measurement, not assumption: the same S1 and S2 prompts through DeepSeek vision, local Qwen3-VL
(3090, $0), Haiku 4.5 and Sonnet 5, scored on the sets below. Pick the cheapest model per stage that holds the score.

## Evaluation sets and metrics

- **Real-world set** (`~/corpora/realworld`): the owner's 4 files, the 6 Artec scans at 150k triangles, and the
  Collarino's Autodesk STEP as exact ground truth.
- **Graded corpus** (`~/corpora/mechparts`, 39 parts with the owner's feature-tree grades): structure agreement.

Metrics, always set-wide, never one part:
1. Share of parts whose tree builds a valid solid within tolerance (two-sided p95 deviation ≤ 1 % of the diagonal).
2. Recognition: area share by surface kind vs ground truth where it exists (Collarino), and vs the mesh otherwise.
3. Tree quality: step count, and agreement with the owner's grades (tools/tree/bench.py).
4. Cost and wall time per part, per stage.

Baseline to beat: the fitting pipeline's numbers from tools/scan_bench.py (runs/bench_base on branch feat/scan-oc).

## What exists and what is new

| Piece | Status |
|---|---|
| Renderer, 7 views + crops, VLM call | exists: deepseek-vision skill (render.py, ask.py, validate.py) |
| Tree format + exact builder | exists: tools/tree/tree.py `compile_tree` |
| FreeCAD feature tree export | exists: tools/tree/fcstd.py (valid on the corpus; part 5 fixed 2026-09-29) |
| Real-world benchmark | exists: tools/scan_bench.py (feat/scan-oc) |
| Sections in the renderer | new, small |
| Inventory + Plan schemas and prompts | new |
| Probe toolbox (7 probes) | new, small, deterministic |
| Sketch template library (Plan → loops) | new, small |
| Difference map + auto-crops | new |
| Round orchestration (≤ 3 rounds) | new |

## Milestones (each accepted on the sets, never on one part)

1. **M1 Look + deconstruct, no build.** S0-S2 on all 49 parts. Score the Inventory and Plan against the owner's grades
   and Collarino's CAD. Model bake-off for S1 and S2. Decides the models.
2. **M2 Confirm + build.** S3 probes and S4 templates; one round, no loop. Metric: valid solids within tolerance.
3. **M3 Close the loop.** S5 differences and S6 rounds (≤ 3). Metric: gain per round vs its cost.
4. **M4 Service.** Wire into the converter as a pass beside the existing ones (the upgrade-pass architecture: served
   only when it beats what the engine built), behind a flag, measured on live uploads.

## Out of scope, deliberately

Free-form surfaces (the Collarino's 75 B-spline blends, the convogliatore duct): a Plan can say "blend between boss
and plate" and the kernel can loft it, but only after M3 shows the prismatic and revolved majority works. Lettering
and logos are named and skipped (a designer would not model them as geometry).

## Risks

- **VLM misreads** (6/10 on cylinders): mitigated by S3 contradictions and S6 differences. The pipeline never trusts a
  single look.
- **Tile context**: a feature spanning several tiles is seen in pieces. The overview image and the tile labels are how
  the VLM stitches them. Measured in M1: feature recall on whole-view-only vs tiled input.
- **Hidden internal features** (blind bores, undercuts): sections in S1 and `section()` probes, not more views.
- **The LLM does arithmetic anyway**: the Plan schema only accepts named parameters and proportions; a literal
  number without a probe behind it is rejected at S4.
- **Cost creep**: rounds and probes are capped; cost per part is a reported metric from M1 on.
