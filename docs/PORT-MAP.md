# Port map — the model of stl2step we are reproducing

Working document for the v2 parity port. **Read this before touching the refit code.**

Sources: `refs/stl2step/docs/METHOD.md`, `AGENTS.md`, the 18 `FINDINGS-*.md` lane
reports, `refit_segment.cpp` (the 85-line spine), and diagnostics run against the
reference binary on 2026-09-03.

---

## 0. The synthesis — five arms, one claim

Sections 1-8 are particulars. They are consequences of this, and if you find yourself
memorising them you are reading the wrong section. **The claim:**

> A CAD-exported mesh is not data *about* a shape. It is the output of a deterministic
> program that *had* the shape. The task is not reconstruction, it is **inversion** —
> recovering that program's inputs.

Everything else follows.

**A. Invert, do not fit.** Parameters of program output are exactly recoverable, so
`R = w / (2 sin(θ/2))` is an inverse, not a regression. *The law is simultaneously the
recovery and the validity test:* a chain is accepted because it obeys an equal-step law,
not because a residual is small. Hence Tier 1 is parameter-free — there is no tolerance
to tune, and reaching for one is the wrong instinct.

**B. The exporter's settings are global to the file, not per feature.** So calibration
intersects across bands: one `d`, one `α` for the whole export. A component whose bands
cannot share one setting is a *mixed export*, and the engine declines wholesale rather
than fitting each band separately. Global consistency is the evidence; local fit is not.
This is why `lawCalibrate` is a maximum-interval-stabbing and not an intersection.

**C. Grouping dominates fitting, so claim order is confidence order.** The law applies to
a chain, not a triangle; wrong grouping makes perfect arithmetic useless. The two failure
modes are *absorption* (a shallow arc swallowed by a plane) and *chimeras* (two
cylinders merged and fitted to a radius belonging to neither). Hence L before B1 before
A3 — the most certain claimant goes first, because plane growth is greedy and destroys
arcs irreversibly. Stage order is forced, not conventional.

**D. Signal has a regime; the bands are its domain of validity.** Inversion recovers only
what the tessellation still encodes — a 10° arc across two facets carries almost nothing.
So `coarseFusionBand` (500-1200) and `archChainBand` (500-8000) are not tuning knobs,
they mark where the signal exists. This arm *predicts* `adaptCoarseSegmentParams`: in a
coarse regime the angular gates must widen or grouping fails. It also makes the
reference's own gaps (Body11: 127 of 583) an honest ceiling rather than a defect.

**E. Recognition and construction are different problems, with a firewall between them.**
Correct surfaces must still become a valid closed solid, and OCCT is unforgiving; nearly
all the reference's engineering pain lives here. The firewall has two rules — when
construction fails, revert **wholesale** rather than ship a mixed shell (R2); and never
trade volume correctness for face count (FINDINGS-VOLUMEFIX). Its deepest consequence:
**when the problem class permits, sidestep construction entirely.** The prismatic route
is not an alternative code path, it is the engine declining to solve the hard
construction problem — fit arcs in 2D where closure is checkable, extrude, and curved
walls are analytic *by construction*.

**Corollary of D and E:** the observable counters are *regime-dependent reports*. The
same field name has three producers depending on which route ran. A counter that will
not move under any local change is a routing error, not a tuning problem.

**What this says about our port:** it has been implementing **C** and the hard half of
**E**, in the wrong order, without **D**'s parameters, for a fixture whose answer is
**E**'s sidestep.

### Prediction log

Written before the check, per `ai-intuition`. A `pending` line is the only proof a
prediction was a prediction.

- `P1: adaptCoarseSegmentParams (arm D) moves handle-lock's segmentation toward the
  reference's 13 planes / 15 cylinders | check: pytest -k "handle-lock and trueform" |
  result: CONFIRMED — planes 15 -> 13, exactly the reference's segmentation; cylinders
  14 vs 15, radii 10 vs 11 still short.`
- `P2: the one missing cylinder and eleventh radius on handle-lock are a large-R arc
  absorbed into a plane, so porting peelLargeArcStripsA2b (arm C, absorption) raises
  smoothCylinders 14 -> 15 and smoothDistinctRadii 10 -> 11 | check: pytest -k
  "handle-lock and trueform", read the mismatch dict | result: REFUTED — cylinders
  stayed 14, radii 10. The peel runs, sees 6 unclaimed provisionals of >=3 triangles,
  and BOTH detectors reject all 6. Nothing was absorbed.`
