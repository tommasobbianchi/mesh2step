# n12 — the 13 "ladder-exhausted" models are four different defects

Status: MEASURED (triage). Predictions below are PENDING.
Baseline to beat: CADScore **71.95** (v1.3.0-n5f live), recall 60.42 %, precision 88.92 %.

## 0. The first measurement: half the 13 can never score

Truth resolvable cylinder faces, normal variant:

| model | truth cyl | note |
|---|---|---|
| L01_hemisphere, L01_sphere, L01_sphere_recon | 0 | |
| L04_chamf_cube_recon, L07_spool_recon | 0 | |
| L08_angle_bracket_recon, L09_actuator_mount_recon | 0 | |
| L02_countersink | 1 | |
| L09_cross_block | 5 | |
| L09_actuator_mount | 7 | 5 matched today |
| L10_tool_holder | 16 | |
| L09_valve_body | 21 | |
| gancio_parametric | 25 | |

**7 of the 13 hold zero truth cylinders.** They cannot move recall by construction;
every hour spent on them was spent on a denominator of 0. The recall prize in this
set is the other 6: **75 faces of the corpus's 518 = 14.5 recall points.**
Matched today: 5. On the floor: **70**.

## 1. Where the 70 are lost — measured, not hypothesised

`STL2STEP_DIAG_REVERT=1 STL2STEP_SEGMENT_SUMMARY=1` on the diagnostic tree
(wt-p84/build-p93, md5 0446ce48d9e6) with the three live flags:

| model | regions | cyl found | builtFaces | builtCyl | decision | first failing test |
|---|---|---|---|---|---|---|
| L09_cross_block | 119 | 6 | 0 | 0 | REVERT | t1 buildFaces returned FALSE |
| L10_tool_holder | 131 | 17 | 0 | 0 | REVERT | t1 buildFaces returned FALSE |
| L09_valve_body | 328 | 123 | 1554 | **123** | REVERT | t4 volume budget |
| L02_countersink | 32 | 1 | 150 | 0 | KEEP | — |
| gancio_parametric | 310 | 5 | 3596 | 0 | KEEP | — |
| L09_actuator_mount | 67 | 12 | 1201 | 10 | KEEP | — |

Four separate defects, and **none of them is detection failing to find a cylinder**:

- **A — hard abort** (cross_block, tool_holder; 21 truth faces).
  `refit_build.cpp:5810`. Site B is entered as *closed shell, BRepCheck-invalid*; the
  cascade ladder runs out of regions to explode; then
  `if (plan.hostR2 || cascadeSt.u2Done || !shValid)` discards the component —
  and `!shValid` is TAUTOLOGICAL inside a `!shValid` branch, so the two other
  disjuncts are dead code. cross_block throws away 155 built faces over
  **one invalid planar face** (`nInvalidFace=1, nPlane=1, nCyl=0`).
- **B — volume budget** (valve_body; 21 truth faces). See §2.
- **C — per-region build failure under KEEP** (countersink 1 found / 0 built,
  gancio 5 found / 0 built). The component ships; the cylinder regions individually
  do not become faces.
- **D — detection gap** (gancio: 5 regions found against 25 truth faces). The only
  member of the 13 where the segmenter is genuinely short, and it is short by 80 %.

## 2. The chosen arm: B, L09_valve_body

The analytic rebuild is **complete and sound** and is thrown away anyway:

    t1 buildFaces returned 1554 faces   PASS
    t2 shell is closed                  PASS
    t3 BRepCheck_Analyzer valid         PASS
    t4 volume budget                    FAIL
       volMesh      22220.038
       volAnalytic  21216.072
       dV            1003.966   (4.52 % of the part)
       budget          27.436   ( = 3 x dVolAbs, dVolAbs = 9.145 )

The gate is not marginal and is not wrong: 1004 mm³ really is missing. What is
wrong is that **99.1 % of the discrepancy is unattributed** — the per-region
shipped error adds up to 9.1 mm³ while the shell is short by 1004. Something is
being dropped, or built inside-out, without any region owning the error.

