# n15 — Arc-first detection: find the arcs, infer the cylinders

Tommaso's proposal, 2026-09-12: reverse the logic. Instead of fitting a surface to a
triangle region and hoping it pins an axis, find the circular ARCS in the mesh and infer
the cylindrical and conical surfaces they bound — which is how chamfers and incomplete
cylinders become visible.

Why it should work, and it is not a guess: the engine needs enough of a surface to pin an
axis (upstream's own chamfer-ring comment measures a 48-sided 45 deg frustum seeding at
5.307 deg facet fold and committing 60 deg arcs at residual 1.9e-2 mm against 1.9e-6 mm for
the correct whole-ring fit). An arc needs only its own points. A 20 deg sliver of a bore and
a one-facet chamfer both still have circular boundaries.
Related prior art: the reference's Route P (slice, fit the 2D profile as lines and arcs,
extrude) and ScanRuler's arc-coverage metric, which exists precisely because arcs survive
coarse meshing when surface fits do not (see `n14-external-prior-art.spec.md` §2a).

## The instrument

`scratchpad/arcfind.py` (~240 lines, stdlib only, no OCCT) and `scratchpad/arcsweep.py`.
Pipeline: read STL -> weld at 1e-6 -> sharp-edge graph (dihedral > 20 deg, plus boundary
edges) -> chain walk where only degree-2 vertices continue a chain, so a ring returns as one
chain and a junction never welds two features -> per chain: PCA plane, Kasa circle in it,
**relative** gates (planarity and radial residual each <= 2 % of the fitted radius, so a
0.8 mm bore is judged like a 30 mm bore) -> arc coverage as **360 deg minus the widest
angular gap** (ScanRuler's definition: it does not shrink because the mesh is coarse).

Arcs are then paired: equal radius + common axis + non-zero axial offset = **cylinder**;
different radius + common axis + small axial offset = **cone**; different radius + coplanar
= **annulus** (a counterbore shoulder or washer face). That last class was a bug found on
the first run — four flat annuli on `L10_tool_holder` were being reported as cones with
`h=0.000`.

## Measured, 203 models, variant normal

```
resolvable truth faces      428
engine matched (arm A)      233        recall 54.44 %
engine built                378
arc-visible truth faces     274
arc-visible AND missed      102        <-- the ceiling
                                       ceiling recall 78.27 %
```

**Accounting note, so this is not confused with CADScore.** This is a stricter denominator
than `cadscore.py`'s: it counts only the integer `matched` field per model and only
resolvable truth, where cadscore also awards fractional credit from `unmatched_radii`
(hence its 313/518 against this 233/428). The 102 is therefore a count of *faces*, not a
CADScore delta, and credit is **capped by the number of arc candidates at that radius** —
one arc-derived cylinder at R=2.0 is evidence for one face, not for all twelve bores that
share the radius. Without that cap the figure was 117; the capped 102 is the honest one.

## Two verified cases

`L09_cross_block`: arc evidence gives **R=2.5000** against truth 2.5, where the engine's
surface fit gave 2.490-2.630. The arc is the more accurate estimator on the same mesh.

`L10_tool_holder` (truth 8x R2.0, 4x R3.0, 4x R4.0, deflection 0.0654; **engine builds 0**):
24 arcs -> 4 cylinder candidates at R=4.0000 and 7 at R=2.0000, all exact, plus 4 annuli.
The R=3.0 faces are NOT arc-visible — worth finding out why, since that is the tool's own
blind spot rather than the engine's.

## What this does and does not establish

It establishes **detection**: 102 truth faces the engine does not build have a radius that
arc evidence already pins exactly, and many of the top models have engine matched = 0 —
whole components reverted, i.e. the J6/cascade victims of §8. It does **not** establish
recall: turning an arc pair into a kept cylinder still needs a face built on shared rim
edges and a component that survives adjudication.

But the construction is unusually direct, and this is the reason to pursue it: an arc pair
hands over the axis, the radius, the axial extent **and the two rim curves as exact
circles**. That is every input `BRepPrimAPI`/`BRepBuilderAPI` needs, with the rims available
as shared edges by construction — the same "nothing to repair afterward" property that makes
Route P work, reached without slicing.

## P113 (pending)

Constructing cylindrical faces from arc pairs whose radius is NOT already built, with the
rim arcs as the shared edges, raises recall without the precision collapse t4 guards
against. Gate: CADScore > 71.95 on normal, valid closed solids >= 200, fine 78 not below 74,
sentinels SOT-23 12 / SOT-143 16 / SuperSOT-3 12 / TSOT-23 12.

Open questions to settle before building anything:
1. why R=3.0 on `L10_tool_holder` is invisible to the arc finder;
2. whether a 346 deg arc pair is the same region the segmenter already claimed (double-count
   risk — the 102 must be cross-checked against built radii per region, not per model);
3. the 20 deg dihedral and 2 % residual thresholds are untuned first guesses; they need a
   sweep before any number from this tool is used as a target.

## 8. The C++ stage: built, fires, commits nothing yet — and it overturned my own triage

`claimArcBandsN15` in `wt-p84/src/refit_grow.cpp`, declared in `refit_internal.hpp`, called
from `runStages` before `rejectTorusSlicesN5F`, gated on `STL2STEP_N15_ARCS`.

Design: the stage proposes only an AXIS. `evaluateCommit(mv, tol, tris, axis, rHint)` then
`fillCylinderRegion` do the rest, which is the same path `peelLargeArcStripsA2b` uses — so
every B1 gate still judges the result and the claim model stays whole-provisional.
Tommaso's three conditions implemented as `bestArcRun`: coplanar (normals of consecutive
chord pairs agree to 2 %), equal-chord (CV < 2 %), equal-turn (CV < 5 %), radius by
inversion `R = w / (2 sin(t/2))`, centre by averaging the inward bisector offset
`r cos(t/2)` at each interior vertex. Axis = the run's plane normal.

