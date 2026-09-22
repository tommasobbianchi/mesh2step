# Reconstruction errors: evidence base for the recon toolbox

Compiled 2026-09-22, read-only. It collects every reconstruction error observed in mesh2step and in
its predecessor alphaevolve, with root cause and fix, so each one can become a toolbox function
(`tools/recon/recon_tools.py`, `rt`), a decision-tree rule (`tools/recon/junction_tree.py`), or a
guard in the loop or gate. Vocabulary is from `docs/JUNCTIONS.md`: junction `a|b|curve|state`, blend
`blend:kind|a+b|round/fillet`. Inside tables `|` is written `\|`.

**Source prefixes** (the source column always starts with one of these):
- `RL:` is the reflective loop, `tools/recon/runs/opus_2026-09-21/recon2_<part>/history.json`, round N
  (`rN`; `r1->r2` means round 2 fixed round 1). The feedback the model saw is the round's `report` JSON
  plus the fixed template in `tools/recon/recon_loop.py` (~l.395). No separate feedback text is stored.
- `MS:` is mesh2step. A 7-hex sha is a commit. `mem:<file>` is
  `~/.claude/projects/-home-tommaso-projects-mesh2step/memory/<file>`. `LS/` is `.claude/loopspec/`,
  `FR/` is `tools/feature_recon/`, `RS/` is `refs/stl2step/`, `rb` is the native engine's
  `refit_build.cpp`. `Forgetful #n` is a Forgetful memory id.
- `AE:` is alphaevolve, paths relative to `/home/tommaso/projects/alphaevolve`.

**Markers.** INFERRED means the row, or the marked cell, is a deduction, not an observation.
"open" means no fix exists.

**Engine-era rows.** Rows citing `rb`/`RS/` come from the C++ native engine (stl2step port). The loop
no longer goes through it, but each such row records a way an OCCT construction fails, so it still
bears on what an `rt` function must avoid.

---

## 1. Tables of observed errors

### BO: blend omitted, modelled sharp (the most frequent loop error)

| id | symptom | junction signature(s) | root cause | fix | source | toolbox action |
|---|---|---|---|---|---|---|
| BO-01 | part 1: curved 13/40, misses r1.52 x13 PLANE, r25.39 x2 NONE; where_wrong "NOT COVERED 55 samples, up to 3.17 mm" | `blend:cylinder\|plane+plane\|fillet` (r1.524 tower base), `blend:torus\|cylinder+plane\|fillet` (boss ring) | base fillets and the vertical r25.4 boss never modelled | BoxSelector `.fillet(1.524)`; boss ring as revolved torus trimmed to tower plan; `edges("\|Z").fillet(4.7625)`. 40/40 | RL: recon2_1 r1->r2 | already covered by rt.edge_round + rt.ring_fillet; decision-tree rule (brief must list every blend signature) |
| BO-02 | part 6: curved 29/52, misses r4.0 x9 PLANE, r2.54 x6 | `blend:cylinder\|plane+plane\|fillet`, `blend:torus\|cylinder+plane\|fillet` | floor fillet built as 3.9 (true 4.0); end-wall r2.54, web base, tube-to-wall and pad-to-wall fillets absent | explicit fillet rings `ycyl.cut(makeTorus(19.05+RF, RF))`, web profile with `threePointArc`. 43/52 | RL: recon2_6 r1->r2 | new rt function `rt.round_primitive`; already covered by rt.ring_fillet (tube-to-wall) |
| BO-03 | part 9: curved 48/77, misses r1.95-2.17 x14 PLANE | `blend:cylinder\|plane+plane\|round`, `blend:torus\|cylinder+plane\|round` | R2 top/bottom rounds absent | `ring.edges(">Z or <Z").fillet(R_EDGE-1e-3)` | RL: recon2_9 r1->r2 | already covered by rt.edge_round |
| BO-04 | part 11: curved 9/34, misses r3.88-4.43 x14 PLANE | same pair | R4 perimeter rounds absent | one `.edges(...).fillet(4)` | RL: recon2_11 r1->r2 | already covered by rt.edge_round |
| BO-05 | part 12: curved 22/30, misses r1.98-2.05 x8 PLANE | same pair | R2 rounds on outline and bores absent | one `fillet(2)`; tori 0->20 | RL: recon2_12 r1->r2 | already covered by rt.edge_round |
| BO-06 | part 17: curved 38/50, misses r76.13-76.25 x12 | `blend:cylinder\|plane+plane\|fillet`, `blend:cylinder\|cylinder+plane\|fillet` (plan-view concave corners) | concave plan blends absent, wheel slots wrong | plan outline rewritten as one exact line/arc wire; own analytic `fillet(line, circ, r)` tangent solver. 50/50 | RL: recon2_17 r1->r2 | new rt function `rt.tangent_profile` |
| BO-07 | part 17 (old gate): curved 31/50, misses r76.2 x7, r317.2-317.5 x8 PLANE | as BO-06, plus end caps modelled flat (`cylinder\|plane\|line\|convex` built as `plane\|plane`) | blends absent; R317.5 end caps flat | caps as arcs, hub disk added; 50/50 but then invalid (RT-08) | RL: recon2_17_oldgate r1->r2 | new rt function `rt.tangent_profile` |
| BO-08 | part 23: curved 57/80, misses r3.01-3.07 x14 | `blend:torus\|cylinder+plane\|round`, `blend:cylinder\|plane+plane\|round` | R3 rounds absent | `fillet(3)` on all top/bottom edges after cuts; tori 0->38 | RL: recon2_23 r1->r2 | already covered by rt.edge_round |
| BO-09 | part 25: curved 17/46, far 7, misses r5.88-6.05 x15 | same pair | R6 rounds absent | `s.cut(holes).edges("not \|Z").fillet(6.0)` | RL: recon2_25 r1->r2 | already covered by rt.edge_round |
| BO-10 | part 33: curved 77/121, misses r0.47-0.52 x15 PLANE | `blend:torus\|cone+plane\|round` (drafted walls) | r0.5 top-edge round absent | profiles solved to exact tangency, draft via `BRepOffsetAPI_DraftAngle`, then `faces(">Z").edges().fillet(R_TOP)`; 121/121, one B-spline face left (NA-04) | RL: recon2_33 r1->r2 | new rt function `rt.drafted_prism` (with top_round) |
| BO-11 | part 35: curved 26/58, misses r0.99-1.09 x15 | `blend:torus\|cylinder+plane\|round`, `blend:cylinder\|plane+plane\|round` | R1 rounds on window and slots absent | `result.val().fillet(1.0, inner_wire_edges)` | RL: recon2_35 r1->r2 | already covered by rt.edge_round |
| BO-12 | part 36: curved 17/31, far 5, cones 35, misses r4.01-4.05 x14 | `blend:torus\|cylinder+plane\|round` (slot rim) | the rim round was read as wall draft (BT-04) | taper removed, `fillet(4.0)` on rim edges; 30/31 | RL: recon2_36 r1->r2 | decision-tree rule DT-07 |
| BO-13 | part 37: curved 65/102, misses r3.69-4.10 x14 | `blend:torus\|cylinder+plane\|round` | outer perimeter r4 absent | one fillet line; 102/102 | RL: recon2_37 r1->r2 | already covered by rt.edge_round |
| BO-14 | part 39: curved 40/62, p95 11.5/14.0, misses r60 x13, r431.6 PLANE | `blend:torus\|cylinder+plane\|round` (R60), `blend:cylinder\|cylinder+cylinder\|fillet` (R127 plan fillets) | R60 applied per slot, not globally; arm/ring/hub plan fillets absent; spline count and bore wrong (9 vs 11 slots) | analytic fillet centres for R127; one global `faces(">Z").edges().fillet(60)`. 62/62 | RL: recon2_39 r1->r2 | new rt function `rt.tangent_profile`; already covered by rt.edge_round |
| BO-15 | part 21: where_wrong "60 samples, 1.73 mm" (feature gate already full) | `blend:torus\|cylinder+plane\|round` (bore mouth) | R6 mouth round absent | `fillet(6.0)`, wrong edges picked (LP-02), fixed r3 by revolved half-section | RL: recon2_21 r1->r2 | already covered by rt.hole(mouth_round) |
| BO-16 | part 22: p95 3.94/6.07, dV +8.1%, where_wrong 8.17 mm | full-round throat, `blend:torus\|cylinder+plane\|round` x2 meeting (INFERRED) | modelled as a straight D127 bore; the bore is an R20 toroidal throat | revolved half-section `lineTo..threePointArc..revolve(360)`; p95 0.009 | RL: recon2_22 r1->r2 | new rt function `rt.revolve_profile` |
| BO-17 | part 32: where_wrong "86 samples, 2.42 mm" | `blend:torus\|cylinder+plane\|round` | R6 hole-mouth rounds absent | circle edges filtered by centre+radius, `.fillet(6.0)`; tori 0->6 | RL: recon2_32 r1->r2 | already covered by rt.hole(mouth_round) |
| BO-18 | part 18: where_wrong "39 samples, 2.43 mm" | `blend:torus\|cylinder+plane\|round` | mouth feature absent, then mistyped (BT-03) | `makeCone` chamfers (wrong type) | RL: recon2_18 r1->r2 | already covered by rt.hole(mouth_round); decision-tree rule DT-07 |
| BO-19 | parts 12/23 (deterministic path): 20 and 57 radial partial cylinders dropped, sweep 16-62 deg, R~2.0/3.03, axis radial to Z | `blend:cylinder\|plane+plane\|fillet` with axis perpendicular to the extrusion axis | auto2d/auto25g fit arcs only in the extrusion plane (auto2d.py:76-119), so the radial fillet is unrepresentable | `FR/radial_fillets.py` augment(): corner-wedge swap per patch, kept only while valid with 0 free edges | MS: 2783a30; mem:project_missing_features_are_fillets.md | new rt function `rt.radial_fillet` |
| BO-20 | part 12 at keep 0.35: `stepped` build serves 0 tori | `blend:torus\|cylinder+plane\|round` | level-stack builder cannot emit a torus; approximates fillets by a plane/cylinder staircase | none on that path; loop reaches 30/30 | MS: mem:project_part19_solved_by_decimation.md | already covered by rt.edge_round / rt.boss |
| BO-21 | engine: 728 R~4 bands on part 11 with coplanar axes fanning 180 deg | `blend:torus\|cylinder+plane` ring | torus faces "not implemented" (rb:5208); rejectTorusSlicesN5F groups by radius only | engine never fixed; solved by edgebuild tori and canon.py | MS: b967967; LS/RESUME.md:240 | already covered by rt.ring_fillet |
| BO-22 | engine: a torus committed as 86 equal-radius cylinder slices; rolling blend as 123 cylinders R2.0 on 121 axes | `blend:torus\|...` sliced; `blend:cylinder\|plane+plane\|round` chain (INFERRED) | per-patch tests cannot see a swept blend | orientation tensor of the radius group's axes; N12_BLEND guard (neutral) | MS: 4348df8; LS/n12-ladder13-triage.spec.md:245 | guard in loop/gate (GD-05: torus-vs-cylinder model test) |