123 cylinder faces (21 truth) are on the floor behind that one number.

### P106 — PENDING
The missing 1004 mm³ is localised, not spread: it is one or a few regions whose
analytic face bounds a different volume than its facets, and the per-region
accounting in `collectResidualCulprits` does not see it because the region is not
`regionShippedAnalytic` (exploded, or replaced by a plate) — i.e. the error lives in
a region the accountant skips, not in one it measures.

Refuted if the 1004 mm³ is spread across >20 regions at <50 mm³ each, or if every
region's own |dVol| is under 1 mm³ and the deficit only appears at shell level
(which would mean a wire/orientation defect, not a region defect).

### Instrument
Env-gate `STL2STEP_N12_FORCE_ADOPT`: skip test t4 only, keep t1..t3. That ships the
analytic shell as the STEP so it can be interrogated in OCP against the mesh —
per-face signed volume contribution vs the same faces' facets. Dump the object;
do not predict a second time.

### Gate for any fix
- CADScore over main 203 must rise from 71.95 with precision not below 88.0.
- fine variant, 78 models: no change to matched/unmatched.
- valid closed solids: 200/203 or better.
- sentinels exact: SOT-23 12, SOT-143 16, SuperSOT-3 12, TSOT-23 12.

## 3. Arms parked, with their reasons

- **A** (line 5810): the fix is not "delete the tautology" — the ladder genuinely has
  nothing left to explode. It needs a policy for *ship the valid subset*, which is
  n7-partial-adoption. 21 faces. Do it after B.
- **C**: 6 faces. Cheap to diagnose, small prize.
- **D**: 25 faces, but it is a detection problem on a part whose holes are R=0.8–1.5
  against a 0.036 deflection — the hardest class in the corpus. Last.
- The 7 zero-truth models: **closed. Never work on them again for recall.**

---

## 4. P106 — REFUTED. The deficit is not in the geometry; the gate's ruler is bent.

Instrument: `STL2STEP_N12_FORCE_ADOPT` (skip t4 only) and `STL2STEP_N12_DUMP_PROBE`
(BRepTools::Write of the exact shell t4 measures). Both diagnostic-only, wt-p84.

`vb_probe.brep`, the shell t4 rejected, interrogated in OCP:

    shape                 TopoDS_Shell, 1554 faces (1431 planar, 123 cylindrical)
    BRep_Tool::IsClosed   true
    free edges            0        edges with >2 faces 0      (closed, manifold)
    BRepCheck_Analyzer    VALID
    reversed faces        0

It is a sound solid. Then its volume, measured three ways:

    BRepGProp::VolumeProperties (no tol)            21216.072
    BRepGProp::VolumeProperties (tol 1e-6, adaptive) 21216.064
    tessellated Sigma (1/6) a.(b x c), deflection 0.05    22109.683
                                        "        0.01     22109.730
                                        "        0.002    22109.127
                                        "        0.0005   22108.641   (0 faces untriangulated)
    source mesh                                      22220.038

**BRepGProp is wrong by 892.6 mm³ — 4.2 % — on this shell**, and both its overloads
agree with each other, so it is not a tolerance setting. The tessellated figure is
converged over two decades of deflection. t4 rejected a rebuild that is actually
within **0.50 %** of the mesh.

Corroborating signs on the same shell, all pointing at defective face trimming
rather than defective geometry:
- `BRepClass3d_SolidClassifier` returns **ON** for deep interior points (0,0,0).
- GProp surface area 5537.94 vs tessellated 5646.54. Faces 12 and 14 — both
  cylinders — account for 96 of the 109 mm² gap on their own (66.6 vs 116.5,
  66.0 vs 112.7), i.e. GProp integrates roughly half the face the tessellator walks.
- 11 cylinder faces cannot be triangulated at 0.01 at all (0 at 0.0005).

P106 said the 1004 mm³ lived in a region the per-region accountant skips. It does
not live anywhere: **900 of it does not exist**, and the remaining ~111 is ordinary.

## 5. The second defect, which the first was hiding