- `P3: raising thetaPlane to 15 degrees makes plane growth more absorptive, so the peel
  matters more after P1 than before | result: MOOT — P2's refutation makes the premise
  irrelevant; nothing is being absorbed either way.`

**Arm correction forced by P2.** Instrumented after the refutation: all 14 cylinders come
from stage **L**, and B1 contributes **zero**. The reference accepts **15** law bands where
we accept 14. So the missing cylinder is a missing law band — the gap is in arm **A/B**
(the tessellation law and its per-export calibration), not arm **C** (absorption). I had
attributed a recognition shortfall to a grouping stage because grouping was the arm I had
most recently been working in.

- `P4: the 15th band is a chain our lawChainAccept rejects at one of the four Tier-1
  tests (equal-theta, R-consistency, common-axis, on-surface), not one we never seed —
  since our calibration already reproduces the reference's dLo/dHi exactly, the seeding
  and the export-level fit are right | check: instrument law_chain_accept on handle-lock
  and count accept/reject per test | result: REFUTED — the seeding is exactly what is
  wrong. DIAG_LAWCLAIM on the reference names its 15 bands; ours reproduces 14 of them
  to 5 decimals and misses precisely rid=443, n=6 tris, N=3, R=20.001531. Censused every
  chain we ever offer lawChainAccept: ZERO with R in (19,21) accepted, and the eight
  rejected there are different triangle sets (nearest: 6 tris from 216, R=20.403). That
  chain is never offered.`

**Arm correction forced by P4.** The gap is not a test being too strict, it is a whole
seeding pass that was never ported: `refit_grow.cpp:2255`, a SECOND law pass over the
triangles the first pass left, re-clustered with the TIGHT normal gate held against the
seed normal rather than the running mean, plus two absorption loops that pull still-loose
facets into an accepted band. A three-generator arc cannot survive the first pass — its
strips are a minority inside a chart whose running mean is set by the long bands, so the
gate walks past it. Our `_cluster_law_strips` already carried the `seed_only` parameter
and both constants: the pass was anticipated and then forgotten. Twice now the answer has
been "a stage of the reference we do not run", not "a threshold we set wrong" — arm E's
firewall (recognition is not construction) has a sibling: **a missing pass looks exactly
like a strict test, and only the reference's own census tells them apart.**

- `P5: porting the leftover second pass raises handle-lock smoothCylinders 14 -> 15 and
  smoothDistinctRadii 10 -> 11, the new band being R~20.0015 over 6 triangles | check:
  pytest -k "handle-lock and trueform", read the mismatch dict | result: CONFIRMED —
  smoothCylinders 14 -> 15, smoothDistinctRadii 10 -> 11, exactly the two counters named.`

**The unpredicted half is the larger one.** `smoothMaxDevMM` fell from **0.6295 to
2.32e-05** — four orders of magnitude — and `smoothMaxEdgeTolMM` with it (0.5960 ->
2.12e-05). The missing band was not a sixteenth face nobody would notice: those six
triangles were being absorbed into a *neighbouring* surface whose fit then had to
stretch 0.63 mm to cover them, and that stretch was the fixture's worst deviation.
One unported seeding pass was setting the accuracy ceiling for the whole part.

**Cost:** 96 s -> 171 s on handle-lock (908 tris), after scoping the absorption ring to
each band's own edges instead of the reference's per-band O(nTri) scan. Body11 (15300
tris) and Body28 (14126) are the real test of whether that scoping is enough.

- `P6: handle-lock's remaining parity gap is ENTIRELY route P, not segmentation. The
  reference's own DIAG_PRISM census for it is nPlane=13 nCyl=15 -- identical to ours. Its
  reported smoothPlanes=23/smoothCylinders=17/facesBeforeUnify=40 are the OUTPUT of
  buildPrismatic (2 slabs, 30+10 faces, fuse to 40), not of segmentation. So when route P
  lands, handle-lock's counters jump 13->23 and 15->17 and the overlay volume moves
  16038.862197 -> 15868.832006 with no segmentation change at all | check:
  STL2STEP_PRISM_DIAG=1 on handle-lock, compare DIAG_PRISM census vs RESULT counters |
  result: pending`

