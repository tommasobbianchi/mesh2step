# Findings — p14 valid in memory, invalid after STEP (mechparts/14)

Second-opinion investigation. All measurements reproduced with system `python3` (OCP
**7.9.3.1** — note: task said 7.8; the bindings report 7.9.3.1, so OCCT source cited from
GitHub `V7_8_0` tag matches logic but line numbers may differ slightly from the linked
library).

## TL;DR

The 25 faces that become `BRepCheck_UnorientableShape` after STEP re-read are **sliver /
shelf faces at the level junctions** (z = 127, 635, 762, 889). Their wire geometry survives
STEP **bit-for-bit** (3D curves, pcurves, parameter ranges, plane, vertex positions and
tolerances are all identical before/after). What changes is **the order of edges inside each
wire** — the STEP reader reorders them — and that reordering tips OCCT's
`BRepCheck_Wire::SelfIntersect` (domain-based circular-pcurve intersection) into a
false-positive `BRepCheck_SelfIntersectingWire`, which cascades to `UnorientableShape`.

The "near-equal ring faces" (55 thin annuli) are **not** the invalid faces: the invalid set
is 23 single-wire slivers + 2 multi-wire shelves, all with **near-coincident circular arcs**
in their boundary (e.g. R=813.0078 vs R=812.7787, centres 0.8 mm apart).

No post-processing tool fixes it (see "Fix attempts" below). The fix belongs in the builder.

---

## Q1 — What is lost in STEP translation?

**Nothing geometric is lost. Only the wire edge order changes.**

Per-face before/after comparison of the first invalid face (area 861818, z=889, face idx 2)
— all values identical in memory (`p14_mem.brep`) and re-read (`diag.step`):

| property | MEM | RR (after STEP) |
|---|---|---|
| face orient | FORWARD | FORWARD |
| plane loc | (2869.790047, 8748.706917, 888.999537) | identical |
| plane normal | (0,0,0,1) | identical |
| wire0 edge order (by UV start) | e0,e1,e2,e3,e4,e5 | e0,e5,e4,e3,e2,e1 |
| each edge pcurve type/range | Geom2d_Circle, identical | identical |
| each edge UVPoints | identical | identical |
| vertex pos + tol | identical | identical |

So the reader reorders wire0's edges into **traversal order** (memory stores them in a
non-traversal order left behind by the fuse). The wire's `BRepCheck` status goes:

- MEM wire0: `BRepCheck_NoError`
- RR wire0: `BRepCheck_SelfIntersectingWire`

`BRepCheck_Analyzer` then turns any wire error into face-level `UnorientableShape`
(`src/BRepCheck/BRepCheck_Analyzer.cxx` — `SetUnorientable()` is called when the wire-level
check reports anything other than `NoError`; in `V7_8_0` that is around the face branch that
calls `aFaceRes->OrientationOfWires()` / `aFaceRes->SetUnorientable()`).

`BRepCheck_Wire::SelfIntersect` (`src/BRepCheck/BRepCheck_Wire.cxx:990`) detects the problem
via `Geom2dInt_GInter` on the **pcurves restricted to per-edge domains built from
`BRep_Tool::UVPoints` + `CurveOnSurface` ranges**. I reproduced this domain-based intersection
(`IntRes2d_Domain(p1, f1, 1e-10, p2, l1, 1e-10)`):

- MEM wire0 → 5 intersections (3 point + 2 segment), all at shared vertices → tolerated.
- RR wire0 → 2 intersections (segments) → **not** tolerated → `SelfIntersectingWire`.

The near-coincident arcs are the trigger: consecutive edges in these wires are arcs of
**nearly identical circles** (e.g. edge1 `CIRCLE c=(2869.64,9384.98) R=813.0078`, edge2
`CIRCLE c=(2870.27,9385.22) R=812.7787`), i.e. two ~0.23 mm-offset circles sharing a vertex.
That near-coincidence is exactly what the reordered-wire domain intersection mis-reads as a
self-intersection.

### Why near-coincident arcs exist

The builder fuses level prisms whose outlines are traced from **different slice heights**, so
neighbouring levels' outlines differ by ~0.1–1 mm. The fuse exposes a thin shelf/sliver
bounded by one arc from each level — two nearly-identical circles. This is the physical
"step" between levels, so it is real geometry, not a defect per se — but its representation
does not survive a STEP round trip.

---

## Q2 — Do the near-equal ring faces cause the invalid faces? No.

Wire census of the valid in-memory shape confirms the task's measurement: 166 cylinder
faces (1 wire), 75 planar 1-wire, 56 planar 2-wire, 3 planar 8/10/20-wire.