Fixing the ruler is **not sufficient**. With the correct volume:

    dV = |22108.6 - 22220.0| = 111.4     budget = max(1e-4 x 22220, 3 x 9.145) = 27.44

It still fails. The budget is the second defect:

- It is `3 x Sum|dVolPredicted|` = 27.4 mm³, **0.12 % of the part**, derived from
  per-region predictions that sum to 9.1 mm³.
- The quantity being bounded is the difference between an **analytic** shell and a
  **tessellated** one. That difference is not an error — it is the tessellation's own
  chord bias, and it is predictable: area x deflection / 3 = 5538 x 0.0534 / 3 =
  **98.6 mm³**, against the 111.4 actually measured. The budget is a factor of four
  below the systematic bias it is measuring.
- So t4 currently asks the rebuild to agree with the mesh more closely than the mesh
  agrees with the CAD it came from.

### P107 — PENDING (measurement)
Computing the shell volume by tessellation (same rule the mesh volume is computed
with) instead of `BRepGProp` changes no model's t4 verdict except by removing
GProp's error. Refuted if any model's |dV| moves by more than 1 % without its
adoption decision being the intended one.

### P108 — PENDING (budget)
Adding a third budget term `0.5 x Sum(analytic face area) x meshDeflection` — the
tessellation's own chord bias, with a factor-of-two margin — adopts L09_valve_body
(111.4 vs a budget of ~148) and does not adopt any component whose rebuild is
genuinely wrong, because a wrong rebuild is off by percent, not by the sagitta.
Prize if both hold: 123 built cylinder faces on valve_body, 21 truth faces.
Refuted if precision on the main 203 falls below 88.0, or valid solids below 200.

Both flags ship under one env gate, `STL2STEP_N12_VOLGATE`, measured A/B on the
main 203 and the fine 78 before any promotion. Baseline 71.95.

## 6. Two notes from building the instrument

- **The tessellated-volume route is closed in this environment.** `BRepMesh_IncrementalMesh`
  needs TKMesh, TKMesh pulls TKService, and the snap's `libTKService.so.7.8` wants
  FreeImage symbols that are not linkable outside the snap. So P107 cannot be tested by
  measuring the shell with BRepMesh from inside the engine. The prize was therefore
  measured the other way round: with `STL2STEP_N12_FORCE_ADOPT` removing t4 entirely.
- **`~/.cmake/packages/OpenCASCADE/` holds five registry entries pointing at other
  projects' half-built OCCT trees**, one of which (Katana3D) is missing its
  `*Targets.cmake` files. Any fresh configure of this project finds that one first and
  dies. `wt-p84/build` still has an intact cache and is the build dir to use; a fresh
  configure needs `-DCASROOT=/snap/freecad/current/usr -DSTL2STEP_BUILD_TESTS=OFF` and
  something to defeat the registry. Not fixed here — the registry entries belong to
  other projects.

### First check of the instrument, before the corpus run

    flags                    L09_valve_body            L10_cross_slide
    live three               cyl   0  reverted 1       cyl  0  reverted 1
    + N12_FORCE_ADOPT        cyl 123  reverted 0       cyl 11  reverted 0
                             1 solid, watertight,      1 solid, watertight,
                             volume dev 0.38 %         volume dev 0.02 %

Both adopt as sound solids. 0.38 % and 0.02 % are the deviations t4 called fatal.

---

## 7. The corpus A/B: t4 is vindicated, and P108 dies with it

`radius_audit --b-env STL2STEP_N12_FORCE_ADOPT=1`, main 203, normal:

    arm A (live)        CADScore 71.95   recall 60.42 %   precision 88.92 %  built 352
    arm B (no t4)       CADScore 64.36   recall 66.07 %   precision 62.73 %  built 534
    valid closed solids  200/203  ->  191/203

Removing t4 buys 5.65 points of recall and pays 26 points of precision. **-7.59 net.**
Eighteen components change; only three improve.

Adoption simulated per component against the same scorer (arm A rows with one model's
row swapped in), which is exact because the models are independent:

| adopted | CADScore | recall | precision |
|---|---|---|---|
| none (live) | 71.95 | 60.42 | 88.92 |
| L09_valve_body only | **67.27** | 64.48 | 70.32 |
| L09_coupling + L06_slotted_plate + L07_pulley | **73.12** | 61.97 | **89.17** |
| those three + valve_body | 68.33 | 66.02 | 70.81 |

**L09_valve_body — the model this whole arm was built around — is the single worst
component in the corpus to adopt, at -4.68.** P108 predicted the opposite. Refuted.

The three that help build 5, 2 and 1 cylinder faces and match 5, 2 and 1: every face
they add is real, and precision *rises*. That +1.17 is available but there is no
engine-visible quantity yet that separates them from valve_body — see §8.

**t4 was right.** It was rejecting a rebuild that is mostly fabricated. The 4.2 %
GProp disagreement of §4 is real but no longer load-bearing: it is a symptom of the
slivers described below, not the cause of the loss.

## 8. What valve_body actually is: a blend shipped as cylinder slivers

Truth for `L09_valve_body`: 52 faces — 21 cylindrical, 7 planar, **24 "other"**,
94 circle edges. The engine builds **123 cylinder faces, 121 of them on distinct
axis-lines**, all at R = 2.0 where truth has 18 faces. Roughly 100 are invented.

Measured on the adopted shell:

    orientation tensor of the 123 axes   L2/L1 = 0.9871   L3/L1 = 0.2045   (isotropic)
    distinct axis directions              51
    face area   total 1093.5   median 1.40   min -0.99 (a reversed face)   max 113.1
    area histogram  <0.5:4  <1:31  <2:37  <5:32  <10:0  <20:4  >=20:10

Ten faces carry the real bores. The other ~113 are slivers of 1-2 mm² whose axes point
in 51 directions. That is a **rolling fillet / blend**, for which the engine has no
primitive, chopped into cylinder patches — the same disease as n5f's torus with a
non-planar spine. `smoothBuiltFillets = 0` on this model.

n5f correctly did **not** fire: its rule needs coplanar axes (L3/L1 < 0.05) and these
are isotropic at 0.2045. The discriminator for this class is different:
**within one radius group, a majority of sliver-area faces with isotropic axes.**
valve_body would fire on it; L09_coupling (5 faces), L06_slotted_plate (2) and
L07_pulley (1) are all below n5f's group floor of 6 and cannot.

### P109 — PENDING
Extending the n5f group rule with a second arm — group size >= 6, axes isotropic
(L3/L1 > 0.15), and median member area below a fraction of the largest member's —
removes valve_body's ~100 fabricated cylinders without touching any genuine group in
the corpus. If it holds, valve_body's real bores survive, the volume deficit goes with
the slivers, and t4 may then adopt the component on its own.
Refuted if it fires on any radius group whose members are matched faces today, or if
corpus precision falls.

**This is round 3 on this component (R1).** P106 refuted, P108 refuted. If P109 also
fails, valve_body is parked and the next arm is §3-A, the `refit_build.cpp:5810`
hard abort.

## 9. Banked, independent of P109

Adopting only L09_coupling, L06_slotted_plate and L07_pulley is **+1.17 CADScore with
precision going up**, and needs no new geometry — only a rule that lets a component
through t4 when its rebuild adds no fabricated cylinders. Keep it on the shelf; it is
the fallback if P109 dies.

---

## 10. P109 — CONFIRMED as a guard, WORTHLESS as a score move. valve_body parked.