**I spent a session tuning the wrong stage.** The handle-lock law-band work was measured
against 23/17 -- numbers the reference produces on a route we do not implement. Its
segmentation agrees with ours to the unit. Arm E again, from the other side: I compared our
*recognition* against their *construction* and read the difference as a recognition defect.

**Where the time actually was — measured, not guessed.** I predicted the absorption loop
was the bottleneck and was *refuted twice over*: `_absorb_leftover_into_bands` is 13.0% on
handle-lock and **0.1%** on Body11 (4.3 s of 3189 s). The cost is `law_chain_accept`
(71.1% on Body11) and inside it `nearest_at_angle`, which rescanned every chain point
recomputing `azimuth` per query: 25.3M scalar calls on a 908-triangle fixture, 36% of
runtime, for a frame that is **constant for the whole chain**. Hoisting the azimuth array
out of `extract_chain` gave 171 s -> 82.5 s, i.e. it also paid back the 96 s baseline that
predates the new pass. Third refuted prediction in a row, all with the same shape: I
reached for the explanation from whatever area I had most recently worked in.

---

## 1. What the engine is

Two stages, user-selected, sharing one front end (read, weld, split into manifold
components, sew dirty components, build, unify coplanar, write STEP).

| Stage | Mode | Produces |
|---|---|---|
| 1 | `verbatim` (default) | Byte-faithful faceted B-Rep. One planar face per triangle, coplanar merge afterwards. Never invents geometry. |
| 2 | `trueform` (`--smooth`) | Stage 1 **plus** analytic recovery: tessellated curved regions become real `Geom_CylindricalSurface` faces. |

Only clean components are refit. A component needing the sewing repair path is skipped
(`smoothSkippedComponents`), never refit.

## 2. The central idea

A CAD-exported mesh is not a noisy sample; it is the deterministic output of a
tessellator that followed a **law**. It caps chordal deviation at some `d` and normal
change at some `α`, then divides an arc of extent `Φ` into `N = ceil(Φ/θmax)` equal
steps. Therefore, for a chain of strips of chord `w` meeting at dihedral `θ`:

```
R = w / (2 sin(θ/2))
```

This is an *inverse*, not a fit: it reproduces the CAD radius to mesh precision. Two
disciplines make it robust, and both are load-bearing in the port:

1. **The law's parameters are never assumed** — `d` and `α` are estimated from the
   mesh's own band statistics (`lawCalibrate`).
2. **The law is also the validity test** — a chain is an arc only if its strips really
   do satisfy an equal-step law, which is what separates arcs from coincidental
   near-flat geometry.

> METHOD.md §3: *grouping, not fitting, is the hard part.* The two characteristic
> failures are **absorption** (a shallow arc swallowed by an adjacent plane) and
> **chimeras** (strips of two different cylinders merged and fitted to a blended
> radius belonging to neither). This is why stage L runs before plane growth.

## 3. The pipeline — `refit_segment.cpp:runStages`

```
adaptCoarseSegmentParams   <-- MUTATES PARAMS BEFORE ANYTHING (see §5)
deriveTols
  A1  chartsA1             sharp-edge charts (union-find on dihedral <= thetaSharp)
  A2  growProvisionalA2    running-PCA provisional planes, TOTAL partition
  L   claimLawBandsL       tessellation-law arc bands   <-- BEFORE B1 and A3
  B1  claimCylindersB1     cylinder seeds + G1..G5 gates
  C1  claimFilletsC1       plane-plane fillet strips (if doFillets)
  A3  commitPlanesA3       plane commit, + peelLargeArcStripsA2b inside it
  D   buildTopologyD       boundary chains, loops, and the RefitStats census
```

Then, per component, in `stl2step.cpp`:

```
refit::buildFaces  ->  probe: IsClosed && BRepCheck valid && volume within budget
                       accept -> usedRefit = true
                       reject -> R2 revert: rebuild verts/edges FRESH, faceted build
```