### BT: blend or chamfer given the wrong type (draft, cone, chamfer)

| id | symptom | junction signature(s) | root cause | fix | source | toolbox action |
|---|---|---|---|---|---|---|
| BT-01 | part 7: p95 0.45 -> 0.73 (worse), where_wrong 1.32 -> 3.23 mm | `blend:torus\|cylinder+plane\|round` (bore top R6) | bore built as `makeCone` with facts' 5.83 deg pseudo-draft; r2 only flipped the draft sign | r3: straight bore + `fillet(6.0)`; cone 1->0, torus 0->1 | RL: recon2_7 r1->r2->r3 | decision-tree rule DT-07 |
| BT-02 | part 19: p95 0.110, where_wrong 0.15 mm | `blend:torus\|cylinder+plane\|round` | R_TOP=6.35 read from renders ("1/4 inch"); the facts' 5.83 deg pseudo-draft implies R6.0 | `R_TOP = 6.0`; p95 0.011 | RL: recon2_19 r1->r2 | guard in loop/gate (GD-09: dimensions from facts) |
| BT-03 | part 18: cones 4, where_wrong 0.50 mm | `blend:torus\|cylinder+plane\|round` built as `cone\|cylinder\|circle\|convex` | mouth R6 fillet built as a 3.5 mm chamfer | `edges("%CIRCLE").fillet(6.0)`; cones 4->0, tori 0->4 | RL: recon2_18 r2->r3 | decision-tree rule DT-07 |
| BT-04 | part 36: 35 cones | `blend:torus\|cylinder+plane\|round` read as cone walls | spurious draft facts from the rim rounds | walls vertical, rim `fillet(4.0)` | RL: recon2_36 r1->r2 | decision-tree rule DT-07 |
| BT-05 | part 30: where_wrong 109 samples, 0.16 mm | hole-mouth chamfer `cone\|cylinder\|circle\|convex` (INFERRED) read as -2.1 deg draft | chamfer read as draft | 45 deg tapered prism `extrude(C+0.01, taper=-45)` | RL: recon2_30 r1->r2 | new rt function `rt.edge_chamfer`; decision-tree rule DT-07 |
| BT-06 | deterministic path: p22 blends chained into one "cone" | blend chain along a drafted wall | dihedral join at 20 (and 5) deg | open: residual-based growth | MS: b4ccd2c, 3138be9 | decision-tree rule DT-07 (INFERRED applicability) |

### NA: construction produced a non-analytic face (B-spline or surface of revolution)

| id | symptom | junction signature(s) | root cause | fix | source | toolbox action |
|---|---|---|---|---|---|---|
| NA-01 | part 6 r2: misses "r=2.540 NON-ANALYTIC (spline)" x3 | `blend:cylinder\|plane+plane\|fillet` chain of radii 2.54 and 3.9 | sequential `.fillet()` of different radii on one tangent chain (OCC propagates round the chain) | floor fillets as primitives: `box.cut(xcyl(RB))`, corner = `zcyl - zcyl - makeTorus(RB-RE, RE)`; misses 9->3 | RL: recon2_6 r2->r3 | new rt function `rt.round_primitive` + `rt.corner_blend` |
| NA-02 | part 6 best: 3 misses r2.54 NON-ANALYTIC; best.step holds 2 SURFACE_OF_REVOLUTION faces, `bsplines=0` | three-fillet corner, `blend:torus\|cylinder+plane\|fillet` with minor > major (spindle, R1.46 < r2.54) | `makeTorus(RB-RE=1.46, RE=2.54)`; r4 revolved the arc about the corner axis (same result) and got worse 49->47 | open (loop ended 49/52; r5 "no file") | RL: recon2_6 r3, r4; recon2_6/best.step | new rt function `rt.corner_blend`; guard in loop/gate GD-02 |
| NA-03 | parts 14, 19: B-spline faces in accepted best, not flagged (14: 2 faces 36 569 mm2 at z 825; 19: 2 corner patches ~2.1 mm2) | 14: `blend:cylinder\|cylinder+cylinder\|fillet` r177.8; 19: vertex blend of `faces(">Z").edges().fillet(6)` (INFERRED) | cadquery `.fillet()` between parallel cylinders / at a vertex where rounds meet yields B-spline blends | open; gate scored curved == patches | RL: recon2_14 r4, recon2_19/best.step | new rt function `rt.tangent_profile` (14), `rt.corner_blend` (19); guard GD-02 |
| NA-04 | part 33 best: 1 B-spline face 2.0 mm2 at z 4.81 | `blend:torus\|cone+plane\|round` | `fillet(0.5)` on walls drafted by DraftAngle (INFERRED) | open | RL: recon2_33/best.step | new rt function `rt.drafted_prism` |
| NA-05 | part 36 r2: miss "r=56.477 NON-ANALYTIC (spline)" | outer wall `other` | model replaced a measured arc chain with `.ellipse()` inscribed in bbox | arc chain restored; 31/31 | RL: recon2_36 r2->r3 | guard in loop/gate (GD-10: no ellipse/spline primitives unless facts show one) |
| NA-06 | revolved-arc rounds exported as SURFACE_OF_REVOLUTION over a B-spline (counts as lost) | `blend:torus\|cylinder+plane\|round`, R1.46 < r2.54 | OCCT's STEP writer cannot emit a torus with R < r | `tools/recon/canon.py` rewrites the STEP to (DEGENERATE_)TOROIDAL_SURFACE, kept only if validity, faces, volume hold; 1241 -> 1244/1244 | MS: 261a720; mem:project_spindle_torus_step_writer.md | already covered by rt.boss (top_round spindle) + canon; guard GD-01 |
| NA-07 | part 16 deterministic full round: OCCT fillet near 0.5 x thickness gives 3 unorientable faces and a shell, not a solid | `blend:cylinder\|plane+plane\|round` (full round, r = T/2) | BRepFilletAPI_MakeFillet unreliable near r ~ T/2 | measure flat-band rho, check solid count; loop solved 16 with 8 tori in r1 | MS: 93b390e, f656e6a; Forgetful #3127 | new rt function `rt.full_round` |
| NA-08 | piped rims invalid; direct-construction fuse empty | torus rim (INFERRED `blend:torus\|plane+torus\|round`) | MakePipe spine has convex arcs tighter than the rim radius | parked | MS: 566a0f8, d22bf1f | new rt function `rt.corner_blend` (INFERRED) |
| NA-09 | FreeCAD RE: `makeFillet` refuses a swept face at every radius | edge of a periodic B-spline profile (`other`) | closed periodic BSpline has a seamless edge with no vertices; makeFillet is all-or-nothing over its edge list | split profile into non-periodic segments; fillet one edge at a time, largest first | MS: Forgetful #2312 (gancio_zanza, sibling RE job) | guard in loop/gate (GD-11: per-edge fillet probe) |
| NA-10 | auto2d: 18/24 parts fail `GC_MakeArcOfCircle StdFail_NotDone` | `cylinder\|plane\|circle\|convex` (full hole in section) | a full-circle loop gives a 3-point arc with start == end | full `gp_Circ` edge | MS: a533408 | already covered by rt.hole |
| NA-11 | blanket repair converted 302/572 (part 39) and 876 (part 6) circles to splines | any circle edge | repair applied to every conic edge | scope conversion to faces that come back invalid (37 edges on 39) | MS: 2783a30; Forgetful #3167 | guard in loop/gate (GD-12: scoped repair) |
| NA-12 | alphaevolve: a real cylinder replaced by an 8-section loft (NC 0.944 vs 0.774) | cylinder surface as loft (`other`) | parsimony metric preferred loft fidelity; `_CIRC_THRESHOLD=0.85` sent true cylinders to loft | never fixed; parsimony dropped in 059ab14 | AE: OVERNIGHT_STRATEGY.md s2; seed_recon.py:31; Forgetful #589 | guard in loop/gate (GD-02: B-spline never beats analytic) |
| NA-13 | alphaevolve: `ruled=True` loft gives faceted strips | loft between polygon sections (`other`) | ruled surfaces | `ruled=False` (+0.020) | AE: work_log.csv 02:02-02:05; cadquery_gen.py:187 | guard in loop/gate (GD-10) |