### Two implementations, and why the first was wrong

Per-provisional boundaries find nothing: at this tessellation a bore wall is split into many
2-triangle provisionals, so no single provisional owns a rim arc — the same reason the seed
path fails on these models. Replaced by `sharpChains`, a component-wide sharp-edge chain
walk (dihedral > `thetaSharp`, plus boundary edges, degree-2 vertices continue, junctions
terminate). That fires: `L10_idler_bracket` reports `chains=10 arcs=4`.

No candidate commits yet: no unclaimed provisional has ALL of its triangles on the proposed
cylinder, so `tris.size() < 2` every time. The gathering rule, not the arc detection, is what
needs work.

### The triage that the stage's entry diagnostic destroyed

`N15_ARC entry accepted=N cylinders=M` on the eight models I had classified as detection
gaps:

```
L10_gearbox          no entry at all      (component SKIPPED, see below)
L08_motor_bracket    cylinders = 6
L09_bearing_block    cylinders = 8
L09_coupling         cylinders = 5
L07_spool            cylinders = 2
L07_grooved_shaft    cylinders = 135
L08_angle_bracket    cylinders = 0, chains = 0, arcs = 0   (2 components, 1 skipped)
L10_idler_bracket    cylinders = 0, chains = 10, arcs = 4
```

**Six of the eight already accept cylinders in segmentation.** My classification in §7 used
"no `DIAG_EXPLODE` events" as the test for "nothing was ever detected", and that inference is
wrong: a region can be accepted by segmentation and then lost at build WITHOUT an explode
event. So the detection-gap population is at most two models, not eight, and the corpus-wide
lever is **retention**, not detection. The 119-face arc ceiling of §6 stands as *radius
evidence* — the radii are exact, `gearbox` 2.0/10.0/12.0 and `coupling` 2.0/5.0/20.0 against
truth — but it is not a gap a new claim stage can fill, because the engine is already finding
most of it.

### A third loss class, previously unnamed: components skipped before recognition

`stl2step.cpp:590` — `if (!isClean(cs)) { smoothSkippedComponents++; return; }`. An unclean
component never reaches `refit::segment` at all, so it gets zero analytic cylinders by policy
whatever any detector does. `L10_gearbox`'s only component is unclean (8 arc-visible truth
faces, all unreachable); `L08_angle_bracket` has 2 components with 1 skipped. This is neither
detection nor cascade, and nothing in the ladder or the arc route addresses it.

### Status

Three rounds on this arm (per-provisional, component-wide, entry diagnostic), so it is
**parked at the stop-loss** with the stage in the tree, env-gated, committing nothing. It is
not a dead end — the arc detection demonstrably works and the radii are exact — but the next
round must fix triangle gathering (a provisional is currently required to lie ENTIRELY on the
cylinder, which a band straddling a rim never does), and that should be weighed against
retention, which the evidence now says is the bigger prize.

### What this stretch established, to save the next session re-deriving it

1. The arc route gives exact radii where surface fitting gives none (`cross_block` 2.5000 vs
   2.490-2.630 from the fit).
2. Tommaso's three conditions + inversion beat a circle fit on short arcs, and beat my own
   first cut (turn-angle only, Kasa radius): corpus arc-visible 274 -> 302 -> 310.