And **over the top of all of it**, the prismatic route (§4), which for a qualifying
component replaces the whole 3D face-building problem.

## 4. Three routes a component can take

This is the distinction the port missed for a long time.

**Route P — prismatic rebuild** (`refit_prism.cpp`, `refit_prism_build.cpp`,
`refit_profile.cpp`). Detected from the recognition results: all cylinder axes
parallel, planes split cleanly into caps (normal along axis) and laterals. Then:
slice at cap levels, fit each level's closed 2D profile as lines and arcs using the
same inverse law, extrude, fuse. *Curved walls are analytic by construction — there is
nothing to repair afterwards.* METHOD.md §4.

**Route G — general analytic build** (`refit_build.cpp`). Per-region faces with
analytic boundary chains: plane|plane, plane|cylinder and cylinder|cylinder
intersection curves, pcurves and seams on cylindrical surfaces, the explode ladder
when a region will not build.

**Route R — revert to faceted.** The probe fails; the component is rebuilt verbatim.
`usedRefit` stays false and **every `smooth*` counter contributes zero**
(`stl2step.cpp:821`).

**And a fourth outcome, which is easy to mistake for R.** `buildFaces` can succeed while
the explode ladder has turned *every* region into its own triangles. Then `usedRefit` is
true, so the segmentation stats ARE reported, but the built census
(`stl2step.cpp:955`) sees no cylindrical face and counts the component as reverted:

| outcome | stats reported | built census | signature |
|---|---|---|---|
| P prism | from `countSurf` on the solid | built | `facesBeforeUnify` small |
| G built | from the D census | built | `smoothBuilt* > 0` |
| **G exploded** | **yes** | **reverted** | `smoothPlanes > 0` **and** `smoothBuilt* == 0`, `facesBeforeUnify == triangles` |
| R2 revert | none (all zero) | reverted | `smoothPlanes == 0` |

Distinguishing G-exploded from R2 is what `smoothPlanes` tells you, and it decides
whether a fixture needs analytic construction at all.

### Measured route per corpus fixture (2026-09-03, reference binary)

| fixture | tris | prism `ok` | route | evidence |
|---|---:|---|---|---|
| cube | 12 | 0 (`failedCond=1`) | G built | 6 planes, trivial |
| S09 | 54 | 0, both components | G built | 28 planes, 14 facet faces, 8 cylinder seeds rejected |
| nonprismatic-control | 96 | 0 (`failedCond=3`, `nOblique=1`) | **R2** | `smoothPlanes 0`, reverted 1 |
| handle-lock | 908 | **1** | **P** | `nCyl=15 nPlane=13 nCap=3 nLat=10` |
| Body11 | 15300 | — | **G exploded** | planes 1344, cyl 419, facetFaces 1513, **built 0**, reverted 2, `facesBeforeUnify == 15300` |
| Body28 | 14126 | — | **G exploded** | planes 499, cyl 340, facetFaces 4613, **built 0**, reverted 1, `facesBeforeUnify == 14126` |

**The consequence for this port, and it is large.** No fixture in the corpus needs
plane|cylinder or cylinder|cylinder intersection curves, partial-cylinder faces, pcurves
or seams. Two fixtures are planes-only, one is prismatic, and the remaining three end
faceted — one by R2 revert and two by exploding. Everything M3b's cylinder-face work and
all of M3c were built for is **off the parity path**. What parity needs instead is
segmentation that produces the right *counts* (1344 planes / 419 cylinders on Body11), a
build that explodes correctly, and route P for handle-lock.

That is also the road the reference itself abandoned: lanes A, C, E, F, G, CYLEDGES,
PARTIALFACES and RIDS drove route G at handle-lock to 16 built cylinders with a 121%
volume blowout, VOLUMEFIX retreated to one cylinder to keep the volume honest, and only
then was route P written. The FINDINGS files are not documentation of how the code works
— they are a record of which paths lead nowhere.

**Only handle-lock takes route P.** Its golden decodes directly from the prism build:

```
DIAG_PRISMBUILD slab=0 faces=30 vol=14668.27 valid=1
DIAG_PRISMBUILD slab=1 faces=10 vol=1200.56  valid=1
DIAG_PRISMBUILD fuse-k=1 faces=40                     -> facesBeforeUnify 40
DIAG_PRISMBUILD usd-try faces P=23->23 C=17->15        -> smoothPlanes 23,
                                                          smoothCylinders 17,
                                                          smoothBuiltCylinders 15
```