### BL: boolean construction, order and overreach

| id | symptom | junction signature(s) | root cause | fix | source | toolbox action |
|---|---|---|---|---|---|---|
| BL-01 | part 39: fold with a 0.138 mm2 REVERSED plane and a 0.117 mm2 FORWARD plane on one 1.09 mm edge carrying 4 faces; passes BRepCheck in memory, fails after serialization | radial corner sector `blend:cylinder\|plane+plane` against a level shelf | `_apply` did `Fuse(shape, add)` then `Cut(rem)`; the extra intermediate emits two slivers | `keep = Cut(shape, corner); add = Common(corner, cyl) if convex else Cut(corner, cyl); Fuse(keep, add)` (FR/radial_fillets.py:216) | MS: 9caa99c; mem:project_fillet_boolean_order.md | new rt function `rt.radial_fillet` (bake the order in); guard GD-01 |
| BL-02 | part 6 r2: "YOUR SOLID HAS SURFACE 24 samples 1.61 mm" + "NOT COVERED 2.43 mm" | `blend:torus\|cylinder+plane\|fillet` at pad ends | a full `makeTorus` cut also gouged the straight run | `f.cut(tor.intersect(box(half)))`: keep only the end-cap half | RL: recon2_6 r2->r3 | new rt function `rt.corner_blend` (torus clipped to its sector) |
| BL-03 | part 6: dV +3.92%, +11 955 mm3 in band z 29.12-32.14 | `cylinder\|plane\|circle\|convex` (bore opening at a level) | `material_area()` summed hole loops instead of subtracting them; a level whose bore opens was merged into the level below | odd-depth containment rule (FR/auto25g.py:34); dV -0.62% | MS: 9caa99c; mem:project_material_area_summed_holes.md | guard in loop/gate (INFERRED: facts.py section areas must be outer minus holes) |
| BL-04 | parts 14/39/6 stepped: sliver "lens" faces at level boundaries (two near-coincident arcs sharing both endpoints; r 634.99 vs 641.86) | `plane\|plane` shelf bounded by two arcs of the same physical `cylinder\|plane\|circle` edge | adjacent level prisms carry different arc fits of one edge | scoped conic->non-periodic BSpline repair on re-read (FR/auto25g.py:127); glue fuse only 25->15 | MS: e39ece5, 42117bb, 2783a30; mem:project_sliver_lens_faces_39_6.md; Forgetful #3166 | decision-tree rule DT-12 (one feature = one primitive, never per-level arcs) |
| BL-05 | seeded band: 10 free edges, shell not solid | `cylinder\|plane\|circle` rim breached 270 deg by cross holes; `cylinder\|cylinder\|other` | chord-to-circle swap, MakeWire fails, face keeps chord chain | refuse seeds without closed rims or with mid-wall breaches (rebuild.py:120-152) | MS: 385ea65 | already covered by rt.hole (cut cross holes after the bore) |
| BL-06 | band rebuilt across a mid-wall hole closes a 360 deg face over it | `cylinder\|cylinder\|other` | rims closed but wall breached | same checks | MS: 385ea65 | decision-tree rule DT-11 (build bore, then cross holes) |
| BL-07 | slot box over-cuts (-1.96%) | `plane\|plane\|line\|concave` slot | cutter not bounded at the floor | bound at the unpaired floor (autorev_cut4) | MS: be8152f | new rt function `rt.slot` (INFERRED) |
| BL-08 | holes shrink 3.19 mm under the outline offset | `cylinder\|plane\|circle\|convex` | offset applied to hole loops; fillet applied to hole walls | offset only the outer loop | MS: fcae327 | already covered by rt.hole (holes after profile ops) |
| BL-09 | alphaevolve: booleans that barely intersect or touch tangentially give non-watertight results (~25% at TS<1, estimated) | cutter coplanar/tangent to base (INFERRED `cylinder\|plane`) | coincident/tangent faces between tool and base | proposed oversize cutter (height x2.5, radius x1.02); never shipped | AE: OVERNIGHT_STRATEGY.md s2 item 4; Forgetful #398 | already covered by rt.hole (cutter spans `_extent`); guard GD-11 |
| BL-10 | 3dprint-pipeline CadQuery benchmark: fillet_crash, detached parts after unions | any fillet after booleans | `.faces().edges().fillet()` after booleans is unstable; many sequential unions degrade | fillet before booleans; overlap >= 0.1 mm; solid-count assertion | MS: Forgetful #99, #100 (sibling project, not mesh2step) | guard in loop/gate (GD-13: solid count == bodies) |

### RT: valid in memory, invalid or changed after STEP round trip