3. `STL2STEP_P94_THETA_CYL_LO` from 5.0 down to 0.5 changes nothing on any of the eight
   models (0/0 throughout) — the seed angle floor is NOT what blocks them.
4. "No explode events" does not mean "nothing detected". Use the segmentation-entry counter.
5. `!isClean(cs)` silently removes whole components from recognition.

## 9. MEASURED WIN on the fine corpus, and the first independent part test

### Corpus A/B, `STL2STEP_N15_ARCS=1`, both variants

```
normal 203   A 71.95  /  B 71.95            (neutral; valid closed solids 200/203 both)
fine    78   A 37.67  /  B 50.13   +12.46
             recall    23.53% -> 33.91%
             precision 94.44% -> 96.08%     (UP)
             matched   272 -> 392   (+120)
             built     288 -> 408   (+120)  <- every new face matched a truth radius
             valid closed solids 74/78 in BOTH arms (no validity cost)
```

Gainers are the `NEG_TO-263*` family, 1 -> 5..19 cylinders each.

**Fidelity check on `NEG_TO-263-9_TabPin5_fine`** (truth 18x0.215 + 18x0.785 + 1x1.25,
deflection 0.009281):

```
A  cyl 1/1    volDelta 0.000000 %  watertight  11 solids  maxDev 0.000000  457 faces
B  cyl 19/19  volDelta 0.000000 %  watertight  11 solids  maxDev 0.000000  331 faces
```

Volume exact, solid count unchanged, face count DOWN 457 -> 331: facets replaced by true
cylinders. This is not the radius-only artefact that sank the +1.17 (§11) and the +1.01 (§15
of the n12 spec) — the volume says the shape is the same.

### Independent test: Tommaso's own part (`Mesh2step_test01.stl` + reference STEP)

Reference STEP carries 4 cylindrical faces, in metres: 0.0116 / 0.0138 / 0.0167 / 0.0398
(= 11.6 / 13.8 / 16.7 / 39.8 mm). 1308 triangles, bbox 102 x 25 x 70 mm.

```
arcfind.py        4 candidates: 11.5882  13.7518  16.6858  39.8345   (all four, ~0.1 %)
engine stage      3 commit with gate=PASS, evR matching arcR to 5 dp
baseline          0 cylinders
n15               0 cylinders  -- component REVERTED
n15 + force t4    2 cylindrical faces R=11.5882, R=13.7518
                  stepVol 135793.1 vs meshVol 135807.5  =  0.011 % off, watertight, 1 solid
```

### Why it reverts, traced end to end

```
DIAG_EXPLODE rid=3 type=1 R=16.685853 nTris=210 maxVertexDev=0.000043 closed360=0 nSides=144
DIAG_REVERT  firstFail=t4_volumeBudget  t1=1 t2=1 t3=1
             dV=3261.67  budget=31.52  meshVol=135807.51  shellVol=132545.84
             dVolAbs=10.51   triIsland=210
```

1. the arc stage commits three correct cylinders;
2. the cascade explodes `rid=3` (R=16.686) with **no `DIAG_FBF`** — a casualty, not a culprit;
3. that explode leaves the shell closed and BRepCheck-valid but **3261.7 mm3 short**, against
   a predicted analytic-vs-chord difference of 10.5 — the explode is NOT volume-neutral;
4. t4 correctly reverts, and all four cylinders are lost.

`t4` is the messenger, not the defect. Ruled out as causes: `STL2STEP_N14_NONREGION` and
`STL2STEP_P93_CLOSE_DEGEN` (no change), and disconnection of the claimed region — an
edge-connectivity filter was added to the stage and reports `comps=1` on all three claims, so
the regions are single patches. **Root cause of the remaining loss on this part is not yet
identified**, and this is attempt 5 on the arm: per Rule 8 the next move is `/ask-kimi` with
the measured facts, not a sixth hypothesis.

### Shipping position

`STL2STEP_N15_ARCS` stays **OFF by default**. It is +12.46 on fine with no validity or volume
cost and neutral on normal, which is a genuine win and the first of the session — but it is one
variant, the gain is concentrated in one model family, and the arm is five rounds deep with an
unexplained revert on the only independent part tested. It wants the second opinion and a
sentinel check (SOT-23 12 / SOT-143 16 / SuperSOT-3 12 / TSOT-23 12) before any default flip,
and the live unit must not be touched.

## 10. Sentinel gate: PASS

