# n19 — unify opens the shell, and the pipeline answers by deleting the file

## 1. What was measured first, and what it refuted

The pending list carried, as item 1:

> L08_pillow_block ships at 15.06 % volume error with NO flags and t4 PASSES it.

**Refuted.** Re-run against the shipped v1.5.0-n17n18 binary:

| model | volumeDeltaPct |
|---|---|
| L08_pillow_block_normal | 0.000000 |
| L08_pillow_block_fine | 0.000000 |
| L08_pillow_block_coarse | 0.000000 |
| L08_pillow_block_recon_normal | 0.000000 |
| L08_pillow_block_recon_fine | 0.000000 |

Swept the whole corpus rather than trusting one model:

- **normal, 203 models: 0 with `|delta| > 0.05 %`, 0 failures.**
- **fine, 281 models: 0 with `|delta| > 0.05 %`, 1 hard failure.**

The 15.06 % figure was the **in-memory** `BRepGProp` number — exactly the quantity n17
proved is not the shipped volume. n17 fixed the gate that consumed it; nothing on disk was
ever 15 % wrong. Item 1 is closed as refuted, not deferred.

The sweep is the point: the same command that refuted the stale item found the real one.

## 2. The real defect: `L10_nut_housing_recon_fine`

One model of 484 produces **no output file at all**:

```
solid     1 solid, 0 open shells
unify     1,836 -> 1,683 faces
check     INVALID (ran during write)
fix       valid after ShapeFix -- rewriting output
write     AP214, ... (3973.1 KB)
error: post-write verification failed: re-read solid count 0 != written 1
```

The written STEP contains `1683 ADVANCED_FACE`, **0 `MANIFOLD_SOLID_BREP`, 0 `CLOSED_SHELL`,
1 `OPEN_SHELL`**. The writer cannot emit a solid around an open shell, so it emits a
shell-based surface model; post-write verification counts 0 solids against the 1 it believed
it wrote, calls the writer broken, and `fs::remove`s the output. The user gets nothing.

## 3. Attempt 1 — refuted

Hypothesis: `ShapeFix_Shape` buys validity by opening the shell (it is the stage between
`check INVALID` and the bad write). Implemented the revert guard, measured
`countFreeEdges` either side of `fix.Perform()`: **the count does not rise across
ShapeFix.** The three free edges already existed when ShapeFix ran. Guard removed; the
three lines it had displaced were restored and re-verified.

## 4. Attempt 2 — the cause, isolated by bisection

`--no-unify` on the same model:

```
check     valid
verify    re-read 1 solid, 1,836 faces, volume delta 0.000000%
watertight: true, freeEdges: 0
```

**`ShapeUpgrade_UnifySameDomain` is what opens the shell**: merging 1836 → 1683 coplanar
faces leaves 3 free edges. Everything downstream — the INVALID check, the ShapeFix rewrite,
the unrepresentable solid, the deletion — is consequence, not cause.

## 5. The fix, and why it is not new policy

n5h already established the principle, in this file, for the *second* unify pass:

> smooth-flat is a consolidation, never a repair, so it is transactional.

That guard was scoped to the smooth-flat pass only. The **first** `unifyAll(unifyAngleDeg,
"unify")` had none, and that is the one that breaks here. n19 extends the same transaction
to it: snapshot `shape` / `parts` / `facesAfter`, count free edges either side, restore on
a rise.

```cpp
static const bool n19 = std::getenv("STL2STEP_N19_UNIFY_CLOSURE") != nullptr;
const int freeBeforeUnify = n19 ? countFreeEdges(shape) : -1;
const TopoDS_Shape shapePreUnify = shape;
const std::vector<TopoDS_Shape> partsPreUnify = parts;
const int facesPreUnify = facesAfter;
unifyAll(unifyAngleDeg, "unify");
if (n19) {
    const int freeAfterUnify = countFreeEdges(shape);
    if (freeAfterUnify > freeBeforeUnify) {
        shape = shapePreUnify; parts = partsPreUnify; facesAfter = facesPreUnify;
        warn("unify opened the shell (free edges ... ) -- reverted");
    }
}
```