| id | symptom | junction signature(s) | root cause | fix | source | toolbox action |
|---|---|---|---|---|---|---|
| RT-01 | parts 39/6 stepped: 12/232 and 8/916 faces invalid after re-read, every edge valid; in-memory BREP valid | `plane\|cylinder\|circle` (periodic pcurves on lens faces) | STEP reader reparametrises by ~1e-13, tipping BRepCheck_Wire::SelfIntersect on periodic circle pcurves | convert conic edges to non-periodic BSpline on the invalid faces only, SameParameter + ShapeFix | MS: 2783a30; Forgetful #3166 | guard GD-01 + GD-12 |
| RT-02 | Schlauchschelle: valid 548.9 mm3 in memory, re-read 60.3 mm3, outer wall missing, service said Ready | `cylinder\|other` (facet island) | boundary kept as 130 mesh chords 3.4 um off the cylinder; STEP has no tolerances | degree-2 BSpline edge on the cylinder shared by both faces (engine v1.8.1) | MS: 18b742f; Forgetful #3134 | guard GD-01 |
| RT-03 | STEP re-read gives cylinder faces 430-6038 mm2, negative area, 2.1x volume | partial cylinder starting at u=0 | patch frame rotated to u=0 with negative-u pcurves (INFERRED by the author) | superseded by the feature path | MS: 3c73fc3, 5cba15e | guard GD-01 |
| RT-04 | part 14 r1-r3: valid=False with p95 0.082; no location given | `blend:cylinder\|cylinder+cylinder\|fillet` as sketched tangent-arc wire at ~5 m coordinates | "sketched face fails BRepCheck after STEP round-trip at these absolute coordinates" (model's comment) | r4 used 3D `.fillet()`: valid but B-spline (NA-03) | RL: recon2_14 r1-r4 | new rt function `rt.tangent_profile` (local frame near origin, INFERRED); guard GD-06 |
| RT-05 | part 17 old gate r2-r3: valid=False at 50/50; best fell back to r1 (31/50) | concave plan blends + curved slot | fillet-API tangent vertices and slot boolean slivers (INFERRED from the program comments) | single-wire `arc_slot`, still invalid; rerun solved with analytically solved tangent points | RL: recon2_17_oldgate r2-r5, recon2_17 r1 | new rt function `rt.tangent_profile` |
| RT-06 | part 17 best rounds: one invalid plane face | plane | not recorded | `repair_step_shape` made it valid (loop repair step) | MS: Forgetful #3236 | already covered by loop repair step |
| RT-07 | spindle torus correct in memory, SURFACE_OF_REVOLUTION in the file | see NA-06 | writer limitation | canon.py | MS: 261a720 | guard GD-01 |
| RT-08 | part 16: in-memory says invalid, re-read valid | blend round | the two verdicts disagree in both directions | judge on the served STEP | MS: 88000b2 | guard GD-01 |
| RT-09 | t4 rejects a component whose file is 0.011% correct (in memory 2.2% off); BRepGProp 4.2% wrong on a valid shell; revolved B-spline volume 0.2% off | n/a | in-memory GProp differs from the shipped file | round-trip retest; adaptive `VolumeProperties_s(s, g, 1e-9, False)` | MS: 9da1fa5, 9296873; mem:project_spindle_torus_step_writer.md | guard in loop/gate (measure volume on the re-read file) |
| RT-10 | unify at write time turns a valid shell invalid | n/a | no ShapeFix after unify | none | MS: LS/RESUME.md:974-981 | guard GD-01 |

### ED: edge, pcurve and seam construction (engine era; constraints on any rt builder)

| id | symptom | junction signature(s) | root cause | fix | source | toolbox action |
|---|---|---|---|---|---|---|
| ED-01 | planar slivers: 62/64 built Reversed, BadOrientationOfSubshape | `plane\|plane\|line` tiny region | outer wire enclosed the infinite region; the "retry reversed wire" used MakeFace Inside=true (a no-op) | Inside=false retry (P103); 89/96 valid | MS: 4348df8, 50a6e35; Forgetful #3087 | guard GD-01 (INFERRED: cq faces made from wires are exposed too) |
| ED-02 | 98 partial-cylinder faces UnorientableShape | `cylinder\|plane`, `cylinder\|cylinder` | straight UV pcurve for every non-conic edge; seam-straddling regions not unwrapped | GeomProjLib::Curve2d (bad 15->2) | MS: faefc2d, 79f8359 | decision-tree rule DT-12 (build partial cylinders by booleans, never by face assembly) |
| ED-03 | rotated-trim faces up to 67x their region's area | partial cylinder | a Geom_RectangularTrimmedSurface passed to builders; cast to cylinder is NULL | unwrap BasisSurface() (N50); never pass a trimmed surface | MS: ba92bac, 92c32b5 | same as ED-02 |
| ED-04 | every wire edge starts and ends at one vertex | partial cylinder across the seam | BRepBuilderAPI_MakeWire merged vertices with overlapping tolerance spheres | skip the rebuild (N61), failures 28->1 | MS: 5f27929; Forgetful #3121 | same as ED-02 |
| ED-05 | oblique ellipse trim 2.44 mm off; 2-vertex cap arc takes the short arc | `cylinder\|plane\|ellipse\|convex` | IntAna ellipse on coarse boundaries; shortest-arc default | explicit mid-point arcs, full circles | MS: RS/FINDINGS-E.md | new rt function `rt.oblique_hole` (INFERRED) |
| ED-06 | closed 360 deg cylinders never built; seamed360 with 51 free edges | `cylinder\|plane\|circle\|convex` closed; `cone\|cylinder` chamfer faceted | constructor missing; no cone primitive | trySeamed360; share the circular edge by construction | MS: b50d240, c785956; LS/n5c-mixed-boundary.spec.md:47 | already covered by rt.hole / rt.boss |
| ED-07 | torus interior classified OUT (1.29 mm vs 0.0004) | `blend:torus\|cylinder+plane` side edge | interpolated B-spline pcurve hooks at the tangent corner | exact iso circle (EB_ISO_SNAP) | MS: 814bce4 | already covered by rt.ring_fillet (primitive torus) |
| ED-08 | `cylinder\|cylinder` IntAna no solution: 111/120 misses part 9, 186/213 part 11; hotend 43x "IntAna cyl\|cyl empty" -> shell open -> 36 cyl + 126 fillets reverted | `cylinder\|cylinder\|line\|tangent` or skew | independently fitted axes a few degrees apart | parallel gate 8 deg; skew open | MS: LS/FINDINGS-N27-kimi.md, RS/FINDINGS-CYLEDGES.md; Forgetful #3224 | decision-tree rule DT-08 (shared axis by construction) |
| ED-09 | exactly tangent torus/plane: projection cannot converge; 2.83 mm cone/cylinder edge as 55 and 158 mm B-splines | `blend:torus\|cylinder+plane`; `cone\|cylinder` near-tangent | parallel gradients; points slide along tangent surfaces | closed-form circle; pin points by a section plane | MS: 0192491, 45ec7d3, d1bf5df | already covered by rt.ring_fillet / rt.hole(mouth_chamfer) |
| ED-10 | straight chain gets 0.06-0.07 mm bumps | `plane\|plane\|line` at ~2 deg dihedral | ill-conditioned intersection (bump ~ d/sin theta) | intersect only within budget, else fitted line | MS: LS/n5e-wire-chaining.spec.md:158 | decision-tree rule DT-13 (near-coplanar planes are one plane) |
| ED-11 | 4 free B-spline edges 11-52 mm on an oblique cylinder/torus junction | `cylinder\|torus\|other` | point projection bounces between IntSS branches | exact GeomAPI_IntSS fallback (diag only) | MS: 7ea65e4 | new rt function `rt.oblique_hole` (INFERRED) |
| ED-12 | torus face trimmed short where oblique R10 bores cut it (dist_p95 6.86) | `cylinder\|torus\|other` through `blend:torus\|cylinder+plane\|fillet` | edgebuild.py:2097 assumes two whole-circle loops per torus face | open | MS: 7ea65e4; FINDINGS2.md s2 | already covered by rt.ring_fillet then rt.hole (boolean order handles the holes) |

### DM: wrong dimension, radius, axis or position

| id | symptom | junction signature(s) | root cause | fix | source | toolbox action |
|---|---|---|---|---|---|---|
| DM-01 | part 34: p95 0.056, where_wrong 0.50 mm | countersink: `cone\|cylinder\|circle\|convex` + `cone\|plane\|circle\|convex` (INFERRED) | Z levels off by ~0.05; countersink 34.4 deg vs true 82 deg | constants corrected; p95 0.0035 | RL: recon2_34 r1->r2 | new rt function `rt.countersink` |
| DM-02 | part 38: where_wrong 12.73 mm | `plane\|plane\|line\|concave` (INFERRED) | end-slot half-width 38.1 guessed from a render ("not in facts") | 25.4 from the mesh walls | RL: recon2_38 r1->r2 | guard GD-09 |
| DM-03 | part 30 r2: p95 0.051, max 0.42 | outline arcs vs tangent line | profile arcs should be a straight tangent line; chamfer 0.6 not 0.5 | profile edited, C=0.6 | RL: recon2_30 r2->r3 | new rt function `rt.tangent_profile` |
| DM-04 | part 9 r3: p95 0.1338 unchanged r2-r3 | outer `cylinder\|plane\|circle\|convex` | mesh chord sagitta biased the R51.69 fit | `R_OUT = 51.69 - 0.065`; p95 0.069 | RL: recon2_9 r3->r4 | guard in loop/gate (INFERRED: facts report sagitta-corrected radius) |
| DM-05 | part 3: p95 0.94/2.35, where_wrong 6.25 mm | `cylinder\|plane\|line\|tangent` (web into knuckle, INFERRED) | clevis topology misread from renders | webs tangent to knuckles (`tangent_pt`); p95 0.002 | RL: recon2_3 r1->r2 | new rt function `rt.tangent_profile` |
| DM-06 | part 14: p95 84/110, miss r2095 x2 NONE | stepped rim (INFERRED) | tooth-rim side relief absent | ring cuts z 127..635 | RL: recon2_14 r1->r2 | decision-tree rule (none; missing feature) |
| DM-07 | polydryer: where_wrong 1.96 mm (floor windows), then 0.24-0.29 at skirt corners | drafted `cone\|plane`, window rounds (INFERRED) | r2 flare ineffective; skirt draft and bowed sides not modelled | r3 0.48 deg drafted skirt + window round via sweep; r4 concave corner profile revolved as toroidal cutter; r5 bowed sides; p95 0.044 | RL: recon2_polydryer r1-r5; Forgetful #3230 | new rt function `rt.drafted_prism` |
| DM-08 | part 23: six axial half-cylinders "missing"; section arcs 0.15-0.8 mm undersized | `cylinder\|plane` axial half-bore | auto2d section fit (ARC_TOL=0.02 + greedy merge at auto2d.py:87 suspected, unverified) | patch refit wins 6/6; spec dispatched | MS: 23c3d1a; mem:project_section_arcs_fitted_undersized.md | guard in loop/gate (INFERRED: prefer patch radius over section radius when they disagree) |
| DM-09 | coarse N-gon fits inscribed radius (13.87 vs 16); large-R arcs over-fit (27.3 vs 20); 15 mm bore fits 11.70 | cylinder, coarse | Kasa low bias; Gauss/Eberly high bias; axial bands drag the fit | circumferential-chord refine, Pratt, arch-chain R=w/(2 sin(t/2)), rHint | MS: b4b11fe, c75fe85; RS/FINDINGS-G.md, FINDINGS-ARCHCHAINS.md, FINDINGS-RADIUS15.md | guard (INFERRED: facts.py radius estimator choice) |
| DM-10 | R 0.1556 vs 0.15 (+3.75%), cap chain vetoed, 0 cylinders | `cylinder\|plane\|circle` | 3D chord over an azimuthal angle includes the axial term | P85 (not promoted: costs pillow_block 10->0) | MS: LS/n6-post-build-oracle.spec.md:527-612 | guard (INFERRED) |
| DM-11 | band axis from unsigned SVD rim normal; r=24.65 and r=3.3 walls dropped | `cylinder\|plane\|circle` | sign ambiguity | axis from the rim pair | MS: 7c2f113 | decision-tree rule DT-08 |
| DM-12 | stepped/extrusion picks wrong axis: p20 -71.9%, staircases of 8-28 levels | n/a | axis chooser | retry all axes, keep best valid; bisected levels | MS: b0eb1cd, 15167bc, 1e18449 | guard (facts.py auto axis; already in loop) |
| DM-13 | turned-part bore off by -60..+64% | `cylinder\|plane\|circle\|concave` | bore = min distance over all points (cross holes, flats read as bore) | innermost loop enclosing the axis | MS: e861089 | new rt function `rt.revolve_profile` |
| DM-14 | 2 mm chamfer cone k1 7.2e-4 short of the cylinder rim; 10-tri cone refit blows up (k0 3e17) | `cone\|cylinder\|circle\|convex` | coaxial projection moved only the origin; unguarded refit | refit in the constraint null space; EB_REFIT_GUARD | MS: d1bf5df, 814bce4 | already covered by rt.hole(mouth_chamfer) (exact cone by construction) |
| DM-15 | S63: 53 triangles over 2.19 mm give torus major 146 vs true 44 | torus fragment | a short arc does not contain its own major radius | cross-region absorb (EB_ABSORB_FACETS, off by default) | MS: 8797f02; mem:project_refit_before_split_refuted.md | decision-tree rule DT-03 (torus major from the coaxial cylinder, not the patch) |
| DM-16 | tangency constraint pulls surfaces off their vertices; two tangencies slide a cylinder around its axis | `cylinder\|cylinder` tangent | constraint over-applied | drop any constraint that pulls a surface off its vertices | MS: eb127f6, 4a81f17; mem:project_edgebuild_intersection.md | new rt function `rt.tangent_profile` (tangency solved in 2D) |
| DM-17 | alphaevolve: cylinder wrong axis (NC 0.35); radius off-centre | cylinder | position-PCA axis; missing cu/cv offset | least-squares line through section centroids (NC 0.77); normal-SVD axis; offsets | AE: work_log.csv 02:06-02:30, cac698a; Forgetful #423 | guard (INFERRED: axis from section centres, already in facts.py) |
| DM-18 | alphaevolve: block/disk/plate sliced along the shortest axis; OBB sign flip | n/a | eigenvalue ratio on a short axis ranked first; det<0 eigenvectors | ratio capped at 5 (f92e79f); det+1 | AE: f92e79f; axis_detection.py:84; seed_recon.py:728 | guard (INFERRED) |

### ID: feature identity, dedupe and acceptance filters

| id | symptom | junction signature(s) | root cause | fix | source | toolbox action |
|---|---|---|---|---|---|---|
| ID-01 | 11 distinct R2.0 fillets on part 12 collapse into 1 face (23: 40 of 42 skipped) | `blend:cylinder\|plane+plane\|fillet` x N | augment() skipped any candidate whose radius already existed | identity = axis line + overlapping axial span | MS: 2783a30; mem:project_fillet_filters_reject_good_features.md | guard in loop/gate GD-04 |
| ID-02 | vetoed "cylinder" patches on part 12 lie on a torus minor 2.000 (err 1e-4) vs cylinder refit err 3e-3..9e-3 | `blend:torus\|cylinder+plane` | classify's 2.0 is the torus minor radius; a cylinder refit disagrees and the 15% veto fires (correctly) | keep the veto; add a torus path | MS: a3752f0, 23c3d1a; LS/fillet-radius-guard.spec.md | guard GD-05 |
| ID-03 | "refit wins 21/21" and "patch wins 6/6" adjudications void | n/a | competing fits scored with the metric one of them minimises | point-to-surface against the model, or both fits against the mesh | MS: 23c3d1a; mem:project_coverage_metric_was_wrong.md | guard GD-05 |
| ID-04 | part 12 no-loss check says "nothing lost" while served build changes by 30 radii | n/a | `_passes_gate` compares against radii entering augment(), not the served build | compare at the serving site (open) | MS: mem:project_radial_fillets_shipped.md | guard in loop/gate GD-07 |
| ID-05 | L08 `turned`/`block` builds recover 4/4 cylinders and are discarded for solids=4 / dV 503%; clamp_half_a 6/11 lost on p95 0.443 vs 0.286; hotend one unclosable shell discards 36 cyl + 126 fillets | n/a | acceptance per build or per component, not per feature | open (per-feature graft chosen 2026-09-19) | MS: docs/Acilindria-physiopathologia.md B2,B3; Forgetful #3224 | guard GD-08 |
| ID-06 | L09_valve_body stepped invents 65 of 80 cylinders; SpeedTestStructure ships 139 cylinders, 12 real | n/a | confabulation when the support gate is relaxed | keep MIN_SUPPORT; report recovered AND invented | MS: docs/Acilindria-physiopathologia.md B4,B6 | guard GD-08 |
| ID-07 | L04_puck: detector finds 0 cylinders, so support()=0 and three correct builds are refused | `cylinder\|plane\|circle\|convex` (single full-height cylinder) | absence of evidence treated as evidence of absence | open | MS: docs/Acilindria-physiopathologia.md B5 | guard GD-14 |
| ID-08 | part 16 after repair: one component shipped 86 fabricated cylinders; CADScore -5.4 on a correct fix | n/a | a repair unmasked a previously reverted invented component | budget for the second defect | MS: Forgetful #3089 | guard GD-08 |

### MF: missing non-blend feature (holes, chamfers, reliefs)

| id | symptom | junction signature(s) | root cause | fix | source | toolbox action |
|---|---|---|---|---|---|---|
| MF-01 | part 5: curved 21/60, p95 4.49, dV +8.35, misses r2.66 x13, r15.87 | cross holes `cylinder\|cylinder\|other\|concave` (INFERRED), bore | cross holes and bore absent, section misread | turned-shaft rewrite, `hole()` x4, `makeCylinder` x2; 60/60 | RL: recon2_5 r1->r2 | new rt function `rt.revolve_profile` + already covered by rt.hole |
| MF-02 | part 8: curved 0/4, p95 7.45, misses r101.55 x4 PLANE | `cylinder\|plane\|circle\|convex` | three R101.6 holes absent, slab stack misread | X-extrusion with holes cut; 4/4 | RL: recon2_8 r1->r2 | already covered by rt.hole |
| MF-03 | parts 10, 29, 31, 38: where_wrong 1.37-12.73 mm; cones 0->18 (29), 0->12 (31) | chamfers `cone\|plane\|line\|convex` / plane chamfer (INFERRED; chamfers are not blends) | 2 mm window chamfer (10), chamfer on every profile edge (29, 31), 25.4x45 end chamfer (38) omitted | `chamfer(...)` / chamfer in the polyline | RL: recon2_10, recon2_29, recon2_31, recon2_38 r1->r2 | new rt function `rt.edge_chamfer` |
| MF-04 | part 30: `edge chamfer()` fails on pocket/slot wires | hole/slot mouth chamfer | OCC chamfer on those wires fails | 45 deg tapered prism extrude | RL: recon2_30 r1 | new rt function `rt.edge_chamfer` (cutter-based, not `.chamfer()`) |
| MF-05 | alphaevolve: evolved best defined `_fit_sub_primitives()` but never called it | holes/bosses (INFERRED `cylinder\|plane\|circle\|convex`) | evolution disconnected the boolean path; score did not notice | manual fix listed | AE: OVERNIGHT_STRATEGY.md s7; Forgetful #397 | guard GD-15 |
| MF-06 | alphaevolve: hole/bore regions with inverted normals vs the single-primitive fit (NC ~0.65) | `cylinder\|plane\|circle\|convex` (INFERRED) | boolean CSG vetoed; no subtract step | none (structural) | AE: OVERNIGHT_STRATEGY.md s2; memory state.md | already covered by rt.hole |

### SG: segmentation and recognition (mesh side of the junction library)

| id | symptom | junction signature(s) | root cause | fix | source | toolbox action |
|---|---|---|---|---|---|---|
| SG-01 | mesh_junctions: blend recall 16.8%, precision 0.1%; 136 144 spurious cylinder\|cylinder "blends" | `blend:cylinder\|cylinder+cylinder\|round` (false) | coarse STL splits one cylinder into tangent fragments | merge same-surface regions (axis 1 deg, 0.5% diag, radius 2%) before classifying | MS: tools/recon/specs/mesh-junctions.md:28; d80393e | decision-tree rule DT-10 |
| SG-02 | 4 crashes, LinAlgError in `_sor_axis` (parts 9, 11, 20, polydryer) | n/a | degenerate fit | a failed fit becomes `other` | MS: tools/recon/specs/mesh-junctions.md | guard in loop/gate (library robustness) |
| SG-03 | edgebuild: one bad triangle in 20 deg facing test deletes a curved region -> facet planes (79x part 16, 64x part 19 -> 21 304 planes) | torus/cylinder regions dissolved to `plane` | all-triangles facing guard (edgebuild.py:372-385) | refit-before-split refuted; loop solved 16/19 in r1 | MS: mem:project_corner_blocker_16_19.md, mem:project_refit_before_split_refuted.md | already covered by the loop (macro construction) |
| SG-04 | part 20: cylinder + tangent R2 round fitted as one surface, rejected, exploded | `blend:cylinder\|cylinder+plane` (INFERRED) | mixed smooth region | EB_SPLIT_MIXED per-triangle vote | MS: 814bce4 | decision-tree rule DT-10 |
| SG-05 | part 11: 41 of 56 "cylinders" are coarse fillet strips; n21 removed 89% of cylinder regions on part 11 | blend strips | only shape check is span 30-180 deg; n21 tuned on cadbench | N30 sag ratio; n21 withdrawn | MS: eea7de8; 8d217f2; mem:feedback_measure_on_the_user_corpus.md | guard GD-05 |
| SG-06 | part 9: 97 engine "cylinders" totalling 180 mm2 with random radii; the bore never found | edge-break strips | noise fits on a splined ring | slice-and-feature CSG rebuild in 1.3 s (77 cyl, 22 tori) | MS: 427f04b; Forgetful #3126 | already covered by the loop |
| SG-07 | octagon prism rebuilt as a cylinder (+11%) | prism vs `cylinder` | 45 deg facets inside the seed band | UI warning; sagitta ratio > 8 refusal | MS: 1f7c667 | decision-tree rule DT-14 |
| SG-08 | fake cylinders on a taper (R 7.2 vs 2.0) | cone sliced as cylinders | sec-lift + self-widening tolerance | open | MS: LS/n6-post-build-oracle.spec.md:691-1146 | new rt function `rt.drafted_prism` |
| SG-09 | hotend: seed-band fraction 0.40 vs 1.00 on all mechparts; 13.5% of features under 1 mm radius; decimation 20 656->10 328 drops smooth_cylinders 36->0 | n/a | corpus not representative; decimation below feature scale | pre-flight mesh census proposed | MS: Forgetful #3224; docs/Acilindria-physiopathologia.md A1 | guard GD-14 |
| SG-10 | decimation non-monotonic: part 19 passes at keep 0.50, fails at 0.25; unwelded STL decimation gives dV -40% / +224% | n/a | halving removes redundant tessellation, quartering removes geometry; STL is triangle soup | weld before decimating (c98d81f) | MS: mem:project_part19_solved_by_decimation.md | guard (INFERRED: facts.py on welded mesh) |
| SG-11 | alphaevolve: spheres snapped to cylinder / split into cone arcs; RANSAC cone (half-angle 0) fires on cylinders; cone missed on coordinate axes | sphere, cone vs cylinder | cv_radii threshold at poles; degenerate cone fits any cylinder; PCA-only axes | sphericity check (3708ab8); cone discarded; coordinate-axis fallback (4ff1992) | AE: 3708ab8, 4ff1992, results.tsv "RANSAC cone" | decision-tree rule DT-14 |
| SG-12 | alphaevolve: box with bore classed as cylinder (angular uniformity 0.88); cross/star profile as cylinder (0.986); L/U/C profiles as cylinder | `cylinder\|plane\|circle\|convex` vs `plane\|plane\|line\|concave` | angular metrics fooled by symmetry | threshold 0.92; non-convexity check; 2D circularity < 0.65 rejected | AE: Forgetful #459, #461, #587; seed_recon.py:270 | decision-tree rule DT-14 |
| SG-13 | alphaevolve: T-profile and I-beam lose concavity | `plane\|plane\|line\|concave` | convex-hull boundary | partly: traced boundary; seed_recon reverted to hull | AE: seed_recon.py:800; memory state.md | guard (facts.py uses exact loops; already covered) |
| SG-14 | alphaevolve: extrusion shortcut collapses box+cylinder compounds into one extrusion; borderline shapes captured by extrusion snap | compound (INFERRED `cylinder\|plane`) | shortcut fired before compound evidence | compound guard (d3a42fe); cv_areas 0.15->0.08 | AE: d3a42fe; work_log.csv 01:39 | decision-tree rule DT-12 |
| SG-15 | alphaevolve: 256-point clouds cannot separate box/cylinder/sphere; hull tracing rounds box corners into circles | `plane\|plane\|line\|convex` rounded off | sampling density below feature scale | benchmark moved to 5k-30k points | AE: Forgetful #367, #368; scripts/regen_pcd_30k.py | guard GD-14 |
| SG-16 | alphaevolve: loft/extrude crashes on zero-length edges, sparse contours, disconnected spline wires | section wires (`other`) | duplicate points; < 5 points; open spline wires | dedup, filter, polygon-only wires (f92e79f) | AE: f92e79f; cadquery_gen.py:77-183; Forgetful #390 | guard GD-10 |

### SH: shell, sewing and explode cascade (engine era, condensed)

| id | symptom | junction signature(s) | root cause | fix | source | toolbox action |
|---|---|---|---|---|---|---|
| SH-01 | watertight STL with zero-area triangles: "re-read solid count 0 != written 1" | n/a | engine skips degenerate triangles, open shell | webapp retries with --force-sew | MS: 38e7768; mem:reference_engine_skips_degenerate_opens_shell.md | guard (INFERRED: facts.py drops degenerate triangles after welding) |
| SH-02 | sewing at 0.1 mm makes 522 folds, 2.1x volume | `cylinder\|plane` cap junction | BRepBuilderAPI_Sewing welds by distance with no face-side check | own best-partner weld | MS: 387203e, 105b0ca | already covered by the loop (no sewing; CSG only) |
| SH-03 | unify opens the shell (OPEN_SHELL, 0 solids); second unify over-merges (164 free edges) | `plane\|plane` | no closure guard | transactional unify (N19); gate the pass | MS: b5f17e7; LS/n19-unify-opens-the-shell.spec.md:30; RS/FINDINGS-W2F.md | guard GD-01 |
| SH-04 | 0.6% of chains fail, 100% of geometry dies (3777 regions exploded); one invalid plane discards 155 faces | n/a | cascade response, not geometry; tautological guard (rb:5810) | cascade brakes; open | MS: 982131e; LS/n12-ladder13-triage.spec.md:27 | guard GD-08 |
| SH-05 | multi-body print-in-place mesh (3 bodies, 0.34 mm clearance) could never pass solids == 1 | n/a | gate assumed one body | rebuild per body, serve N solids | MS: 4a81f17; mem:project_multibody_meshes.md | guard GD-13 |
| SH-06 | one face per triangle: 56/96 faces fail; ShapeFix returns a VALID solid 39% short | cylinder | diagonal chords on no cylinder; silent failure | merge coplanar faces first; verify by distance | MS: c785956 | guard GD-01 (validity alone is not proof) |

### GT: gate and metric errors

| id | symptom | junction signature(s) | root cause | fix | source | toolbox action |
|---|---|---|---|---|---|---|
| GT-01 | `bsplines` counts `B_SPLINE_SURFACE` strings, not faces (14: 6 for 2 faces), and misses SURFACE_OF_REVOLUTION (part 6: bsplines=0 with 3 SPLINE misses) | n/a | string census | count non-analytic FACES by surface type on the re-read file | RL: recon2_14, recon2_6; best.step census 2026-09-22 | guard GD-02 |
| GT-02 | non-analytic faces in accepted bests (14, 19, 33) unflagged because curved == patches | as NA-03/NA-04 | gate scores only mesh patches, not every built face | open | RL: recon2_14/19/33 best.step | guard GD-02 |
| GT-03 | `feature_misses` capped at 15 | n/a | `f["misses"][:15]` (recon_loop.py:338) | report the true count patches - curved beside the list | RL: tools/recon/recon_loop.py:338 | guard GD-03 |
| GT-04 | runs of 2026-09-21 carry no `invalid_faces`; parts 14 and 17_oldgate got `valid:false` with no location | n/a | runs predate the invalid-face report (now recon_loop.py:353) | invalid_face_report + repair (specs/invalid-feedback.md) | RL: recon2_14, recon2_17_oldgate history.json | already covered (invalid-feedback) |
| GT-05 | polydryer: patches=0, feature gate vacuous (represent 0/0 on drafted walls) | `cone\|plane` drafted | mesh detector sees no cylinders on cones | open | RL: recon2_polydryer; Forgetful #3236 | guard GD-14 |
| GT-06 | part 6: best-round rule "fewest B-splines first" kept r2 (25/52) over r3 (43/52) | n/a | ranked by the wrong criterion | rank by the product instrument within fidelity bound | MS: Forgetful #3231 | guard GD-07 |
| GT-07 | part 33 converged at p95 0.040 with 19 patches on planes | n/a | stop rule purely geometric | feature completeness in gate and feedback | MS: Forgetful #3231 | guard GD-03 |
| GT-08 | 8 stalled rounds (14 r5, 17 r3-r5, 38 r3-r5, 9 r5): program unchanged or only a comment changed | n/a | absolute 0.05 mm stop target below chordal noise | stop at RECON_STOP_REL (-28% rounds) | RL: those rounds; MS: d9562ba | guard GD-16 |
| GT-09 | B-spline / surface of revolution scored as "curved"; rim vertices score as planar | other | represent() bucket; vertex sampling | only quadrics count + STEP entity witness; sample centroids | MS: a5d87b7, 912dbf1 | guard GD-02 |
| GT-10 | coverage "17/30", "36/80" wrong: 30 and 80 radii collapse to 8 and 19 clusters | n/a | radius matching counts numerical noise | point-to-surface (`scripts/patch_representation.py`) | MS: mem:project_coverage_metric_was_wrong.md | guard GD-05 |
| GT-11 | `cyl_radii` deduplicated: SpeedTestStructure reads 4 instead of 285; mesh detector finds 375/706 | n/a | `sorted(set())` at build_corpus.py:158; detector as denominator | `cyl_radii_hist`; report counts | MS: b93f850; docs/Acilindria-physiopathologia.md D2,D3 | guard GD-14 |
| GT-12 | `engine=faceted` returns n_faces == n_tris, dV 0, passes the gate while reconstructing nothing | n/a | upgrade passes gated on trueform (server.py:675-682) | split by `backend`, never by the gate | MS: mem:project_corpus_39_all_served.md | guard GD-02 |
| GT-13 | volume budget reverts a closed valid 97-cylinder shell (1.7% vs 0.1%); closest-volume selection blind to twenty R2 holes | n/a | volume as arbiter of shape | N82 advisory; select by backed cylinders | MS: ed88966; mem:feedback_shape_over_volume.md; docs/Acilindria-physiopathologia.md C2 | guard GD-07 |
| GT-14 | accepted builds lost when measure() throws Standard_NullObject; loop died on a 0-face STEP | n/a | unguarded in-process OCCT call in a candidate loop | catch per candidate; record as round feedback | MS: c45d11d, b93f850, ab4a559 | guard GD-15 |
| GT-15 | alphaevolve score 0.93 re-scored 0.637; notable-point 1.0 by copying the GT formula; feature padding to recall 0.995; boolean metric saturated | n/a | recall-only metrics, 5 samples, metric rewards the labeller | proximity-F1 on 50-100 samples; padding never fixed | AE: STATUS.md 2026-03-19, v15-v19; strategy_log.tsv 2026-04-02; Forgetful #326, #329, #366 | guard GD-15 |
| GT-16 | alphaevolve: harness edit (empty-GT 0.0 -> 1.0) counted as +0.030; seed defining `evaluate_solution()` blocked harness injection | n/a | evaluator editable inside the loop it measures | f6a6806; 073aadf | AE: f6a6806, 073aadf; alphaevolve/evaluator/sandbox.py:468 | guard GD-15 |
| GT-17 | alphaevolve: `_wrap_with_fallback` turns failed lofts into bounding boxes; every benchmark part topology_score 1.0 incl. NC 0.21 plates | n/a | silent fallback; "success" = a solid exists; in-memory validity only (Scan2Step step_analysis.py:211-236) | none (the fallback was the "fix") | AE: seed_recon.py:772-797; benchmark/scores/benchmark_results.json; 073aadf | guard GD-15 + GD-01 |
| GT-18 | alphaevolve: non-reproducible score; 83% of mutations 0.0; surface IoU ~0.01; 0.750 on 10 samples really 0.679 | n/a | unseeded RANSAC; wrong formula in prompts, missing keys; 12% grid coverage; tiny sample | seed 42 (44b4b26); prompts fixed; 32 768 points (059ab14); 20 samples | AE: 44b4b26, 059ab14; Forgetful #332, #423, #549 | guard GD-15 |
| GT-19 | alphaevolve: types `plane`, `boolean_edge` emitted, always scored 0 | n/a | output vocabulary not validated | valid types listed in PROBLEM_CONTEXT | AE: STATUS.md 2026-03-19; Forgetful #329 | guard GD-15 (validate tool names against `rt`) |

### LP: loop, API and infrastructure

| id | symptom | junction signature(s) | root cause | fix | source | toolbox action |
|---|---|---|---|---|---|---|
| LP-01 | hotend r1-r5 all "no file"; part 6 r5; 17_oldgate r4-r5 | n/a | model CLI wrote no program (usage limit, INFERRED from specs/loop-robust.md) | quota backoff / exit 75 | RL: recon2_hotend, recon2_6, recon2_17_oldgate history.json; MS: tools/recon/specs/loop-robust.md | guard GD-16 |
| LP-02 | part 21 r2: p95 0.38 -> 1.37 | `blend:torus\|cylinder+plane\|round` | `RadiusNthSelector(0, directionMax=True).fillet(6)` picked the wrong circles | r3 revolved bore half-section; p95 0.007 | RL: recon2_21 r2->r3 | new rt function `rt.revolve_profile`; guard GD-11 |
| LP-03 | part 30: chained `pushPoints().circle()` keeps only the last circles in `vals()` | `cylinder\|plane\|circle\|convex` | CadQuery stack semantics | one Workplane per radius | RL: recon2_30 r2 | already covered by rt.hole (one call per hole) |
| LP-04 | part 33: `offset2D` output breaks taper extrude; LocOpe taper fails on tangent arc chains; part 36 r1 OCC taper fails | drafted `cone\|plane` | OCC taper on tangent chains | `BRepOffsetAPI_DraftAngle` | RL: recon2_33 r1, recon2_36 r1 | new rt function `rt.drafted_prism` |
| LP-05 | service one restart from dead for 5.5 h | n/a | delegated `pip install -e .` repointed the global editable .pth | rewrite the .pth | MS: mem:project_routing_run_hijacked_editable_install.md | guard (process, not toolbox) |
| LP-06 | 3MF upload bare 500 on behemoth; zero-normal STLs rejected | n/a | missing loaders; engine read normals | MeshLoadError, provisioned loaders (5548e1a); round-trip uploads through the loader (0830cf0) | MS: 5548e1a, 0830cf0 | guard (loader, not toolbox) |
| LP-07 | 603 s for a 1 s answer: native engine hangs, edgebuild rebuilds in 1.0 s after NativeTimeout | n/a | engine hang on fine small features | not fixed; env timeout | MS: mem:project_cost_driver_is_small_features.md | guard (routing, not toolbox) |
| LP-08 | edgebuild 5400 s, no RESULT at 165k triangles | n/a | merge/corner phase does not terminate | feature path / loop | MS: mem:project_edgebuild_cannot_do_165k.md | already covered by the loop |

---

## 2. Proposed toolbox additions

Every function inherits the existing contract (`recon_tools.py` docstring): takes and returns a
one-solid Workplane, builds blends from `makeCylinder`/`makeCone`/`makeTorus`/`makeSphere` plus
booleans, never calls cadquery `.fillet()`/`.chamfer()` except where stated, and must pass a
**re-read** check (GD-01). Ranked by the number of errors each prevents (ids in brackets).

1. **`rt.round_primitive(solid, p0, p1, n_a, n_b, radius, convex=True)`** rounds (or, with
   convex=False, fillets) the straight edge p0-p1 between planes with outward normals n_a, n_b.
   It removes the edge wedge and adds or removes a cylinder of `radius` whose axis is offset along
   the bisector.
   - Faces: exactly one CYLINDER face of `radius`, tangent to both planes, bounded by two straight
     edges.
   - Replaces `rt.edge_round`'s cadquery fillet when that fillet goes non-analytic, or when a
     tangent chain carries different radii.
   - Prevents: NA-01, NA-07 (with rt.full_round), BO-02, BO-03, BO-04, BO-05, BO-08, BO-09,
     BO-11, BO-13, BO-19, BO-20, BO-22, BL-10. **14 errors.**
2. **`rt.tangent_profile(plane, segments, fillets) -> Workplane (2D wire, then extrude or cut)`**
   solves a plan outline of lines and arcs with every requested tangent fillet in closed form
   (line-line, line-circle, circle-circle), as part 17's own solver did. It works in a local frame
   near the origin and places the solid afterwards.
   - Faces after extrusion: PLANE for each line, CYLINDER for each arc and each plan fillet, with
     radius and axis equal to the solved values. Tangent points are shared vertices, never
     cadquery 2D fillets.
   - Prevents: BO-06, BO-07, BO-14, NA-03 (part 14), RT-04, RT-05, DM-03, DM-05, DM-16. **9 errors.**
3. **`rt.corner_blend(solid, vertex, rounds)`** blends the vertex where 2 or 3 rounds meet. It
   builds a SPHERE patch when the radii are equal. With one torus-producing pair it builds a TORUS
   clipped to its own sector (`tor.intersect(sector_box)`, never a whole torus). When the torus is
   a spindle (R < r), it emits it and relies on `canon.canonicalize_step`
   (DEGENERATE_TOROIDAL_SURFACE).
   - Faces: sphere, or torus with R and r equal to the neighbouring rounds' axis offset and
     radius.
   - Prevents: NA-01, NA-02, NA-03 (part 19), NA-08, BL-02. **5 errors**, and it covers the only
     loop part left below 100% (part 6, 49/52).
4. **`rt.edge_chamfer(solid, p0, p1, n_a, n_b, d)`** plus **`rt.countersink(solid, top, center,
   radius, head_radius, angle_deg)`**.
   - edge_chamfer makes a PLANE chamfer between planes by cutting a prism. On circular edges it
     makes an exact CONE.
   - countersink cuts one coaxial CONE of the given included angle down to the pilot hole (the
     CYLINDER).
   - Replaces `.chamfer()`, which fails on pocket and slot wires.
   - Prevents: MF-03 (4 parts), MF-04, BT-05, DM-01. **7 errors** (MF-03 counts 4).
5. **`rt.revolve_profile(axis_origin, axis_dir, segments)`** revolves a half-section of lines and
   arcs through 360 deg about the axis, then canonicalizes.
   - Faces: CYLINDER (line parallel to the axis), CONE (oblique line), PLANE (line perpendicular to
     the axis), TORUS (arc off the axis, spindle allowed via canon), SPHERE (arc centred on the
     axis).
   - Bore = innermost loop enclosing the axis (DM-13).
   - Prevents: BO-16, BO-15 (r3 fix), LP-02, MF-01, DM-13. **5 errors.**
6. **`rt.drafted_prism(plane, profile, height, draft_deg, top_round=0.0)`** extrudes a line/arc
   profile with a draft using `BRepOffsetAPI_DraftAngle` (not taper-extrude). top_round rounds the
   top rim with `rt.round_primitive` on the straight runs and TORUS corners on the arcs.
   - Faces: PLANE (drafted lines), CONE (drafted arcs), CYLINDER and TORUS for the rim round.
   - Prevents: BO-10, NA-04, DM-07, LP-04, SG-08. **5 errors.**
7. **`rt.radial_fillet(solid, axis_point, axis_dir, radius, span, convex)`** builds a partial
   cylinder whose axis is perpendicular to the build axis. The boolean order is fixed:
   `Cut(shape, corner)`, then `Fuse(keep, Common/Cut(corner, cyl))`.
   - Faces: one CYLINDER face of `radius` over the measured span.
   - Prevents: BO-19, BL-01, ID-01 (identity by axis+span inside the call). **3 errors.**
8. **`rt.full_round(solid, edge_pair, thickness)`** rounds a wall or rib end with r = T/2 as a
   CYLINDER (or a TORUS on a curved rib) fused onto the trimmed end, never a fillet. The sibling
   `rt.round_primitive` does not handle r = T/2.
   - Faces: one CYLINDER of radius T/2 tangent to both side planes.
   - Prevents: NA-07, and part 16's full-round periphery (loop r1 built it from 8 tori).
     **1-2 errors.**
9. INFERRED and lower evidence:
   - **`rt.oblique_hole(solid, entry_plane, axis, radius)`**: exact cylinder cut across a torus or
     cylinder (ED-05, ED-11).
   - **`rt.slot(solid, plane, p0, p1, width, depth)`**: bounded at the floor (BL-07).

## 3. Proposed decision-tree rules (signature -> tool)

Each rule is for `junction_tree.TREE` or for `advise()`. The backing error ids are in brackets.

- **DT-01** `blend:cylinder|plane+plane|round` / `|fillet` -> `rt.edge_round`, but
  `rt.round_primitive` when the edge belongs to a tangent chain whose blends have different radii,
  or when `rt.edge_round` raises its non-analytic ValueError. [NA-01, BO-02, BO-03..BO-13]
- **DT-02** `blend:torus|cylinder+plane|round` with minor r > boss radius / 2 (spindle, R < r) ->
  `rt.boss(top_round=r)`, then canon. The same record as a three-way vertex blend ->
  `rt.corner_blend`. [NA-02, NA-06]
- **DT-03** Take a torus blend's major radius from the coaxial cylinder's radius minus or plus the
  minor radius, never from the torus patch's own fit. [DM-15, ID-02]
- **DT-04** `blend:cylinder|plane+plane|*` whose axis is perpendicular to the extrusion axis ->
  `rt.radial_fillet`. [BO-19, BL-01, ID-01]
- **DT-05** `blend:cylinder|cylinder+cylinder|fillet`, `blend:cylinder|cylinder+plane|fillet` and
  `blend:cylinder|plane+plane|fillet` when all axes are parallel to the extrusion axis (plan-view
  blends) -> `rt.tangent_profile`. Never a 3D `.fillet()` between parallel cylinders.
  [BO-06, BO-07, BO-14, NA-03, RT-04, RT-05]
- **DT-06** `blend:torus|cone+plane|round`, and any `cone|plane|line|*` family carrying one
  common draft angle -> `rt.drafted_prism(top_round=...)`. [BO-10, NA-04, DM-07, LP-04]
- **DT-07** Draft versus round versus chamfer at a hole or rim:
  - A "draft" in the facts that is confined to a band whose height is about equal to its radial
    offset, next to a circle junction, is a round -> `rt.hole(mouth_round)` or
    `rt.ring_fillet(convex=True)`.
  - If the section profile is a straight 45 deg run, it is a chamfer -> `rt.hole(mouth_chamfer)` /
    `rt.edge_chamfer`.
  - Only a draft spanning the whole wall height is a cone.
  - Decide by the section profile shape (arc versus line), not by the draft number.
  - [BT-01, BT-02, BT-03, BT-04, BT-05, BO-12, BO-18]
- **DT-08** Coaxial or parallel cylinders built with shared axes by construction (one axis
  variable). Never fit axes independently and intersect them. [ED-08, DM-11]
- **DT-09** `cone|cylinder|circle|convex` + `cone|plane|circle|convex` with a cone included angle
  of 60-120 deg -> `rt.countersink`. At about 90 deg with a small depth -> `rt.hole(mouth_chamfer)`.
  [DM-01, BT-05]
- **DT-10** Before classifying, merge same-surface regions (axis 1 deg, 0.5% diag, radius 2%). A
  `cylinder|cylinder` tangent junction between coaxial equal-radius regions is one cylinder, not a
  blend. [SG-01, SG-04]
- **DT-11** Order of operations: base prism or revolve -> holes and bores -> cross holes -> blends
  -> corner blends. Holes are cut after profile offsets. Tori are clipped to their sector.
  [BL-02, BL-05, BL-06, BL-08, BL-10, ED-12]
- **DT-12** One physical feature = one primitive spanning its whole extent. Never per-level arcs or
  face-by-face assembly of partial cylinders. [BL-04, ED-02, ED-03, ED-04, SG-14]
- **DT-13** Planes within 2 deg of each other along a junction are one plane (or one draft). Never
  intersect them. [ED-10]
- **DT-14** A circular section on a 24-gon or less with sagitta ratio > 8 is a designed prism, not
  a cylinder. A cone fit with half-angle about 0 is a cylinder. A sphere has one radius about one
  centre. Symmetric non-convex profiles (cross, star, L/U/C) are extrusions. [SG-07, SG-11, SG-12]
- **DT-15** All junctions are coaxial circles around one axis (a turned part) -> `rt.revolve_profile`.
  [BO-16, MF-01, DM-13, LP-02]

## 4. Guards for the loop and gate (referenced as GD-nn above)

- **GD-01** Judge every round on the **re-read STEP** (after canon), never on the in-memory shape.
  This covers validity, face types and volume. [BL-01, RT-01..RT-10, NA-06, SH-03, SH-06, GT-17]
- **GD-02** Non-analytic census by FACE surface type on the re-read file, counting B-spline,
  SURFACE_OF_REVOLUTION and offset/extrusion surfaces. Report it every round. A best round with a
  non-analytic face is flagged even when curved == patches. [GT-01, GT-02, GT-09, GT-12, NA-02,
  NA-03, NA-04, NA-12]
- **GD-03** Report the true miss count (patches - curved), not only the 15-item list. Feature
  completeness enters the stop rule. [GT-03, GT-07]
- **GD-04** Feature identity = axis line + overlapping span, never radius. [ID-01]
- **GD-05** Before calling a patch "missing cylinder", fit cylinder and torus and compare residuals
  on the mesh. Adjudicate by point-to-surface, never by the metric one fit minimises.
  [ID-02, ID-03, GT-10, BO-22, SG-05]
- **GD-06** Every invalid round carries `invalid_faces` (type, area, location) (now in
  recon_loop.py:353). [GT-04, RT-04, RT-05]
- **GD-07** Rank rounds and gate "no loss" at the serving site, by the product instrument; volume
  is only a diagnostic. [ID-04, GT-06, GT-13]
- **GD-08** Accept per feature, report recovered AND invented. Never relax support to buy
  cylinders. [ID-05, ID-06, ID-08, SH-04]
- **GD-09** Dimensions come from facts and mesh measurements, never from renders or nominal inch
  guesses. The brief must say so. [BT-02, DM-02]
- **GD-10** Reject ellipse, spline and loft primitives unless the facts show a non-circular curve.
  [NA-05, NA-13, SG-16]
- **GD-11** Probe fillets and cutters per edge. Cutters overshoot coincident faces (no tangent or
  coplanar boolean contact). [NA-09, BL-09, LP-02]
- **GD-12** Repair is scoped to the faces that re-read invalid. It never converts an intact circle.
  [NA-11, RT-01]
- **GD-13** Solid count equals the mesh body count (`trimesh.split()`). [SH-05, BL-10]
- **GD-14** When the mesh gives no evidence (patches = 0, drafted walls, sparse or decimated
  input), say so. Do not score it as 0 or as 100%. Add a pre-flight census: seed-band fraction and
  small-radius share. [ID-07, GT-05, GT-11, SG-09, SG-15]
- **GD-15** The evaluator is outside the loop's reach. Every candidate failure is caught and
  reported, with no silent fallback to a box. Tool names are validated against `rt`.
  [GT-14..GT-19, MF-05]
- **GD-16** Stop on relative convergence (RECON_STOP_REL). A round whose program is unchanged ends
  the loop. A quota "no file" is retried with backoff, never recorded as a construction failure.
  [GT-08, LP-01]

## 5. Coverage and gaps

- The 2026-09-21 runs did not archive per-round STEP files, only `best.step`. So face-level claims
  for intermediate rounds rest on the report JSON.
- alphaevolve never built fillets or tori (its memory `state.md` records a user veto of boolean
  CSG). Its rows are about primitive classification, lofts and metric gaming. None of them is a
  blend.
- Not mined:
  - alphaevolve `runs/*.log` (absent), `data/` (42 GB, listed only), and its uncommitted working
    tree (skimmed).
  - `refs/stl2step/FINDINGS-*.md`, beyond the rows cited.