So for a prismatic component the `smooth*` counters are **counted off the rebuilt
solid** (`refit_prism_build.cpp:1137,1167` `countSurf` -> `rs.stats`), *not* off
segmentation. No amount of fixing general-path face building can make our
segmentation-derived counters reach them.

## 4b. Route P in full — why it is the easy route, not the exotic one

Read whole: `refit_prism.cpp` (377), `refit_prism_build.cpp` (1188), `refit_profile.cpp`
(1290). It is arm **E**'s sidestep, and every part of it is a consequence of the arms.

**Selection is a cheap predicate over the RegionSet, not geometry.** `detectPrismatic`
(RULE 5.1) is six conditions, all with self-computed tolerances (RULE 4.2a — "no degree
constants"): (1) at least two cylinders; (2) common axis, max pairwise `sin < tauAx`;
(3) no oblique planes — each plane is a cap (`|n·â| > 1-tauAx`) or a lateral
(`|n·â| < tauAx`); (4) at least two distinct cap levels, clustered at `tauLvl`; (5) every
cylinder spans a contiguous run of levels; (6) signed cap-area closure,
`|Σ area·(n·â)| < tauFit · Σ perimeter`. `tauSurf = max(5e-5, 4·weldTol, 1e-6·diag)`,
`tauAx = max(1e-6, 2·tauSurf/hMin)`. Our fixtures fail at 1 (cube, S09: no cylinders) and
3 (nonprismatic-control: `nOblique=1`); handle-lock passes all six.

**Then it changes the problem's domain.** Slice the mesh at each cap level, chain the
2D segments into closed loops, and fit *there*. Two dimensions is where closure is
checkable — signed area, exact loop closure, area reconciled against the measured cap.

**The alphabet is closed: line or arc, nothing else.** A profile that cannot be said in
two primitives is not said at all. This is why route P cannot fail the way route G
fails: there is no seam, no pcurve, no surface-surface intersection to miss.

**Arc radii are not fitted from the slice.** The slice points lie on mesh chords, not on
the circle. They are used only to *associate* a run of the loop with a recognised
cylinder region (`cylAssocTol = max(tauFit, 4·chordSagitta, 4·maxVertexDev)`); the radius
then comes from that region's law-recovered value. Arm A: measure by inversion, never by
re-fitting a chord chain.

**Ambiguity resolves to the safe primitive.** RULE 5.3a: if the candidate arc's sagitta
`R(1-cos(φ/2))` is below `tauFit`, it is indistinguishable from a line at mesh
resolution, so emit a **line** and flag `declinedAmbiguous`. Never guess a radius.

**Construction is then trivial and total**: wire per loop, planar face with holes,
`BRepPrimAPI_MakePrism` per slab, deterministic `Fuse` with `GlueShift`, one
`UnifySameDomain`. Curved walls exist as cylinders by construction.

**Acceptance uses the law a second time.** `tryStageP` accepts only if the solid is
closed, BRepCheck-valid, and the volume is off by *exactly* the predicted arc-versus-chord
defect: `vRef = meshVol - Σ(R²/2)(θ - sin θ)·h`, then `|vol - vRef| ≤ budget` **and**
`|vol - meshVol| ≤ 1.05·dAbs`. It never asks "is the volume close"; it asks "is it wrong
by the amount the law says it must be". Failing that, `prismNoteStageP(false, true, ...)`
and the component falls back — arm E's firewall.

**And only on acceptance** does it write `rs.stats.planes = nPlanes;
rs.stats.cylinders = nCyls` from `countSurf` on the built solid, zeroing the facet
counters. That single assignment is why handle-lock's golden is unreachable from
segmentation.

## 5. Cross-cutting rules that bite

- **`adaptCoarseSegmentParams`** (`refit_segment.cpp`): in the coarse band it raises
  `thetaPlaneDeg` 2 -> **15** and `thetaCylHiDeg` 60 -> **70**, *before* `deriveTols`.
  A 7.5x change to the plane-growth angle. **Not ported as of 2026-09-03.**
- **Band predicates** (`refit_internal.hpp`): `coarseFusionBand` = 500..1200 tris;
  `archChainBand` = 500..8000. Almost every coarse-band relaxation is gated on these,
  and FINDINGS-INT records that un-gating them breaks the small fillet fixtures. Do
  not widen them.
- **The `smooth-flat` second unify** (`stl2step.cpp:914-931`), gated
  `smooth && !forceSew && 500 <= nTri <= 1200`, exists for *"faceted islands (revert
  fallback and analytic+facet mixes)"*. A reverted component is therefore deliberately
  **not** byte-identical to verbatim.