Fewer faces is a nicety; a file is not. The trade is 1683 → 1836 faces on one model against
that model existing at all.

Result with the gate on:

```
unify     1,836 -> 1,683 faces
warning: unify opened the shell (free edges 0 -> 3) -- reverted
verify    re-read 1 solid, 1,836 faces, volume delta 0.000000%
ok:true  watertight:true  freeEdges:0  volumeDeltaPct:0.000000
```

Gate off reproduces the failure verbatim, so the guard is the whole difference.

## 6. Corpus gates

`STL2STEP_N19_UNIFY_CLOSURE=1` as the B arm against the same binary with the gate off,
normal and fine. Numbers appended below once measured.

## 7. Corpus gates — measured, all neutral

Six arms, same binary, flags off (A) vs on (B):

| arm | variant | A | B | matched delta |
|---|---|---|---|---|
| resid | normal | 73.67 | 73.67 | +0 |
| resid | fine   | 50.13 | 50.13 | +0 |
| n19   | normal | 73.67 | 73.67 | +0 |
| n19   | fine   | 50.13 | 50.13 | +0 |
| both  | normal | 73.67 | 73.67 | +0 |
| both  | fine   | 50.13 | 50.13 | +0 |

B-Rep health identical throughout (200/203 normal, 74/78 fine).

## 8. The second arm in this patch: the law-band stage cost

`extractChain` (refit_lawband.cpp:594-618) spawned a thread pool on EVERY call to
parallelise an O(nV) max-reduction over ~100 doubles. `claimLawBandsL` makes tens of
thousands of those calls per model, so spawn+join dominated. gdb counted **157,558
thread creations in 90 s** on mechparts/29.

Why cadbench never saw it — instrumented (`STL2STEP_LAWBAND_DIAG`):

| model | nTri | nStrips | triples | seedsOk | maxMembers | triVisits |
|---|---|---|---|---|---|---|
| L08_pillow_block (corpus) | 566 | 166 | 156 | 83/156 | 31 | 67,073 |
| L04_pillow (corpus) | 1852 | 1326 | 4944 | **26/4944** | 10 | 48,635 |
| mechparts/15 | 1784 | 446 | 432 | **432/432** | 144 | 4,159,146 |

Corpus models reject nearly every seed; real mechanical parts accept every one and grow
144-strip chains. The corpus has no long law-band chains, so the stage was never exercised
in the regime where its cost matters.

The reduction is a pure `max`, so serialising it is bit-identical — verified by comparing
geometry hashes (STEP header excluded) on L04_pillow, L08_pillow_block and clamp_half_a.

Measured on real parts: 38.4->27.0 s, 43.4->21.0 s, 45.6->25.4 s.

### Refuted on the way (recorded so they are not retried)

1. The ungated `fprintf` at refit_fillet.cpp:772 dominates — no, 28 lines per run.
   (Still a real defect: a debug print shipped in a production build.)
2. The seed triples explode combinatorially — no, mechparts/29 has 367, the FAST corpus
   model L04_pillow has 4944.
3. Skip a seed whose three strips are already covered by a grown band (n20) — cuts work
   but mechparts/15 drops 1 cylinder -> 0. Growing from a different seed yields a
   different band. Removed from the tree; do not resurrect without a recall gate.

## 9. v1.6.0 deploy record

`~/.local/share/mesh2step-native-v1.6.0-aeef6adc3bf0`, md5 aeef6adc3bf0.
Drop-in rewritten; rollback at `native.conf.v160-rollback` (restores v1.5.0-n17n18).
Gates proven live through run.sh: nut_housing verifies instead of having its output
deleted; mechparts/15 25 s. API end-to-end: 25.77 s, watertight, volume delta 0.0.

## 10. Next defect, already isolated (not fixed here)

