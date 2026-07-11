# Kernel & architecture selection

## Kernel: OCP instead of pythonocc-core

The spec asks for `pythonocc-core` (`OCC.Core`). This host has no `conda`/`mamba` and
`pythonocc-core` has no PyPI wheel — it is conda-forge-only (confirmed: `pip install
pythonocc-core` fails with no matching distribution). `2STEP-Converter`'s own README
independently confirms this: its launcher spends 5-15 min and ~500 MB pulling
`pythonocc-core` from conda-forge via a bundled micromamba, specifically because no pip
path exists.

**`cadquery-ocp` (import name `OCP`) was already installed on this host** (used by
`cadquery`). It wraps the *same* OpenCASCADE Technology (OCCT 7.8.1) as
`pythonocc-core`, via pybind11 instead of SWIG, with near-identical class names
(`OCP.BRepBuilderAPI.BRepBuilderAPI_MakeFace` vs `OCC.Core.BRepBuilderAPI.
BRepBuilderAPI_MakeFace`). It is pip-installable, actively maintained (backs
`build123d`/`CadQuery`), and required zero environment setup here. Every reference to
"the OCCT kernel" below and in the code uses `OCP`; swapping to `OCC.Core` later is a
mechanical import-name change, not a redesign — the two bindings are call-compatible for
everything this tool uses.

## The four references

### 1. `slugdev/stltostp` (C++, no OCCT)

Hand-writes STEP entities as C++ classes (`Point`, `EdgeCurve`, `Face`, `Shell`, ...)
with their own `serialize()`/`parse_args()` — a from-scratch STEP-21 text emitter, zero
CAD-library dependency.

- **Good idea**: builds an `edge_map` up front (`create_edge_curve` cached by endpoint
  coordinates) so a shared mesh edge becomes one `EDGE_CURVE` referenced by both
  triangles' loops, not two. This is the right instinct — construct sharing at
  build time, don't rely on a later pass to rediscover it.
- **Bug in that instinct**: the map key is `std::tuple<double,...>` compared by exact
  float equality, not a tolerance-quantized bucket. The `tol` parameter is used
  *only* to reject near-zero-length edges/degenerate triangles, never to snap two
  independently-computed "same" vertices together. The README's claim of
  "tolerance-based edge merging" oversells this. It happens to work on STL because
  each STL triangle repeats its vertex floats verbatim (no shared indices in the
  format) and identical geometry gets bit-identical mesh generator output — but any
  precision drift (mixed-precision export, float32→float64 round trip, a second
  mesh source) breaks the match silently and re-splits the edge.
- **Bigger gap**: `build_tri_body` always constructs an `OPEN_SHELL` /
  `SHELL_BASED_SURFACE_MODEL`. There is no closed-shell path, no manifold check, no
  `SOLID` ever emitted — even for a perfectly watertight cube. It cannot satisfy
  "watertight input ⇒ closed solid."
- No merge-coplanar, no batch mode, no formats beyond STL, minimal STEP header
  (no `PRODUCT`/`SHAPE_DEFINITION_REPRESENTATION` wrapper for AP203, a partially-built
  one for AP214) — a genuinely tiny, dependency-free proof of concept, not a
  production path.

### 2. `yaneony/2STEP-Converter` (Python + pythonocc-core)

The most complete reference: multi-format (STL/3MF/OBJ/AMF/IGES), batch mode, a real
CLI, subprocess-isolated OCCT stages (a crash in `Sewing`/`ShapeFix` doesn't kill the
whole run), timing-based ETA, PNG previews.

Pipeline: parse → `open3d`/numpy cleanup → (optional decimate) → round-trip through a
**temp STL file** read back via `StlAPI_Reader` → `BRepBuilderAPI_Sewing` →
`ShapeFix_Shape` → `ShapeUpgrade_UnifySameDomain` → `STEPControl_Writer`.

- **Good idea**: separates "clean the mesh" (`_clean_mesh_arrays`, vertex dedup +
  degenerate-triangle drop) from "build the shape" from "sew" from "fix" from "merge
  co-planar" from "write" — a legible staged pipeline, and it genuinely mirrors what
  FreeCAD's own Part workbench does.
- **Gap 1 — conflated/hidden tolerances, the exact #20455 shape**: `_clean_mesh_arrays`
  hardcodes vertex dedup at `np.round(verts, 6)` — a fixed, invisible tolerance never
  exposed on the CLI. The user-facing `--tolerance` flag only ever reaches
  `BRepBuilderAPI_Sewing(tolerance)`. Two tolerances exist, which is *better* than
  FreeCAD's single overloaded parameter, but the dedup one is undocumented and
  unconfigurable — a user who loosens `--tolerance` to fix a sewing failure has no
  way to know the upstream dedup never moved.
- **Gap 2 — merge-coplanar is not optional.** `ShapeUpgrade_UnifySameDomain` runs
  unconditionally in the "refining" step of every conversion. There is no faceted
  (one face per triangle) output mode at all — this tool cannot do what the task
  calls the exact/geometry-preserving baseline.
- **Gap 3 — indirect shape construction.** `_mesh_to_shape` never builds B-Rep faces
  from the in-memory triangle arrays; it re-serializes them to a temporary binary STL
  and hands that to `StlAPI_Reader`, so the actual "triangle → planar face" step
  happens inside OCCT's STL importer, opaquely, and topology sharing is whatever that
  importer + the subsequent `BRepBuilderAPI_Sewing` pass produce — not something the
  tool controls or can report on (no explicit watertight/open-shell flag is ever
  computed; the README documents the open-shell *symptom* as a troubleshooting note,
  not a structured result).