- **Sort orders are load-bearing.** `sortRegions` on accepted and rejected keeps the
  census stable; the C++ parallelism must become deterministic ordering in Python.
- **Counters, precisely**: `smooth*` come from the D-stage census for route G, from
  `countSurf` on the rebuilt solid for route P, and are all zero for route R.
  `smoothBuilt*` are computed in `stl2step.cpp` after the build.

## 6. What the reference itself does NOT achieve

Targets to not chase past their real ceiling:

- **Body11**: 583 cylinders recognised, **127 built** (`tests/diag/body11/KNOWN-GAP.md`).
- **handle-lock GT**: 28 faces / 15 cylinders ideal; the general path historically
  reached 16 cylinders with an extra ~16 mm duplicate, and FINDINGS-VOLUMEFIX chose
  1 built cylinder + correct volume over 16 + a 121% volume blowout
  (*"correctness over count: volume-true + valid wins"*).
- Cones, spheres, tori are recognised and left faceted. No freeform/NURBS.
- Cylinders only at **N >= 6**; fillet strips 1-3 rows; asymmetric chamfers
  (`sL/sR >= 1.3`) rejected.

## 7. Port status (2026-09-03)

| reference file | lines | ported | notes |
|---|---:|---|---|
| `refit_segment.cpp` | 85 | **done** | `adaptCoarseSegmentParams` ported (P1) |
| `refit_grow.cpp` | 2512 | partial | A1/A2/B1/gates, L driver, `peelLargeArcStripsA2b` (P2), leftover 2nd law pass + absorption (P5). Remaining: C1 call site |
| `refit_lawband.cpp` | 979 | most | `lawband.py`; calibration matches reference exactly |
| `refit_math.cpp` | 1846 | partial | `refineCylinderRadius`, Pratt done; arch-chain family missing |
| `refit_chains.cpp` | 1046 | most | D stage in `segment.py` |
| `refit_build.cpp` | 4605 | ~40% | planes + cylindrical faces + M3c-1 constructors (unwired) |
| `refit_fillet.cpp` | 1612 | no | C1 |
| `refit_prism.cpp` + `refit_prism_build.cpp` + `refit_profile.cpp` | 2855 | **no** | route P — required for handle-lock |
| `dxf_export.cpp` | 326 | no | `--dxf` |

Ours (2026-09-03): `segment.py` 3753, `build.py` 1299, `lawband.py` 738,
`mesh_view.py` 149, `stats.py` 34 — about 6.0k Python against 17.9k C++. (The earlier
"build.py 2161" in this table was never true of any commit; `git show HEAD:` reads 1299.
A line count nobody re-measures is how a map starts lying.)

## 7b. The work order, derived from §0

Not "what failed last", but what the arms say must be true first. Each item names the arm
it serves; if an item cannot be justified by an arm, it is not on the list.

1. ~~**`adaptCoarseSegmentParams`** (D)~~ — **DONE** (P1). Planes 15 -> 13, the
   reference's exact segmentation.
2. ~~**`peelLargeArcStripsA2b`** (C)~~ — **DONE, and it was not the answer** (P2). It
   runs, sees 6 unclaimed provisionals, and both detectors reject all 6. Absorption was
   the wrong arm; the gap was a missing seeding pass, not a missing rescue.
2b. ~~**Leftover second law pass + absorption**~~ (`refit_grow.cpp:2255`) — **DONE**
   (P4/P5). Not on the original list at all: it was invisible until the reference's own
   `DIAG_LAWCLAIM` census named the band we were missing. Recovered the 15th cylinder,
   the 11th radius, and four orders of magnitude of `smoothMaxDevMM`.