Recall on real parts. On mechparts/15: 11 cylinder regions recognised, 4 rejected
(2 Span, 2 VertexResidual), 7 accepted, and **1 cylindrical face reaches the file**.
`DIAG_EXPLODE` fires 10 times; among the casualties rid=9/10/11/12 (R=8.2550, 7.9375,
8.2549, 7.9372), each 144-sided and fitting the mesh to 0.0002 mm.

The trigger is named by the cascade: `culprit rid=13 src=face faceValid=0`, where rid=13
is a 2-triangle 4-sided patch at R=10 — a 90 deg arc drawn with two facets. Its MEASURED
chord sagitta is 10*(1-cos45) = 2.928932 mm, which becomes its edge tolerance
(refit_build.cpp:365; capApplications=99, capWiderThanSew=99). That licenses OCCT to
identify points 2.93 mm apart on a part whose cylinders are R~8 mm; faces go invalid and
the cascade explodes the good neighbours with the culprit.

The cap is honest -- the mesh really is that coarse. The gap is that n18 gates arc
COVERAGE (a 90 deg patch passes) and nothing gates tessellation QUALITY. sagitta/R is
0.293 for the culprit and ~3e-5 for a real 144-sided bore: four orders of magnitude,
treated identically.

Also note `builtFi += st.fillets` (stl2step.cpp:1409) copies the PLANNER's count, so
`smoothBuiltFillets` overstates what was built; only `builtCy` counts real faces.

## 11. n21 coarse-arc rejection — shipped as an explicit TRADE (v1.7.0)

`sagitta/radius > 0.05` on cylinder regions, `STL2STEP_N21_SAGRATIO`.

**The discriminator does not discriminate.** Measured drop lines:

```
L10_nut_housing_normal:  R=2.0000  sag=0.585786  ratio=0.2929  nTri=2   (x5)
mechparts/15:            R=10.0000 sag=2.928932  ratio=0.2929  nTri=2   (x6)
```

Identical shape -- a 90 deg arc in two facets -- differing only in radius, and sagitta/R
is scale-free. So the gate is really "reject 2-triangle quarter-cylinders", and raising
the threshold to 0.10/0.15/0.20/0.25 changes nothing on either model (all sit at 0.2929).

| | without | with |
|---|---|---|
| mechparts/15 | 1 cyl | 5 cyl |
| L10_nut_housing_normal | 9 matched | 5 matched |
| corpus normal | 73.67 | 74.74 (prec 91.93->94.97, built 347->338) |
| corpus fine | 50.13 | 50.51 (prec 96.08->96.81) |
| valid closed solids | 200/203, 74/78 | 202/203, 76/78 |

Every aggregate improves; one corpus model pays. Shipped on that basis, env-gated.

**Refuted refinement, do not retry blind:** a contagion form -- drop the coarse patch
only when an edge-adjacent accepted cylinder is >= 10x finer -- fires on NEITHER model.
The coarse patches are not edge-adjacent to the fine bands, so the damage travels by
some other coupling, which is still unidentified.

## 12. The other recall cause: the calibration quorum (model 8)

Model 8 loses nothing -- `DIAG_REJECTS regions=175 rejected=0 cylRegions=2`, zero
explodes. The law-band stage simply refuses to report:

```
DIAG_LAWCOST    seedsOk=432 acceptCalls=61344 triVisits=9041271 maxMembers=144
DIAG_LAWCAL     dLo=0 dHi=0 nD=3 nA=0 empty=1
DIAG_LAWDECLINE reason=empty_cal nCand=4
```