But the **25 invalid faces are a different set** — mostly 1-wire, not 2-wire:

```
invalid (area, z, #wires, #edges):  (full list in diag4.out)
  6779647  z=762  8 wires 26 edges   <- the "6.78e6, 26 edges" face
  861818   z=889  2 wires  7 edges
  201.43   z=635  1 wire   6 edges
  164.52   z=127  1 wire   6 edges
  137.11   z=127  1 wire   4 edges
  ... 19 more 1-wire slivers (area 0.04 .. 129) at z=127/635/762 ...
```

23 of 25 are **single-wire** sliver/lens faces (2, 4 or 6 circular-arc edges). The 55 thin
annuli (2-wire) mostly **survive** STEP; only the two multi-wire shelves (861818, 6779647)
and the single-wire slivers fail. So the near-equal ring faces and the invalid faces are two
symptoms of the same root cause (fuse of near-identical outlines) rather than cause and
effect. The task's measurement 3 implicitly links them, but they are distinct faces.

---

## Q3 — The fix

### What I tested (all still 25 invalid after STEP re-read)

- `ShapeFix_Shape` (default; `SetMaxTolerance` 0.01/0.1/0.5; `FixSameParameterMode`)
- `ShapeFix_Wire` (`FixReorder`, `FixConnected`, `FixSelfIntersection`, `FixDegenerated`) per wire
- `ShapeFix_Solid` (default and `SetMaxTolerance(0.5)`)
- `BRepBuilderAPI_Sewing` (tol 1e-4 … 0.1) + `BRepBuilderAPI_MakeSolid`
- `ShapeUpgrade_UnifySameDomain` (all `unifyFaces`/`unifyEdges` combos)
- `ShapeUpgrade_ShapeDivideArea` (max area 1e4…1e6) — makes it *worse* (26)
- `BRep_Builder.UpdateVertex` tol 0.01/0.1/1.0 (2560 verts)
- write options: `write.precision.mode` 0/1/2, `write.surfacecurve.mode` 0/1/2
- schemas AP203 / AP214 / AP242
- read options: `read.precision.mode` 0/1
- translating to origin (already in the task) — 26

None change the result. `ShapeFix_Shape` applied to the **re-read** shape also fails to
repair it, so the defect is not a tolerance/self-intersection ShapeFix can undo.

### Root-cause-based fix (builder level)

The sliver faces exist because the fuse of level prisms with slightly different outlines
creates thin shelves whose boundary has **near-coincident arcs**. The two prior builder
attempts failed for a structural reason:

- *snap_loops* (reuse identical polylines across levels, `auto25g.py:55`) removes the
  near-coincidence but leaves **exactly-coincident** edges, which STEP round-trips *worse*
  (31 invalid). So "near-coincident" and "exactly-coincident" are both degenerate.
- leaving outlines unsnapped (`auto25f`) gives 25 invalid.

The clean fix is to **not let the fuse create those junction faces at all**: build the
stepped extrusion as a single multi-section solid (loft/sweep with per-level sections), or
fuse with `BOPAlgo_GlueShift` so coincident section walls are glued rather than split into
slivers. Either eliminates the near-coincident-arc faces instead of repairing them after the
fact.

A post-processing alternative that is theoretically sound but which I could not get stable in
the available time: replace the circular **arc** edges with non-periodic BSplines before the
STEP write (the periodic circle pcurve is what the domain-based self-intersection check
mis-reads). My `bspline_fix.py` prototype segfaults inside `GeomAPI_PointsToBSpline` on some
degenerate arc; it needs per-edge error handling and was left unfinished.

### Smallest verifiable statement

On `p14_mem.brep` there is **no** shape-healing or STEP-write option that yields a valid
re-read while keeping all 166 cylinder faces; the defect must be removed at construction
time (single multi-section prism, or glue-fuse). This is the one claim I could not reduce to
a verified one-liner, and I flag it as such.

---

## Reproducer files (all under `SEM/kimi14/`)

- `diag.py` / `diag2.py` / `diag4.py` — face/wire status + edge/vertex dump, MEM vs RR
- `diag3.py`, `diag5.py`, `diag7.py` — pcurve/range/UVPoints + domain-based intersection
- `fix_test.py` — the exhaustive fix sweep
- `bspline_fix.py` — unfinished circle→BSpline conversion (segfaults)
- OCCT sources pulled: `BRepCheck_Face.cxx`, `BRepCheck_Wire.cxx`, `BRepCheck_Analyzer.cxx`