```
              arm A        arm B (N15_ARCS=1)   required
NEG_SOT-23      12             12                 12
NEG_SOT-143     16             16                 16
NEG_SuperSOT-3  12             12                 12
NEG_TSOT-23     12             12                 12
```
Identical in both arms, watertight in both. (`volumeDeltaPct = -100 %` on these means
`stepVolumeMM3 = 0`, i.e. the written STEP could not be re-read — present in BOTH arms, a
pre-existing condition of the NEG family, not a regression from this arm.)

## 11. Second opinion (Kimi) — diagnosis, what I verified, and where my fix failed

Rule 8 hand-off in `scratchpad/kimi-brief.md`; full reply in `scratchpad/kimi-n15.out`.

### Its three checkable claims, all VERIFIED in our code

1. **Exploded triangles ARE re-emitted into the same shell.** `refit_build.cpp:5403-5414`:
   for every triangle with `iid >= 0 || exploded`, `makeFacet` is appended to the SAME `built`
   vector with `builtRid = rid`. My "the 210 triangles are not re-emitted" hypothesis is
   refuted by the code itself.
2. **`triIsland` is an accounting label, not a separate body.** `refit_build.cpp:5504`:
   `if (iid >= 0 || exp) g_triOwnedByIsland++`. It counts exploded regions too, so
   `triIsland=210` was a red herring. (`triFace=2406 = 2*1308 - 210` because the accounting
   block sits after `try_rebuild:` and runs once per rebuild round.)
3. **rid=3 is exploded by the site-B cascade at rung U0**, and the trace was hidden behind a
   DIFFERENT env var than the one I was using (`STL2STEP_COLLAPSE_DIAG`, not
   `STL2STEP_DIAG_FBF`). Confirmed verbatim:
   ```
   DIAG_PARTIAL_TOPO rid=3 phase=raw tag=rot-trim/rev-hole valid=0 ... st=27(UnorientableShape)
   DIAG_CASCADE culprit rid=0 src=face faceValid=0
   DIAG_CASCADE culprit rid=1 src=face faceValid=0
   DIAG_CASCADE culprit rid=3 src=face faceValid=0
   DIAG_CASCADE explode rid=3 rung=U0 chains=4 nbrs=[0,1,6,7]
   ```
   rid=3's round-1 face was genuinely `UnorientableShape` (a 261.7 deg `rot-trim/rev-hole`
   partial cylinder); rid=0/1 are hub planes and are spared. **Five attempts saw "no evidence"
   because the cascade trace is behind an env var I never set.**

### The central claim, and the evidence that settles it

t4 measures `BRepGProp::VolumeProperties` on `probe`, a raw `BRep_Builder` shell. Its signed
face sum is **132545.835**. The SAME exploded shell, written to STEP and re-read by the
engine's own verifier, is **135793.1** — 0.011 % off the mesh. (Confirmed the shells are the
same: the forced run ships `cyl=2` of the 3 committed, i.e. rid=3 was exploded there too.)
So the 3261.7 mm3 is an orientation-bookkeeping artefact, not missing material, exactly as the
second opinion says — and this is the same failure mode already recorded for
`BRepGProp` on a closed, manifold, BRepCheck-valid shell (n12 spec §4).

### My fix attempts, both MEASURED and both failed

- `STL2STEP_N16_ORIENT_T4` v1: classify the probe with `BRepClass3d_SolidClassifier` and take
  the magnitude. **Mathematically a no-op** — reversing a whole shell only negates the Gauss
  sum, so `|v|` is unchanged. `shellVol` stayed 132545.835.
- v2: `ShapeFix_Shell::FixFaceOrientation` first, repairing per face rather than wholesale.
  Also no change: `shellVol` still 132545.835, component still reverts.

Kimi's own harness reported `unify(noKeep) vol=132865.87` — still 2.2 % away — and the
engine's write-time warning agrees. So the in-memory B-Rep really does carry 132.5k all the
way to the writer, and only the STEP round-trip yields 135793.1. **Repairing the probe's
orientation is therefore not sufficient**, and neither of the two obvious repairs reaches it.

### Where this leaves the arm

The structural conclusion is that **t4's number is not the volume of the file we ship**. The
gate that rejects this component is measuring an in-memory shape that the STEP writer/reader
normalises into something 2.2 % different. The clean fix is to gate on the POST-WRITE re-read
volume — which the engine already computes as `stepVolumeMM3` — instead of on the probe, and
that is a structural change to the adoption order, not a patch to the measurement.

Not attempted here: it is a change to the shipping path's control flow, it needs its own spec
and its own corpus A/B, and this arm is already seven rounds deep. `STL2STEP_N16_ORIENT_T4`
stays in the tree, OFF, as the record of two refuted repairs.