61,344 accept calls and 9M triangle visits are computed and then discarded.
refit_grow.cpp:3088 (`empty_cal`) and :3099 (`nDLimited < 5`) both `return true` without
claiming anything. The comment states the provenance: "handle-lock has 14 ... fewer than
5 is a foreign/partial component (Body11's in-band leftover accepted nD=2)" -- constants
read off cadbench, which has many chains per part. Real machined parts have few.

Note `li` is NOT used by the claim loop, which reads each band's own `b.R` and `b.N`.
The calibration is a cross-check that all bands obey ONE tessellation law, not an input
to the geometry. Declining therefore throws away bands that are individually valid.

## 13. n22 quorum bypass — I CALLED THIS REFUTED ON PARTIAL DATA. IT IS NOT.

`STL2STEP_N22_NOQUORUM=1` skips all three wholesale declines in claimLawBandsL
(`empty_cal` :3088, `nDLimited < 5` :3099, `wide_cal`) and claims the bands on their own
individual evidence, since the claim loop reads `b.R`/`b.N` and never touches `li`.

Measured on the user's parts (n21 on, v1.7.0 flags):

| model | quorum on | bypassed |
|---|---|---|
| 8  | 2 | 2  (no help -- and this was the model that motivated it) |
| 26 | 1 | 0  |
| 2  | 2 | 0  |
| 34 | 3 | 6  |
| 13 | 2 | **14** |
| 15 | 5 | 5  |
| **total** | **15** | **27** |

**Correction.** On the first four rows I recorded "erratic and net-harmful" and committed
that verdict. The last two rows overturn it: the bypass nearly DOUBLES total cylinders
(15 -> 27) with a 7x on model 13. It is high-variance, not harmful. Still not shipped,
but for a different and now-understood reason.

**Why the two zeros happen.** mechparts/2 with the bypass:

```
DIAG_LAWCLAIM_DONE accepted=5
DIAG_REJECTS  regions=167 rejected=3 cylRegions=5 cylRejected=3 hist[VertexResidual*=3]
explodes=0
smoothCylinders=5  smoothBuiltCylinders=0  smoothRevertedComponents=1
```

Nothing explodes. The bypass admits lower-quality bands, 3 fail VertexResidual, the
rebuild then fails the COMPONENT-level adoption test, and the whole component is
reverted -- taking the 2 cylinders it had with the quorum on. These parts are a single
manifold component, so adoption is all-or-nothing: one bad band costs every cylinder.
Model 13 (2 -> 14) is the same change where adoption happens to pass.

**This is pending item #2 from the original list**: replace the component-level volume
verdict with per-region attribution (`collectResidualCulprits`, `faceVolumeContribution`,
`regionChordVol`, `dVolPredicted` are already in the tree). With per-region adoption the
3 bad bands would be dropped individually and the good ones kept, which converts n22
from a gamble into a gain. That is the correct order of work: per-region adoption FIRST,
then re-measure n22.

The lesson corrects the reading in section 12: `DIAG_LAWDECLINE reason=empty_cal`
names where model 8 STOPS, but removing that stop does not produce cylinders, so the
suppression on model 8 is downstream of the claim, not at the quorum. The comment's
cadbench provenance ("handle-lock has 14") made the constant look like a stale artefact;
it is not -- global tessellation-law consistency is doing real work, and without it bands
that individually pass go on to destroy each other.

Next investigation should start by asking where model 8's 4 candidate bands die AFTER
being claimed (n18 arc coverage, n21 coarse-arc, or the commit path), not at the quorum.

## 14. Session ledger — what is shipped, what is refuted

Shipped and live:
- v1.6.0: law-band serial residual (1.4-2.1x on real parts, geometry bit-identical),
  n19 first-unify closure guard (a model that shipped NO FILE now ships a valid solid).
  Six corpus arms neutral.
- v1.7.0: n21 coarse-arc rejection, an explicit trade (+1.07 normal, +0.38 fine,
  mechparts/15 1->5, L10_nut_housing_normal 9->5).

Refuted this session, with numbers, so they are not retried:
1. L08_pillow_block ships 15.06% volume error -- does not exist; 203 normal + 281 fine
   models all within 0.05%. It was the in-memory figure n17 already discredited.
2. The ungated fprintf at refit_fillet.cpp:772 dominates runtime -- 28 lines per run.
3. Seed triples explode combinatorially on real parts -- mechparts/29 has 367, the FAST
   corpus model L04_pillow has 4944.
4. n20 seed dedup -- cuts work, costs mechparts/15 its only cylinder.
5. ShapeFix opens the shell -- free edges do not rise across fix.Perform(); it was unify.
6. n21 contagion form -- fires on neither model.
7. n22 quorum bypass -- above.

Still open:
- The ungated fprintf at refit_fillet.cpp:772 (cosmetic, real).
- Models 29, 31, 3, 5 ship ZERO cylinders; cause not yet isolated.
- 3 of the 40 user parts exceed the 120k-triangle app limit (12, 23, 39).
- The coupling by which a coarse patch destroys a well-tessellated neighbour is still
  unidentified -- it is not edge adjacency.

## 15. n21 WITHDRAWN from production — validated on the wrong population

Deployed 16:25, rolled back 17:15. Measured on mechparts/11 (98% curved by area):

```
n21 OFF: cylRegions=56  ChordConsistency*=119   (the pre-existing G3 gate)
n21 ON : cylRegions=6   ChordConsistency*=169   N21_COARSE dropped=50
```

**It removes 89% of the recognised cylinder regions on the user's most cylindrical
part.** Shipped output is 0 either way today (the build fails separately), so nothing
visible broke -- but the regions are destroyed before the build is reached, so the moment
the build is fixed n21 would suppress the gain.

Its only demonstrated benefit was mechparts/15, 1 -> 5, on a part that is **7.8% curved**.
The +1.07 corpus gain is real and reproducible and still does not justify it, because
cadbench does not resemble these parts.

**The process failure, not the code failure.** The six models I tuned on -- 15, 8, 26, 2,
34, 13 -- were chosen by a census that sorted by FILE SIZE, so it began with the smallest
parts, which are also among the least curved. Curvature measured from the mesh alone
(dihedral 0.3-25 deg):

| part | curved % | | part | curved % |
|---|---|---|---|---|
| 11 | 98.1 | | 15 | 7.8 |
| 23 | 91.4 | |  8 | 4.8 |
| 25 | 92.9 | | 34 | 19.7 |
| 9  | 88.0 | |  2 | 42.4 |

Median across 39 parts: **59%**. Every recall decision of the session was taken on parts
at the bottom of that distribution. Order the work by the property under study, never by
whatever the filesystem hands back first.

A second instrument bug nearly compounded it: the first curvature pass required TWO
smooth edges per triangle and reported these parts as 0.0% flat, which would have
"confirmed" that 1-2 cylinders was correct. A cylinder tessellated as quad strips gives
each triangle exactly ONE smooth edge -- mechparts/15 has 432 edges in the 0.3-5 deg band
and zero triangles with two. Verified against the engine's own vertex count (888 unique,
"0 welded") before believing either number.