3. **Route P** (E's sidestep). What handle-lock's golden actually measures — and P6
   showed it measures *only* that: the reference's segmentation census for handle-lock is
   nPlane=13 nCyl=15, identical to ours. 2855 lines that *remove* difficulty: a
   six-condition predicate, 2D fitting with a two-primitive alphabet, and prism+fuse
   construction. No pcurves, no seams, no surface intersections. `refit_prism.hpp` splits
   it into exactly four entry points, and one `STL2STEP_PRISM_DIAG=1` run yields the
   oracle for all four:
   - ~~P1 `detectPrismatic`~~ — **DONE** (`d17daa2`), exact on all five components.
   - **P2 `sliceProfiles` + `fitProfile`** — in flight. Gate:
     `tests/data/reference/handle-lock.profile.txt`.
   - **P3 `buildPrismSolid`** + wiring route P into the engine. Gate:
     `tests/data/reference/handle-lock.prismbuild.txt`, and P6 comes due here.
   - **P4 `writeProfileDxf`** — this IS `dxf_export.cpp`, not a separate track.
4. **Segmentation accuracy at scale** (C, D) — Body11 and Body28 need the right region
   *counts*, not analytic faces, since both end faceted. This is a recognition problem,
   not a construction one.
5. **`refit_fillet.cpp`** (C). `dxf_export.cpp` is no longer a separate item — it is P4.

**Tracking note.** `~/projects/CLAUDE.md` mandates `bd` for all task tracking, but
mesh2step is its own git repo with no `.beads/`, and the parent's database belongs to a
different repo. This section is the work order until someone decides to `bd init` here;
that is a repo-structure call, not one to make mid-port.

**Route G construction — the hard half of E — is not on this list.** No corpus fixture
reaches it. It was items 1 through 3 of the old plan, and it was the reference's own
abandoned road.

## 8. Method rules, learned the expensive way

1. **The reference is a deterministic source of truth. Read it before instrumenting.**
   Every defect diagnosed by measurement this session — the F4 tolerance rule, the
   missing cylinder branch in `ensureFaceValid`, the wire-orientation retry, the
   interval-stabbing calibration — was stated verbatim in the C++ or the FINDINGS.
2. **Translate; do not paraphrase.** Where the port translated, it matched the
   reference to six decimals on the first run. Where it paraphrased what a function
   "seemed to do", it was wrong (`lawCalibrate`).
3. **Know the route before optimising the road.** Hours went into general-path face
   building for a fixture that the reference rebuilds prismatically.
4. **Milestones are a delegation unit, not a porting unit.** Porting a function and
   then discovering it needs its caller is the signature of working without this map.
5. **A counter that cannot move is a routing error, not a tuning problem.**
6. **The map decays fastest exactly where work is happening.** On 2026-09-03 §7 still
   listed `adaptCoarseSegmentParams` and `peelLargeArcStripsA2b` as missing after both
   had shipped, and carried a `build.py` line count that matched no commit. The
   prediction log stayed honest because each entry is written once and then only
   appended to; the status table drifted because it is the part that must be *rewritten*
   to stay true. Re-read §7 against the tree whenever a prediction resolves, not at the
   end.
7. **Bit-identity in this code is a claim about OpenBLAS, not about arithmetic.**
   `np.dot` on a 3-vector is `ddot`, whose tail loop is an FMA chain: it equals
   neither `a*b + c*d + e*f` (35 553 mismatches per 100k) nor `m @ w`/dgemv (26 521).
   Only batched `np.matmul((n,1,3),(3,))` reproduces it exactly. Independently,
   `np.arctan2` is not libm's `math.atan2` and differs by 1 ulp on ~2.4% of inputs --
   enough to flip an `argmin` near-tie. When vectorising a numerically load-bearing
   scalar loop, assert `np.array_equal` against the scalar original on random data and
   keep a negative control; `allclose` would have passed every wrong candidate above.
8. **A missing pass and a strict test are indistinguishable from the inside.** P2 and P4
   both blamed a threshold and both were wrong; both times the answer was a stage of the
   reference we simply do not run. When a claim never appears, census what is *offered*
   before tuning what is *accepted*.