### 3. `miho/OCC-CSG` (C++, OCCT)

`importSTL()` reads via `RWStl::ReadFile` into a `Poly_Triangulation` — which *already
has deduplicated, indexed nodes* (`aSTLMesh->Node(n1/n2/n3)`) — and then throws that
away: for every triangle it calls `BRepBuilderAPI_MakeVertex` three times from scratch,
builds an independent wire/face, and relies entirely on a subsequent
`BRepBuilderAPI_Sewing` pass to rediscover which of those thousands of freshly-made
vertices are geometrically the same point.

This is precisely the anti-pattern the task brief calls out ("do NOT emit unique
vertices per triangle and rely on a sewing tool to reconstruct sharing afterward").
It is a clean, currently-shipping example of what *not* to do: `Poly_Triangulation`
handed it a node-index → point map for free, and it never used the index, only the
point, so sewing has to redo O(n log n) (or worse — sewing is documented by OCCT devs
as having near-quadratic edge-matching behavior on dense meshes) coincidence detection
that indexed construction would have made unnecessary.

### 4. FreeCAD `Part.Shape.makeShapeFromMesh` + issue #20455

The canonical one-liner: `shape.makeShapeFromMesh(mesh.Topology, tol)` then
`Part.makeSolid(shape)`. Internally this is architecturally the same family as
OCC-CSG's `importSTL` (per-facet face construction + sew at a single `tol`).

Issue #20455 documents the resulting trap precisely: `tol` is labeled "sew tolerance"
and documented as "usually not needed," but it is really the *only* geometric
tolerance the whole pipeline gets — leaving it at the near-zero OCCT default means
vertices from adjacent triangles are never recognized as coincident, so a *later*,
conceptually unrelated "Refine shape" (`ShapeUpgrade_UnifySameDomain`) pass silently
fails to merge triangles into planar faces on an object as simple as an imported cube.
Users burn hours concluding "Refine Shape never helps" (a verbatim comment on the
issue) without realizing the actual defect is upstream, at import time, under a
different, misleadingly-named control.

The lesson for us is not "add more tolerance parameters" — it's the opposite: **a
merge/refine step's quality is only as good as the dedup tolerance the shape was built
with, so that dependency must be explicit, not buried under an unrelated step's
setting.**

The mesh's own alternate recipe in the same doc (`getPlanarSegments` → group facets by
angle → `MeshPart.wireFromSegment` → `Part.Face(wires)`) is a "recognize structure
first, then build filled faces with holes" strategy — architecturally different from
build-then-unify. Noted as a possible alternate `--merge-coplanar` strategy, not needed
for this tool's MVP (`ShapeUpgrade_UnifySameDomain` post-build is sufficient and is what
2STEP-Converter and FreeCAD's own "Refine shape" both use).

## Decision: new implementation, synthesizing the above

Not extending any single reference — `stltostp` can't produce solids at all,
`2STEP-Converter` can't produce a pure faceted mode and hides a tolerance,
`OCC-CSG`/FreeCAD's core routine both build-then-sew instead of building-shared.
None of the four is a sound base; the useful parts (staged pipeline legibility from
#2, edge-cache instinct from #1, `RWStl`'s indexed nodes from #3, the "one tolerance,
one job" lesson from #4) recombine cleanly into a new, small implementation:

1. **Dedup up front, spatially, by quantization** — `round(coord / tol)` integer
   keys via `numpy.unique`, done once, before any OCCT object exists. This is the
   fix for `stltostp`'s exact-match fragility and `OCC-CSG`'s wasted indexed data.
2. **Build shared topology directly**: one `TopoDS_Vertex` per unique (deduped) node,
   one `TopoDS_Edge` per unique (unordered) vertex-index pair, cached and reused by
   every triangle that touches it. A triangle's face is three (possibly-reversed)
   cached edges → wire → plane-fitted face (`BRepBuilderAPI_MakeFace(wire)`, letting
   OCCT least-squares-fit the plane the way `OCC-CSG` does, rather than hand-deriving
   a csys the way `stltostp` does — no reason to hand-roll that math).
3. **No `BRepBuilderAPI_Sewing` in the default path at all.** Because topology is
   shared by construction, sewing has nothing left to do — the tool's own edge-usage
   counts (built for free while caching edges) directly answer "is this watertight":
   every edge used by exactly 2 triangles ⇒ closed manifold ⇒ wrap `TopoDS_Solid`;
   any edge used by 1 (boundary) or ≥3 (non-manifold) ⇒ report a compound/shell and
   say why, never silently fake a solid. This sidesteps the dedup-vs-sew conflation
   (#20455's actual root cause) by removing the second, ambiguous use of the
   tolerance rather than trying to keep two uses of it straight.
4. **Merge-coplanar stays a separate, explicit, off-by-default stage** —
   `ShapeUpgrade_UnifySameDomain` applied only under `--merge-coplanar ANGLE_DEG`,
   with its own linear tolerance (defaults to `--tolerance`, independently
   overridable) — never on the default/faceted path, unlike `2STEP-Converter`.