## 16. What the curved parts actually fail at — three distinct mechanisms

| model | curved | regions | rejected | built | shipped | cause |
|---|---|---|---|---|---|---|
| 11 | 98% |  6 | 205 | 0 | 0 | `buildFaces-false exit=none line=6038` |
| 9  | 88% | 98 | 444 | 0 | 0 | `counted-not-reverted usedRefit=true cyls=0`; VertexResidual*=210 |
| 22 | 77% |  3 |   0 | 0 | 0 | t4 volume revert: `dV=779.43 budget=90.29` |

Model 9 is the clearest target in the whole corpus: **98 cylinder regions recognised, 98
planned, ZERO built**, and the component is adopted anyway. Recognition is not the
bottleneck there; face building is. That is where the next session starts.

## 17. The cascade is a DISPROPORTIONATE RESPONSE, measured — and four fixes that did not land

The decisive measurement (STL2STEP_N25_DIAG, added because DIAG_PARTIAL_EDGE was
misread as a failure count when it is a per-edge trace of the diagnostic walk,
refit_build.cpp:2061):

```
mechparts/9:  N25_CHAINFAIL chains=11498 failed=69 regionsHit=129 recoverPass=0
              DIAG_EXPLODE x3777   cylRegions=98  built=0  shipped=0
```

