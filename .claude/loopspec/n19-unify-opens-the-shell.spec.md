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