Implemented as a second arm of `rejectTorusSlicesN5F`, env-gated `STL2STEP_N12_BLEND`:
group size >= 6, axes isotropic (L3/L1 > 0.15 — disjoint from n5f's < 0.05), and the
group's median member area below 0.15 x its largest.

Fires on L09_valve_body exactly as predicted:

    N12_BLEND group n=123 R=1.9706 L3/L1=0.2045 med/max=0.0121 dropped=123

and the component **stops reverting**: `decision=KEEP`, builtFaces 2661, 1 solid,
watertight, volume deviation 0.000 %. 109 fabricated surfaces refused.

Culling per member instead — keeping the 14 largest — was built and measured: the
component **reverts again**, so those 14 are blend patches too, not bores. Wholesale is
both simpler and the only variant that adopts. That is why valve_body ships **zero**
cylinder faces either way.

Corpus A/B, main 203, normal:

    arm A (live)              CADScore 71.95  recall 60.42 %  precision 88.92 %  built 352
    arm B (+ N12_BLEND)       CADScore 71.95  recall 60.42 %  precision 88.92 %  built 352
    matched delta 0, unmatched delta 0, models changed 0, valid solids 200/203 both.

Exactly neutral. **Keep the flag off.** It is a correct guard that must be paired with
any future loosening of t4 — without it, loosening t4 ships 109 invented surfaces on
this one model — but it is not a CADScore move.

**L09_valve_body is parked (R1: P106, P108, P109).**

## 11. The banked +1.17 is an artefact. Do not take it.

§7 offered +1.17 from adopting L09_coupling, L06_slotted_plate and L07_pulley.
Their actual rebuild quality, from `DIAG_REVERT`:

| model | meshVol | shellVol | dV | error |
|---|---|---|---|---|
| L07_pulley | 5445.34 | 12292.18 | 6846.85 | **+126 %** |
| L09_coupling | 16842.49 | 15348.83 | 1493.66 | −8.9 % |
| L06_slotted_plate | 8455.56 | 8786.57 | 331.01 | +3.9 % |

All three are **grossly wrong solids**. L07_pulley's rebuild is more than twice the
volume of the part. They score because CADScore counts a radius match and cannot see
placement — the limitation `cadscore.py` states in its own header: *"radius agreement
is necessary, not sufficient — right size, wrong place still counts."*

Shipping a 126 %-wrong solid to buy 0.178 of score is the opposite of the goal.
**Rejected.** The +1.17 of §7 is withdrawn.

## 12. Verdict on the whole n12 arm

**t4 is correct on every component examined.** Each one it rejects has a rebuild that
is genuinely broken — fabricated blend slivers (valve_body), or a solid off by 4 % to
126 % (the other three). The recall missing from the 13 is not behind the volume gate,
and the 4.2 % `BRepGProp` error of §4 is a symptom of defective faces, not the cause
of any loss.

What survives from this arm:
- §0: **7 of the 13 hold zero truth cylinders.** Permanently closed.
- §4: `BRepGProp::VolumeProperties` can be 4 % wrong on a raw `BRep_Builder` shell that
  is closed, manifold and BRepCheck-valid; sewing and `ShapeFix_Shape` do not change it.
  Worth knowing before trusting that number anywhere else.
- §10: the blend-sliver guard, written, validated, measured neutral, shipped OFF.
- §11: CADScore can be moved by adopting broken solids. Any future gate change must be
  read against volume error, not against CADScore alone.

**Next: arm A, `refit_build.cpp:5810`.** `L09_cross_block` (6 cylinders detected, 5 of
them within tolerance of truth 2.5) and `L10_tool_holder` (17 detected) both return
`buildFaces = false` with **builtFaces = 0**. Unlike every component above, nothing is
wrong with their geometry — nothing is built at all. 21 truth faces.

---

# n13 — one marginal cylinder takes the other five with it

Arm A, traced on `L09_cross_block` (119 regions, 6 cylinders detected, truth 2.5 x 5).
`FaceBuildFailed` in the reject histogram is misleading: **`explodeRegion` stamps that
same code on every region the cascade sacrifices** (`refit_build.cpp:5073`), so the
"6 cylinders failed to build" reading of §1 was wrong. Only one of them failed.

The ordered trace, `DIAG_VETO` + `DIAG_FBF` + `DIAG_EXPLODE` + `DIAG_COLLAPSE`:

    1  DIAG_VETO  kind=2 resid=0.008952 budget=0.006175
       rid=8, R=2.625353 -- chord sagitta 45 % over budget. A genuinely bad fit.
    2  DIAG_FBF   round=0 rid=8 ... chordSag=0.008967
    3  DIAG_EXPLODE rid=8                      <- correct and proportionate
    4  J6: shell not closed freeEdges=12 faces=125
       DIAG_COLLAPSE mix=7  <- exploding one region left 7 MIXED chains
    5  J6: shell not closed freeEdges=12 (again)
       DIAG_EXPLODE rid=7  R=2.490384  maxVertexDev=0.002174
       DIAG_EXPLODE rid=9  R=2.498467  maxVertexDev=0.004934
       DIAG_EXPLODE rid=10 R=2.496951  maxVertexDev=0.000900
       DIAG_EXPLODE rid=11 R=2.496954  maxVertexDev=0.000900
       DIAG_EXPLODE rid=12 R=2.460015  maxVertexDev=0.003991
    6  revert -- 0 cylinders shipped

Steps 1-3 are the engine working correctly. **The defect is 3 -> 4.** Replacing an
analytic face with its own triangles should be seamless: the facets have exactly the
boundary the face had. Instead it opens the shell by 12 free edges, because the
neighbours were built against *collapsed* analytic edges while the exploded region now
carries polyline edges — `DIAG_COLLAPSE mix=7`. That is **n5c mixed-boundary**, and it
is what converts one bad fit into a total loss.

The five sacrificed cylinders have maxVertexDev 0.0009 to 0.0049 and radii 2.490,
2.498, 2.497, 2.497, 2.460 against truth 2.5 at tol 0.035 — **all five are matches
that would have counted.**

### P110 — PENDING
The loss is the cascade, not the fit. Across the corpus, the cylinder regions that the
engine builds and then explodes — rather than the ones it never fits — are the larger
share of the missing recall, and the trigger is almost always a shell opened by an
earlier explode rather than an independently bad region.
Refuted if most exploded cylinders are exploded in the first round (i.e. they were bad
themselves), or if the corpus total of sacrificed matched-radius cylinders is under 20.

Sweep running: 203 models with `DIAG_FBF`/`DIAG_VETO`/`DIAG_REVERT`, tallying
first-round failures against cascade casualties.

## P110 — CONFIRMED. The cascade destroys more cylinders than fitting ever fails to find.

203 models, `DIAG_FBF` + `DIAG_EXPLODE` + `DIAG_REVERT`, live flags:

    models                                        203
    components reverted                            60
    cylinder regions that FAILED to build          50
    cylinder regions EXPLODED                     160
      of which casualties (never failed a build)  110
      of which radius-matching truth               46

**46 matched-radius cylinder faces are built correctly and then thrown away**, against
50 that genuinely fail to fit. The cascade is the larger loss.

For scale: matched is 313 of 518 today. Recovering the 46 gives recall 69.3 %,
precision (313+46)/(352+46) = 90.2 %, **CADScore about 78.4 — roughly +6.5**, the
largest single arm found this session. Ten of the fourteen affected models already
KEEP their component, so most of it needs no change to the revert path at all.

| model | casualties | decision | first failure | cyl failed | cyl exploded |
|---|---|---|---|---|---|
| L10_tool_holder | 8 | REVERT | buildFaces false | 1 | 9 |
| gancio_parametric | 6 | KEEP | — | 1 | 7 |
| L09_clamp | 6 | KEEP | — | **0** | 6 |
| SpeedTestStructure | 5 | KEEP | — | 0 | 5 |
| L10_spindle_nose | 4 | KEEP | — | 2 | 35 |
| L09_cross_block | 4 | REVERT | buildFaces false | 1 | 6 |
| L10_linear_bearing, L10_guide_block, L09_crank_arm, L07_bushing, L06_slotted_plate | 2 each | | | | |
| L09_gear_blank, L08_pillow_block, L07_collar | 1 each | | | | |

### L09_clamp is the proof case

    J6: shell not closed freeEdges=4 faces=17        <- 4 free edges, no explode yet
    DIAG_EXPLODE rid=8  R=5.000000 maxVertexDev=0.000000
    DIAG_EXPLODE rid=9  R=5.000000 maxVertexDev=0.000000
    DIAG_EXPLODE rid=13 R=2.000000 maxVertexDev=0.000000
    DIAG_EXPLODE rid=14 R=2.000000 maxVertexDev=0.000000
    DIAG_EXPLODE rid=15 R=2.000001 maxVertexDev=0.000001
    DIAG_EXPLODE rid=16 R=2.000001 maxVertexDev=0.000001
    smoothCylinders 8 -> smoothBuiltCylinders 2

Zero `DIAG_FBF`. **Six mathematically exact cylinders — exact radii, zero vertex
deviation — destroyed to chase four free edges**, and the component ships anyway.

The policy doing this is the blanket in `refit_build.cpp`: when the recovery pass finds
no chain-level culprit it runs `explodeAll()`, or, if a Seamed360 must be kept, explodes
**every non-closed360 cylinder in the component**. It never asks which regions own the
free edges — and J6 knows exactly which edges those are.

### The fix direction
Explode the regions incident to the reported free edges, not every cylinder. Gate it,
A/B it against 71.95 with the standard gates (fine 78 unchanged, valid solids >= 200,
sentinels 12/16/12/12).

### Separate bug found in passing
`L09_clamp_normal` emits `"verification failed: written STEP could not be re-read"`
with `stepVolumeMM3 = 0.0`. The engine writes a STEP it cannot read back. Not chased
here; filed so it is not lost.

## §13 — n13 round 1: targeted explode (MEASURED, see §14)

Implemented in `scratchpad/wt-p84/src/refit_build.cpp`, gated on
`STL2STEP_N13_TARGETED_EXPLODE`: in the `recoverPass < 1` J6 fallback, before the two
blanket arms, map each free edge to its single incident face, that face to its region via
`built`/`builtRid`, and explode only those regions.

It fires (`N13_TARGETED freeE=4 regions=3` on L09_clamp) and is **a no-op on the proof
case**: attempt 2 reports the same `freeEdges=4`, and the later passes explode the six
cylinders anyway. `smoothBuiltCylinders` stays 2 in both arms.

### Why — the free edges are not missing faces (measured, `STL2STEP_J6_DIAG=1`)

```
freeE#0 faceRid=8  len=15.6204 pa=(-5,0,10)  pb=(5,0,-2)
freeE#1 faceRid=10 len=0.0000  pa=(5,0,-2)   pb=(5,0,-2)
freeE#2 faceRid=11 len=0.0000  pa=(5,0,-2)   pb=(5,0,-2)
freeE#3 faceRid=11 len=15.6204 pa=(5,0,-2)   pb=(-5,0,10)
```

Two of the four are the **same segment**, owned by rid8 and rid11, traversed in opposite
directions — geometrically identical, two distinct TShapes, so they never paired. The other
two are zero-length edges at the shared endpoint. Nothing is absent from the shell: an edge
that should be shared is duplicated. Exploding either owner cannot pair a duplicate, which is
exactly why the arm is inert.

`STL2STEP_P93_CLOSE_DEGEN` does not rescue it either: it discounts the two degenerate edges,
leaving `realFree = 2`.

### P111 (pending)

The shell is reported open because coincident free edges carry distinct TShapes. Merging
only those — a tolerance-tight sew of the free edges, no explode at all — closes the shell
and the component keeps all 8 cylinders instead of 2. Prediction: `freeEdges` 4 → 0 on
L09_clamp with zero geometric change (`smoothMaxDevMM` unchanged), and no region exploded.

## §14 — n13 round 1 REFUTED (corpus A/B, 203 models, variant normal)

```
arm A (baseline)                  CADScore 71.95  recall 60.42%  precision 88.92%  matched 313  built 352
arm B STL2STEP_N13_TARGETED_EXPLODE=1  CADScore 71.43  recall 59.85%  precision 88.57%  matched 310  built 350
B-Rep health identical: closed valid solids 200/203 in both arms.

better L09_cross_block        0 -> 3
WORSE  L10_linear_bearing     5 -> 0
WORSE  L07_collar             1 -> 0
```

P110's mechanism is real — `cross_block` gains the three cylinders the blanket cascade was
taking — but the *policy* is net negative: exploding fewer regions leaves the shell open in
models where the blanket explode happened to close it, and those components then revert
wholesale. −0.52. **Ships OFF**, kept in the tree env-gated as the evidence for §13's
diagnosis.

The arm is therefore not "which regions to explode" but §13/P111: **do not explode at all** —
pair the duplicated coincident edges so the shell was never open. Exploding is a response to
a mis-measurement of closure.

## §15 — P111 CONFIRMED as mechanism, NOT bankable as score (measured)

Sew the duplicated coincident free edges (`STL2STEP_N13_SEW_FREE`), explode nothing.
Accept only if the sewn shape is a shell, `IsClosed`, and the face count is unchanged;
remap `built[i]` through `sew.ModifiedSubShape` **in place** so `builtRid` stays positional.

```
normal 203   A 71.95 (r 60.42 p 88.92 m 313 b 352)   B 72.96 (r 61.20 p 90.31 m 317 b 351)   +1.01
             valid closed solids 200/203 in both
             better L09_cross_block 0->4 | WORSE L08_pillow_block 5->3
fine 78      A 37.67 (r 23.53 p 94.44 m 272 b 288)   B 40.14 (r 25.61 p 92.79 m 296 b 319)
             valid closed solids 74 -> 72   <-- REGRESSION
```

### Adding `shellIsValid(ns)` to the accept test makes the arm EXACTLY INERT

`71.95 / 71.95` on normal and `37.67 / 37.67` on fine, every counter identical. So the whole
+1.01 came from shells `BRepCheck` rejects.

### What it rejects them for: `BRepCheck_UnorientableShape` (status 27)

Every complaining face on both probe models carries status 27 and nothing else
(`cross_block` faces 9/11/54/71, `clamp` faces 6/7/8). The shell closes and the face count is
right, but the faces cannot be coherently oriented — which is why both models report
`stepVolumeMM3 = 0` and `"verification failed: written STEP could not be re-read"`.

**Verdict: the +1.01 is cylinders in a body that is not a valid solid. Not bankable** — the
same error class as the withdrawn +1.17, caught this time by instrumenting instead of banking.
CADScore matches on radius and cannot see it. The mechanism (merge, don't explode) is right;
the remaining defect is that merging the duplicate leaves the two owners' face orientations
inconsistent.

### P112 (pending)

Re-asserting face orientation after the merge turns the sewn shell valid and keeps the gain:
prediction `shellIsValid` true on `cross_block`, status-27 count 0, `stepVolumeMM3 > 0`, and
the normal corpus at or above 72.96 with valid closed solids >= 200 and the fine 78 not below
74.

## §16 — P112 REFUTED; the n13 defect is PARKED (R1: three rounds)

`ShapeFix_Shell` on the sewn shell clears status 27 on `L09_clamp` (accepted under strict
validity) and fails on `cross_block`. With validity enforced the arm is **exactly inert on both
variants**: normal 71.95/71.95, fine 37.67/37.67, every counter identical. `clamp`'s component
keeps no cylinders even with a valid closed shell, so the orientation repair buys nothing.

Three rounds spent on this defect — targeted explode (−0.52), sew (+1.01 but invalid solids),
sew+orient (inert). **Parked.** All three ship OFF, kept env-gated as the evidence.

What is established and must not be re-derived:
- the shell is opened by a DUPLICATED edge, not a missing face (§13, measured);
- exploding cannot pair a duplicate (§14, measured);
- merging the duplicate closes the shell but leaves `BRepCheck_UnorientableShape` (§15, measured);
- `ShapeFix_Shell` repairs that on some components and not others (§16, measured);
- a closed, valid shell is still not sufficient for the component to keep its cylinders —
  `L09_clamp` loses them at a site downstream of `buildFaces` that has not been located.

The last line is the open question, and it is the one to trace next if this defect is reopened.