**69 of 11,498 chains fail (0.6%).** The targeted arm explodes the 129 regions owning
them; the shell still does not close; recoverPass 1 and 2 then call explodeAll() and
level all 3,777 analytic regions -- 98 correctly built cylinders included -- to chase 69
bad chains. Chain construction is 99.4% successful. **The response is the defect, not the
geometry.** This retires the "mass edge-construction failure" reading entirely.

### Attempts, all instrumented, none successful

| # | change | fired? | result |
|---|---|---|---|
| 1 | U2 cascade brake (STL2STEP_N24_U2_BRAKE) | **no** — N24_U2_REACHED=0 | decideCascade's U2 path never executes on mechparts/9. Wrong code path. |
| 2 | STL2STEP_N13_TARGETED_EXPLODE (pre-existing) | **no** — N13_TARGETED=0 | unreachable: the block is `if (!did && n13Targeted)` (:5921) and the chainEdgeFail arm above it already set did=true. |
| 3 | blanket brake (STL2STEP_N26_NO_BLANKET) | **yes** — held=1 | explodes 3777 -> 157, **cylinders still 0**: refusing to explode leaves did=false, falls to heal-discard, whole build discarded. Predicted before writing it, then measured. |
| 4 | + keep built faces on that exit (n26b) | **yes** — kept=1 | ok:true, watertight:true, freeEdges=0, **cylinders still 0**: by the time the brake engages the cylinders were already exploded in the first targeted pass. Keeping the build is too late. |

The lesson from 3 and 4 together: the damage is done at recoverPass=0 by the *targeted*
arm plus the rebuilds, not only by the blanket. Any fix must stop the cylinders being
exploded in the first place, or rebuild them after the shell question is settled.

### Second opinion (Kimi), findings that stand on their own

- mechparts/9 has **541 free edges**; N13_SEW_FREE sews 26,533 faces and reports
  `closed=0 accepted=0`. They are NOT duplicate TShapes a sewing pass can merge at
  Precision::Confusion()*100. Sewing is a dead end for this part.
- mechparts/22's t4: realized `dV=779` against `budget=90`, and budget = max(1e-4*meshVol,
  3*dVolAbs) = 90.28 implies the fits predicted **dVolAbs < 30 mm^3**. The analytic fits
  mispredicted their own volume effect by ~26x. That is a defect in dVolPredicted, not a
  tolerance to widen -- and it means a "realized vs predicted" gate would be principled
  only once dVolPredicted is trustworthy.

### Still true after all of it

Shipped cylinders on mechparts/9, 11, 22 remain **0**, and no part ships a torus.
Live service is v1.6.0. Nothing from section 17 is deployed.

## 18. n27 — the targeted explode was destroying VICTIMS, and a delegated executor refuted my premise

Delegated to a DeepSeek executor via /opencode-orchestrate to bisect an apparent flag
INTERACTION: with the four N27 flags on, L07_collar_normal dropped 1 cylinder -> 0, while
(per Kimi's log) each flag alone was clean.

**The executor refuted that premise.** It measured `B alone -> 0` five separate ways
(script x3, manual, and a second binary) and said the stated fact was stale. There is no
interaction: `{B}` = STL2STEP_N13_TARGETED_EXPLODE alone is the culprit, and every subset
containing B fails while every subset without it ships 1. I had passed Kimi's number
through without re-measuring it; the executor catching that is worth more than the fix.

### Mechanism, cited

On L07 the inner cylinder rid=4 (R=1.5, closed360) fails its face build and is exploded
(refit_build.cpp:5323), leaving **10 free edges owned by 6 PLANE faces**. The targeted arm
explodes every free-edge owner (:6109) -- but those planes are **victims**: their edges
went free because the neighbouring cylinder was removed, not because they are defective.
Exploding them makes the shell worse, **10 -> 152 free edges**, because
uncollapseRegionChains/restoreShared dirty the shared vertex TShapes of the surviving R16
cylinder rid=0. At recoverPass=1 the blanket explodeAll() (:6144) then wipes rid=0 and
rid=3 -> 0 cylinders. The off path never touches the planes: its keepCyl else-branch
(:6117-6128) explodes only the junk partial cylinder rid=3, and the shell closes.

This is the pathology this codebase already recorded -- "of 160 exploded regions, 110 never
failed a build". The targeted arm was written to cure it and reproduced it.

### Fix (refit_build.cpp:6109-6130, inside the existing B gate)

Skip a free-edge owner that borders, via any chain, a cylinder that is already exploded or
is partial (non-360). The free edge is that cylinder's fault and exploding the victim
cannot re-pair the boundary. `did` stays false and the existing blanket else-branch
explodes the partial cylinder instead -- the same outcome as the off path. With B off the
new code never executes.

### Verified by me, not taken on trust

| check | result |
|---|---|
| off-path L07_collar_normal | 1 cylinder (unchanged) |
| off-path L08_pillow_block_normal | 5 cylinders (unchanged) |
| **mechparts/22** | **0 -> 3 cylinders, ok:true, watertight:true** |
| mechparts/9 | 0 -> 0 (unmoved) |
| mechparts/11 | 0 -> 0 (unmoved) |
| mechparts/15 | 1 -> 1 (no regression) |
| mechparts/8 | 2 -> 2 (no regression) |
| cadbench normal | 73.67 == 73.67, health 200/203 both, 0 models better or worse |
| cadbench fine | 50.13 == 50.13, health 74/78 both |

mechparts/22 is the first genuine cylinder recovery on the user's curved parts this
session, independently reproduced.

### The four N27 flags

| flag | change |
|---|---|
| STL2STEP_N27_SEW_TOL_MM | N13_SEW_FREE sewing tolerance override; the default was Precision::Confusion()*100 = 1e-5 mm, six orders below the 0.05-0.07 mm duplicate distance, which is why sewing merged nothing |
| STL2STEP_N13_TARGETED_EXPLODE | arm decoupled from `did` so it runs at all, PLUS the victim skip above |
| STL2STEP_N27_T4_REL | t4 budget floor max(budget, frac*meshVol); part 22's realized dV=779 vs budget=90 while the fits predicted only 24.4 |
| STL2STEP_N27_SEW_FIXFACE | ShapeFix_Face per invalid sewn face, with closure+validity re-check and built[] remap |

## 19. v1.8.0 deploy record

`~/.local/share/mesh2step-native-v1.8.0-fc0d7911ba1b`, md5 fc0d7911ba1b.
Rollback chain: native.conf.v180-rollback (v1.6.0), .v170-rollback, .v160-rollback.
Gates proven live through run.sh (mechparts/22 cyl=3). API end-to-end: ok:true,
is_solid, watertight, free_edges=0, 1338 faces, 22.61 s.

Engine patch: .claude/loopspec/patches/n19-n27-engine-arms.patch
Kimi's lane document: .claude/loopspec/FINDINGS-N27-kimi.md

### What is honestly fixed, and what is not

Fixed: the t4-revert class (mechparts/22) and the victim-plane cascade that cost
L07_collar its only cylinder. Corpus cost: zero.

NOT fixed: mechparts/9 and /11 still ship 0 cylinders despite recognising 98 and 56
cylinder regions respectively. Both are blocked on shell closure, and for part 9 sewing
is provably not the answer (N13_SEW on 26,533 faces: closed=0 accepted=0 -- the 541 free
edges are not duplicate TShapes at any tolerance tried). 37 of the 40 user parts remain
unmeasured for cylinder count.

### The pattern, stated once because it recurred three times today

The engine destroys valid geometry while reacting to small localised faults:
 - 0.6% of chains fail (69 of 11,498) -> 3,777 regions exploded, 98 built cylinders lost;
 - one 2-triangle 90-degree patch carries an honest 2.93 mm sagitta -> four 144-sided
   bores fitting to 0.0002 mm are exploded;
 - six plane faces own free edges they did not cause -> free edges 10 -> 152 -> the whole
   collar reverts.
Every fix that worked today was a proportionality fix, not a geometry fix.
