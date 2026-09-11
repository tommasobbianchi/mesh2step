# n6 — the post-build oracle: stop predicting BRepCheck, ask it

Opened 2026-09-07 by decision: the oracle route is its own chapter, not a continuation of n5e.

## Why this chapter exists

n5e tried three times to decide, BEFORE a face exists, whether a chain's analytic curve is fit
to use. Each attempt destroyed 40 true cylinders on three fine meshes:

| budget tried | fine meshes (12/16/12 true cylinders) | SpeedTestStructure_normal |
|---|---|---|
| min incident edge / (2*47) | 0 / 0 / 0 | +178 |
| engine's own analyticSnapCap | 0 / 0 / 0 | 0 |
| endpoint coverage only | rejects the same chains (P64) | -- |

The measurements say a pre-emptive veto CANNOT work here, and say why:

1. The engine deliberately accepts curves that miss their own terminals -- `snapVertexToCurve` /
   `bumpVertexTol` widen the TVertex tolerance to cover the gap. v1.1.0-n5h builds the 12 true
   lead-fillet cylinders using curves that miss by **0.014787 mm median**.
2. The populations OVERLAP: fine-mesh chains reach 0.511402 mm; the genuinely broken
   plane-cylinder ellipse reaches 1.341694 mm. No magnitude threshold separates them.
3. `residInterior` is 0.000000 median in the rejected population, so the "interior residual"
   rule was already an endpoint rule in disguise -- which is why gating on endpoints changed
   nothing (P64 refuted).
4. The constant behind the first budget (K = 47) came from P55's ratio claim, which was itself
   refuted when the ratios rose to 7841 with the same edges still invalid.

## The claim

The codebase's validity oracle is `BRepCheck` on BUILT shapes, and it already runs downstream
(`finishPartial` -> `faceIsValid` -> pcurves -> `ShapeFix_Face` -> `ensureFaceValid`). The n5e
rule tried to PREDICT that oracle one stage early, where the face does not exist. The chapter's
claim is that the prediction should be deleted and the oracle consulted directly, with the
culprit banned per CHAIN through machinery that already exists.

Precedent in the tree: the dual-face incidence guard at `refit_build.cpp:4959-4992` already does
exactly this shape of thing --
`fallbackBanned[ci] = 1; collapseBanned[ci] = 1; collapsed[ci] = 0; geom[ci] = {};
restoreShared(); goto try_rebuild;`

## Arms and predictions (all pending; a refuted prediction rewrites its arm, never edited)

- **P65** the four bad plane-cylinder ellipse chains on SpeedTestStructure produce faces that
  `BRepCheck` rejects, while the fine-mesh lead-fillet chains produce faces it ACCEPTS.
  Predicted: the oracle separates the two populations that every magnitude threshold conflated.
  Falsified if the fillet faces are also invalid (then n5h ships invalid faces today, which
  would itself be the finding).
- **P66** banning per CHAIN is sufficient: banning only the chains whose edge carries the
  failing status clears the invalid faces without exploding the region.
  Predicted: SpeedTestStructure keeps its 178 cylinders and the three fine meshes keep 12/16/12.
  Falsified if a per-chain ban cascades into region explosion (watch Body11's 127-cylinder
  component, which the comment at `refit_build.cpp:4564-4566` warns about).
- **P67** the retry terminates: each ban strictly reduces the set of collapsed chains, so the
  `goto try_rebuild` loop is bounded by the chain count.
  Predicted: no model exceeds a small number of extra rounds; measure the distribution.

## Gates (unchanged, and the full set)

- MISSED_silent_wrong_rebuild = 0 on the 26 negatives for that sha.
- 2b v2 with no row worse than the current production baseline.
- **models worse = 0**, measured on the FULL 333-model corpus, with the three fine meshes
  (NEG_SC-59_fine 12, NEG_SOT-143_fine 16, NEG_TSOT-23_fine 12) as named regression sentinels
  because their ground truth was read from the source KiCad CAD.
- recall strictly up; geometric equivalence for every model whose bytes differ.
- One defect per commit, and BISECT before attributing any regression -- the n5e gate
  misattributed the curve rule's damage to J6 until the same tree was built without J6.

## Relationship to n5j

`n5j-j6-progress` (commit c3c3a56) is committed, gated and unpromoted. Alone it changes nothing;
the +178 needs whatever makes the last four free edges healable. If this chapter's oracle route
produces that condition, n5j lands with it -- gated together, one promotion.

## Tests

F2P already written and red against the live baseline:
`tests/test_n5e_speedtest_builds.py::test_in_band_cylinders_reach_the_target` (>= 144 on
SpeedTestStructure_normal). The sibling test `test_the_component_stops_reverting` targets the
COARSE variant, which is a different defect (151 planned cylinders with a 12.9 % median radius
residual -- garbage fits) and stays red on purpose; it belongs to the n5g relative-threshold
work, not here.

### P65 — CONFIRMED (binary 90cf1076124c, branch n6-p65-oracle from c3c3a56,
### parity SAME vs v1.1.0-n5h on L06_adapter_plate_normal and NEG_SC-59_fine)

BRepCheck verdict on every face as it leaves the per-region build, before the repair loop:

| model | Cylinder valid / invalid | Plane valid / invalid | other |
|---|---|---|---|
| NEG_SC-59_fine | 60 / **0** | 54 / 2 | 36 / 0 |
| NEG_SOT-143_fine | 68 / **0** | 162 / 3 | 60 / 0 |
| NEG_TSOT-23_fine | 30 / **0** | 22 / 0 | 36 / 0 |
| SpeedTestStructure_coarse | 681 / **0** | 1624 / 155 | 4650 / 0 |
| SpeedTestStructure_normal | 3449 / **0** | 2822 / 430 | 9600 / 0 |

(counts accumulate over cascade passes, since the diagnostic fires on each buildFaces call.)

**EVERY cylinder face is valid on every model; ZERO invalid cylinders anywhere.** All
invalidity is in PLANE faces. Dominant status by far: `UnorientableShape,SelfIntersectingWire`
(consistent with P35's 902 UnorientableShape), with `BadOrientationOfSubshape` on a handful of
1- and 34-triangle planes.

Reachability control satisfied: valid=0 IS observed, on four of the five models, so the zero on
cylinders is a measurement and not a dead branch.

**Consequence.** The oracle separates exactly the populations that every magnitude threshold
conflated:
- the fine-mesh lead-fillet cylinders (12 / 16 / 12, CAD-verified true) build VALID faces, so
  any rule that rejects their curves is wrong by construction -- which is what n5e's three
  budgets kept doing;
- the damage from the bad plane-cylinder ellipses lands on the PLANE faces they bound (regions
  392 / 394 / 508 / 513, the near-flat micro-regions of P56), and those faces are invalid.

So banning the chains of INVALID faces touches planes only and cannot cost a single cylinder.
That is the mechanism P66 now has to confirm end to end.

**Note for n5g constant 2:** 430 invalid plane faces on SpeedTestStructure_normal and 155 on
coarse is a large population, and its signature (SelfIntersectingWire on 3-, 4- and 8-triangle
planes) is the near-flat micro-region population again. The oracle may be treating a symptom
whose cause is constant 2; measure the overlap before assuming they are independent.

## P65 — CONFIRMED (W5, binary 186ebb824a66, parity SAME on L06 and NEG_SC-59, control branch
## n6-p65-oracle from c3c3a56; lineage checked: contains c3c3a56, does NOT contain 720320a)

Faces judged by BRepCheck_Analyzer on the built face, no pre-emptive rule in the tree.

| model | final pass | total | valid | invalid | cylinder faces | cyl invalid |
|---|---|---|---|---|---|---|
| NEG_SC-59_fine | 2 | 76 | 76 | 0 | 12 | **0** |
| NEG_SOT-143_fine | 2 | 196 | 196 | 0 | 16 | **0** |
| NEG_TSOT-23_fine | 1 | 88 | 88 | 0 | 12 | **0** |
| SpeedTest_coarse | 3 | 2522 | 2449 | 73 | 75 | **0** |
| SpeedTest_normal | 6 | 3440 | 3367 | 73 | 0 | -- |

**All 40 CAD-verified true lead-fillet cylinder faces are VALID, statuses empty.** Across all 5
models and all 14 buildFaces passes, EVERY invalid face is a Plane region face -- never a
cylinder, never a facet.

Status signature of the invalid planes: `UnorientableShape,SelfIntersectingWire` (coarse 72 of
73, normal 60 of 73) and `BadOrientationOfSubshape` (1 and 13).

**Consequence.** The n5e pre-emptive rule destroyed VALID CYLINDER faces in order to prevent
INVALID PLANE faces. It punished the wrong population, which is why no budget could separate
them: the two populations were never distinguished by any property of the curve.

Reachability control satisfied: valid=0 observed on 4 of 5 models, so valid=1 on the 40 cylinder
faces is a measurement, not an unreached counter.

**Two facts that shape the fix:**
1. On the fine meshes the invalid planes appear in pass 1 (2 on SC-59, 3 on SOT-143) and are
   ALREADY REPAIRED to 0 by the final pass. The existing cascade/retry machinery works.
2. On SpeedTestStructure the 73 persist to the final pass, and the diagnostic lists the chains
   each invalid face uses, with collapsed ones marked. That is the ban candidate set for P66.

Caveat carried forward from the worker, not glossed: buildFaces runs multiple times per
conversion (2, 2, 1, 3 and 6 passes on the five models); all headline numbers above are the
FINAL pass, which is the one that produces the STEP. Facet faces from exploded regions inherit
the exploded region's rid, so a `src=region|facet` split was needed to avoid counting facet
triangles as plane faces.

### Reconciliation of the two P65 sections above (they are ONE finding at two aggregations)

The spec carries two P65 tables, from binaries 90cf1076124c and 186ebb824a66. They do not
disagree; they aggregate differently, and the difference must not be quoted as a discrepancy:

- 90cf1076124c counts **accumulated over every buildFaces pass** (the diagnostic fires on each
  call, and a conversion makes 1-6 of them). Hence 3449 cylinder faces and 430 invalid planes on
  SpeedTestStructure_normal.
- 186ebb824a66 adds a `pass=` counter and reports the **FINAL pass**, which is the one that
  produces the STEP. Hence 0 cylinder faces and 73 invalid planes on the same model.

Both report **zero invalid cylinder faces**, on every model, in every pass. That is the finding.

**The final-pass numbers are the ones to quote** (73 invalid planes on each SpeedTestStructure
variant, 40 valid true-fillet cylinders across the three fine meshes). The accumulated figures
count the same face several times across retries. The n5g constant-2 note above cites 430 and
155; those are accumulated, and the corresponding final-pass figures are 73 and 73. The
observation itself stands -- the invalid planes are 3-, 4- and 8-triangle near-flat micro-regions
with a SelfIntersectingWire signature, which is the P56 population -- and the overlap with
constant 2 must still be measured before the two are assumed independent.

## P66 — REFUTED as a recall fix, CONFIRMED as a safe correctness fix
## (W6, binary ff4127bec0d7, branch n6-p66-chainban; lineage contains c3c3a56, excludes 720320a)

Rule: when a built face is BRepCheck-invalid, ban the COLLAPSED chains of that face's own region
via the existing fallbackBanned/collapseBanned/goto try_rebuild precedent, never exploding the
region, behind STL2STEP_ORACLE_BAN. Counters oracleBannedChains / oracleRounds in RESULT.

| model | cyl OFF/ON | reverted OFF/ON | banned | rounds | STEP data |
|---|---|---|---|---|---|
| NEG_SC-59_fine | **12 / 12** | 0 / 0 | 18 | 1 | DIFF |
| NEG_SOT-143_fine | **16 / 16** | 0 / 0 | 25 | 1 | DIFF |
| NEG_TSOT-23_fine | **12 / 12** | 0 / 0 | 0 | 0 | SAME |
| L06_adapter_plate_normal | **14 / 14** | 0 / 0 | 0 | 0 | SAME |
| L01_rod_normal | 1 / 1 | 0 / 0 | 0 | 0 | SAME |
| SpeedTestStructure_normal | 0 / 0 | 1 / 1 | 342 | 8 | DIFF |
| SpeedTestStructure_coarse | 0 / 0 | 1 / 1 | 163 | 8 | SAME |
| L08_T_bracket_recon_normal | 0 / 0 | 1 / 1 | 59 | 4 | SAME |
| L04_soap_bar_normal | 0 / 0 | 1 / 1 | 0 | 0 | SAME |
| gripper_gear_normal | 11 / 11 | 0 / 0 | 0 | 0 | SAME |
| clamp_half_a_normal | 0 / 0 | 1 / 1 | 67 | 1 | SAME |

**CONFIRMED, and it is the first change in this campaign that costs zero cylinders:** all three
sentinels hold (12/16/12) and L06 keeps 14. Reachability proven -- banned > 0 on 6 of 11 models
with the env set, 0 on all 11 with it unset.

**Invalid faces on SpeedTestStructure_normal, per pass, env ON:**
75 -> 27 -> 2 -> 1 (passes 4-10) -> 1 -> 1 -> 1 -> **0** at pass 14. Every invalid face fixed.

**REFUTED as a recall fix.** SpeedTestStructure still builds 0 cylinders and still reverts. Face
validity was never the blocker. Note this binary ALREADY CONTAINS n5j's J6 progress condition, so
J6 progress + oracle ban together still give 0 -- whatever the n5e curve rule did to unlock the
+178 is neither "fix invalid faces" nor "uncollapse chains" (the ban uncollapsed 342 of them).

**P67 CONFIRMED with a caveat**: rounds bounded, max 8 observed. But on SpeedTestStructure the
8-round guard STOPPED the process with one invalid face still present (passes 9-13 show
invalid=1 and no further banning), so termination came from the guard, not from exhaustion.

Worker method notes worth keeping:
- The STEP comparison must be on the DATA SECTION, not the whole file: the header carries a
  wall-clock timestamp, so a whole-file hash reports DIFF on every row and measures nothing.
- Three rows have banned > 0 and SAME data (coarse 163, L08 59, clamp_half_a 67): the ban fired,
  rebuilt, and the shipped shape was identical anyway.

## Where this leaves the chapter

The oracle route is SAFE and CORRECT but does not deliver recall. It is not promotable alone
("recall strictly up" fails), and it is not the +190 lever.

The remaining common root across every thread of this campaign is n5g CONSTANT 2: the near-flat
micro-regions at 2.0016 / 2.1394 deg produce the bad plane-cylinder ellipses (P59), the vertex
bumps (P56/P57), AND the invalid plane faces the oracle has been cleaning up (their signature is
SelfIntersectingWire on 3-, 4- and 8-triangle planes -- that population). Constant 2 should be
measured next, before any further attempt to unlock SpeedTestStructure from below.

---

## P82 — the two negative regressions are ONE cause, not two (pending, 2026-09-10)

Measured before predicting (RESULT counters only, both arms, corpus `~/corpora/cadbench`):

| model | truth cyl | arm | builtComponents | revertedTrue | adoptedNoCyl | cyl in STEP |
|---|---|---|---|---|---|---|
| `NEG_SOT-1334-1_fine`          | 1  | A | 1 | 0 | 0 | 1 |
| `NEG_SOT-1334-1_fine`          | 1  | B | 0 | **1** | 0 | 0 |
| `NEG_SOT-23W_Handsoldering_fine` | 12 | A | 1 | 0 | 1 | 1 |
| `NEG_SOT-23W_Handsoldering_fine` | 12 | B | 0 | **1** | 0 | 0 |
| `NEG_SuperSOT-3_fine` (the WIN) | 12 | A | 0 | **1** | 0 | 0 |
| `NEG_SuperSOT-3_fine` (the WIN) | 12 | B | 1 | 0 | 1 | 12 |

So the win and the two losses are the SAME switch flipping in opposite directions:
`usedRefit` true↔false on a single component. On the two losses arm B builds *nothing at
all* — every counter is 0 — which is a whole-component revert, not a per-face loss.

**P82 (prediction, on disk before instrumenting):** run arm B on both losing models with
`--diag-revert-cause`. Both will report a NON-EMPTY `revertCause` (a real revert, agreeing
with `revertedTrue=1`, unlike instrument error #13 where the string read
`counted-not-reverted`), and the two strings will name the **same** cause. One fix
therefore addresses both rows.

**Refutation conditions, stated in advance:**
- either string is empty / `counted-not-reverted` → `revertedTrue` is a third lying counter,
  and P82 is refuted at its premise;
- the two strings name different causes → two defects, not one; the "they may share one
  cause, both are SOT-family" hypothesis in VERIFY-2026-09-10 is refuted and each row gets
  its own arm.

**What P82 does NOT claim.** It does not claim the cause is the well-conditioned-ellipse
acceptance (`2549e00`) rather than the ISLE_CAP refusal (`6bb29ed`). Both are default-on and
new vs n5h. Attributing the revert to one of them needs a second binary with that one commit
reverted, and that is a separate prediction, written only if P82 holds.

### P82 — REFUTED (measured 2026-09-10, `--diag-revert-cause`, arm B `877511d32a98`)

Both strings are non-empty, so the premise holds: `smoothRevertedTrue` is honest here and
these are real reverts, not instrument error #13 again. But the two causes are **different**:

| model | arm B `revertCause` (head) |
|---|---|
| `NEG_SOT-1334-1_fine` | `budget dV=0.000446 budget=0.000399` |
| `NEG_SOT-23W_Handsoldering_fine` | `buildFaces-false exit=j6-uncollapse line=5354 regions=58 rejects[FaceBuildFailed=1,FilletConsensus*=3,None=57,VertexResidual*=8]` |

**Two defects, not one.** The "both are SOT-family, they may share one cause" hypothesis in
`VERIFY-2026-09-10.md` is refuted; option 1 there is two pieces of work, not one.

- **SOT-1334-1 is a BUDGET miss, with no build failure at all.** The analytic rebuild
  succeeded and was thrown away because its volume deviation `dV=0.000446` exceeds the n5a
  revert budget `0.000399` by **11.8 %**. All-or-nothing revert: one over-budget component
  costs the model its single cylinder.
- **SOT-23W is a HARD BUILD FAILURE**, `FaceBuildFailed=1`, nothing built.

**A second, unasked-for finding, and the more useful one.** Arm A's failure on the model n6
*fixes* — `NEG_SuperSOT-3_fine`, `buildFaces-false exit=j6-uncollapse line=4784 regions=41
rejects[FaceBuildFailed=1,None=40,VertexResidual*=3]` — is the **same signature** as arm B's
failure on SOT-23W: same exit (`j6-uncollapse`), same single `FaceBuildFailed`, and in both
the plate table shows one `plate7 … loop{cyl=N,cap=?,natOri=F}` beside a `plate8` carrying a
mixed `plateOri=F/R` run. n6 did not remove that defect class — it moved which member of the
SOT family lands on it. The +12/-1 on this family is one defect trading places, and a fix
aimed at the signature (not at the model) would collect both.

**P83 (pending) — attribution.** Two default-on commits separate arm B from n5h:
`2549e00` (well-conditioned ellipse acceptance) and `6bb29ed` (ISLE_CAP refusal). Build one
binary from `0bac065` with ONLY `2549e00`'s condition re-gated behind `STL2STEP_ORACLE_ONLY`,
and run the three SOT models. Prediction: `NEG_SOT-1334-1_fine` returns to 1 cylinder with the
gate off (its `dV` falls back under budget, because accepting well-conditioned ellipses is
what raised `snapCap` and hence the rebuild's volume error), and `NEG_SuperSOT-3_fine` loses
its 12 (that gain is the same commit). Refuted if SOT-1334-1 stays at 0 with the gate off —
then ISLE_CAP, not the ellipse gate, owns the budget miss.

### P83 — REFUTED as stated, but it attributed one of the two rows (2026-09-10)

The premise was wrong: **there are not two behavioural commits between n5h and `0bac065`,
there are four.** Beyond `2549e00` (ellipse) and `6bb29ed` (ISLE_CAP), the range also carries
`c3c3a56` (n5j: J6 heals while making progress, instead of exactly one pass) and `0efdb79`
(n5e(b): `meshTolCap` = max(sewTol, measured chordSagitta) — the `0.2929*R` floor deleted).

Attribution binary `p83b-cc55645224b8`, built from `0bac065` in a scratch worktree with each
of the four re-gated behind its own off-switch. **Parity gate first:** with every switch unset
it reproduces arm B's DATA section byte-for-byte on all three models (`cea5a390113a`,
`9a3f3a40435a`, `959aa6e3e612`). **Reachability gate:** each switch is proven to move at least
one model, so no zero below is an unreached counter.

| model | BASE | noELLIPS | noISLE | noJ6MULTI | radFLOOR |
|---|---|---|---|---|---|
| `NEG_SOT-1334-1_fine` (arm A = 1) | 0 | 0 | 0 | 0 | **1** |
| `NEG_SOT-23W_Handsoldering_fine` (arm A = 1) | 0 | 0 | 0 | 0 | 0 |
| `NEG_SuperSOT-3_fine` (arm A = 0) | 12 | **0** | 12 | 12 | 12 |

**Read of the table.**

1. **The +12 win is `2549e00` alone.** Only `noELLIPS` removes it; the other three leave it.
   P83's second half is confirmed.
2. **P83's first half is refuted.** SOT-1334-1's loss is not the ellipse gate — it survives
   `noELLIPS` at 0. It is **`0efdb79`**: restoring the `0.2929*R` floor to `meshTolCap` is the
   only switch that brings the cylinder back, 0 → 1.
3. `0efdb79`'s own commit message claims the deleted term "was inert everywhere it fired" and
   that removing it left "all 83 outputs BYTE-IDENTICAL". **That claim does not hold on this
   corpus** — on `NEG_SOT-1334-1_fine` it is worth one cylinder, via `dV=0.000446` against
   `budget=0.000399`. The measurement was true of the corpus it ran on; it was read as a
   property of the change. (The corpus it ran on no longer exists — see `projects-lpc`.)
4. **Restoring the floor is an attribution, not a fix, and must not be shipped as one.**
   `0efdb79` removed the term because it licenses OCCT to identify points up to 15.83 mm
   apart. Buying back one cylinder on one negative at that price is a bad trade. The correct
   target is the all-or-nothing revert budget, which throws away a whole component — and its
   one good cylinder — for an 11.8 % volume overshoot.
5. **SOT-23W is attributed to none of the four.** Its cause lies in the remaining commits of
   the range; a per-commit walk over all 15 is running (`p83-walk`).

### The per-commit walk settles it, and it corrects both of the readings above

Every commit in `0efdb79..0bac065` built and run on the three models (`p83-walk`, 15 builds,
one scratch worktree, cylinders counted from the written STEP). First-parent history is
`0efdb79 → 720320a → fd11f7c(merge) → 42e0aea → … → 0bac065`; `c3c3a56`, `666f600` and
`ff4127b` sit on the side branch `n6-p66-chainban`, forked from `0efdb79`.

| commit | SOT-23W | SOT-1334-1 | SuperSOT-3 |
|---|---|---|---|
| `0efdb79` n5e(b), floor deleted | 1 | 1 | 0 |
| **`720320a`** WIP n5e: P58 + general curve-choice rule | **0** | **0** | 0 |
| `c3c3a56` (side branch) | 1 | 1 | 0 |
| `666f600` (side branch) | 1 | 1 | 0 |
| `ff4127b` (side branch) | 1 | 1 | 0 |
| `fd11f7c` merge of the side branch into the 720320a line | 0 | 0 | 0 |
| `42e0aea` … `d2dde56` | 0 | 0 | 0 |
| **`2549e00`** ellipse acceptance | 0 | 0 | **12** |
| `b3881bc` … `0bac065` | 0 | 0 | 12 |

**Both rows regress at exactly one commit: `720320a`.** The side branch, which does not
contain it, holds both at 1 through three commits — so `c3c3a56` (J6 multi-pass) and the
diagnostics are cleared, and the merge only reintroduces `720320a`'s content.

**P82 was right at the commit level and wrong at the mechanism level.** One commit causes
both; the two components then die by different proximate routes (a budget overshoot vs a
`FaceBuildFailed`). "Same cause" and "same failure mode" are not the same question, and
`--diag-revert-cause` answers only the second. Recorded as an instrument-scope lesson.

**Correction to the P83 reading above:** `0efdb79` does NOT cause SOT-1334-1's loss — at
`0efdb79` the model still builds its cylinder. The `radFLOOR` switch recovers it at HEAD
because the restored `0.2929*R` tolerance *masks* `720320a`'s defect, not because deleting
the floor created it. Sensitiser, not cause.

### What this actually is: the unrepaired residue of a KNOWN, PARKED regression

`720320a`'s own message says it: *"Parked, NOT promotable as a unit: the general curve-choice
rule regresses three models (NEG_SC-59_fine 12→0, NEG_SOT-143_fine 16→0, NEG_TSOT-23_fine
12→0)."* `2549e00` was written as the repair, and its message claims *"SC-59/SOT-143/TSOT-23
restored to n5h parity (12/16/12)"*.

Verified here on the rebuilt corpus — the repair is real, and it is also incomplete:

| model | A | B |
|---|---|---|
| `NEG_SC-59_fine` | 12 | 12 |
| `NEG_SOT-143_fine` | 16 | 16 |
| `NEG_TSOT-23_fine` | 12 | 12 |
| `NEG_TSOT-23-5_fine` | 20 | 20 |
| `NEG_TSOT-23-6_fine` | 24 | 24 |
| `NEG_SuperSOT-3_fine` | 0 | **12** |
| `NEG_SOT-1334-1_fine` | 1 | **0** |
| `NEG_SOT-23W_Handsoldering_fine` | 1 | **0** |

So `2549e00` repaired the three members `720320a` had measured, plus `SuperSOT-3` as a bonus,
and left the two members nobody had measured still broken. **The two regressions are not a
new defect introduced by the n6 work — they are the part of an already-known, already-parked
regression that the repair did not reach.** They were invisible because the gate ran on the
54-model negative set that contained the three named models and not these two. That is the
missing-manifest hazard, now with a name and a commit.

### Consequence for the promotion decision (still Tommaso's call — nothing taken)

The choice in `VERIFY-2026-09-10.md` changes shape. This is not "+189 against 2 unexplained
regressions"; it is "+189 against the 2 unrepaired members of a regression `720320a`
introduced and `2549e00` was written to repair". Option 3 (waive) is weaker than it looked:
waiving means shipping a known defect whose repair already exists and is simply incomplete.
Option 1 (fix) is now a defined piece of work — extend `2549e00`'s acceptance until these two
members also come back — rather than an open-ended investigation.

**Not attempted here, and deliberately.** Widening the eccentricity constant until these two
pass would be fitting the constant to the two models that fail, which is the same error as
re-scoping the negative set after seeing who fails. Any widening has to be justified by what
the ellipse actually is on these two, and re-gated on the whole 78, before it is a fix.

### Correction: the fix is NOT "extend the ellipse acceptance". Not one ellipse is involved.

The paragraph above assumed the repair path for these two runs through `2549e00`'s
eccentricity gate, because that is what repaired the other three. Measured instead of
assumed — `STL2STEP_DIAG_VETO=1` on arm B, `AnalyticCurve::Kind` = {0 None, 1 Lin, 2 Circ,
3 Elips}:

| model | vetoed chains | kind | residual vs budget |
|---|---|---|---|
| `NEG_SOT-1334-1_fine` | **2** | `2` = **Circ** | 0.005630 vs 0.000106 (53×) |
| `NEG_SOT-23W_Handsoldering_fine` | ~200 | `1` = **Lin** (every one) | 0.001254–0.007831 vs 0.000238/0.000519 (5–33×) |
| `NEG_SuperSOT-3_fine` (builds 12) | 16 | `1` = Lin | 0.013–0.0145 vs 0.000297 (44–49×) |

**Zero `Elips` vetoes on either failing model.** `kMaxElipsEccentricity` cannot be the lever;
widening it would have done nothing, and the "extend `2549e00`'s acceptance" framing above is
withdrawn. Note also that SuperSOT-3 carries 16 Lin vetoes at a *worse* residual ratio and
still builds all 12 cylinders — so a veto is not by itself fatal, and veto count is not the
discriminator either.

What the numbers do say, narrowly and without a proposed fix:

- SOT-1334-1 is the clean case. Truth is a single cylinder, r = 0.15, with 4 circle edges;
  exactly **two** circular chains are vetoed and the polyline is kept for both. Those are
  almost certainly that cylinder's two cap circles. Keeping them as polylines is what moves
  the rebuilt volume to `dV = 0.000446` against `budget = 0.000399`. Two chains, one
  cylinder, 11.8 % over — the smallest reproducer of `720320a`'s defect in the corpus, and
  the right model to work on first.
- SOT-23W is the bulk case, ~200 straight chains vetoed, ending in `FaceBuildFailed`.

**Stopping here (R1).** Three rounds on this defect: P82 (refuted, split the two rows), P83
(refuted, cleared four commits and produced a false attribution I have corrected), the
per-commit walk (settled it on `720320a`). The diagnosis is complete and the next step is a
code change to a parked commit's rule, which is a promotion-track decision, not an
investigation. No code changed on any arm; the two scratch worktrees and the two attribution
binaries (`p83-ce7d5a1e2b79`, `p83b-cc55645224b8`) are diagnostic only and belong to no arm.

---

## P84 — the vetoed chain on SOT-1334-1 is judged AFTER F1 replaced it (pending, 2026-09-11)

Task: fix `720320a`'s curve rule on `NEG_SOT-1334-1_fine`. Measured first.

`DIAG_VETO` on arm B, raw: **two lines, both identical** —
`A=0 B=1 kind=2 resid=0.005630 budget=0.000106 nV=26`. With
`SurfType {Plane, Cylinder, …}` that is **plane|cylinder**, curve kind **Circ**, a 26-vertex
chain. The model's truth is one cylinder, r = 0.15, so this is that cylinder's cap ring, and
the residual is **3.75 % of R** — far too large for a circle fitted to points that lie on the
cylinder, and suspiciously *identical to six decimals* on both reported chains.

Directly upstream of the rule sits **F1**: for `curve.kind == Circ` on a closed360 cap, the
curve is REPLACED wholesale by `cylinderIsoCircle(*cylR, v)` — a circle regenerated from the
fitted cylinder's axis and `Region::radius`, at an axial coordinate `v` taken from the plane
when `planePerpCylinder` holds. F1 exists for a good reason (IntAna's own radius is ~1e-7 off
the fitted R, which desyncs the 3d circle from the surface and BRepCheck-fails the seamed
face). But the curve rule then judges the REPLACEMENT, never the curve that was chosen.

**P84:** on this chain the pre-F1 curve's `residChain` is at or below budget, or at least an
order of magnitude under the post-F1 0.005630. The veto is then an artefact of F1's snap —
the rule rejects a curve F1 substituted in, and falls through to a line-fit rescue that a
26-vertex circle can never pass, so it keeps the polyline and the cap is lost.

**Refutation conditions, stated in advance:**
- pre-F1 residual is also ≈ 0.005630 → F1 is exonerated, the chain is genuinely non-circular
  at that tolerance, and the defect is upstream in the chain or the cylinder fit. P84 refuted
  and the fix must not touch F1.
- the two DIAG lines turn out to be one chain seen in two J6 passes rather than two cap rings
  → does not refute P84, but the "both caps" reading in the paragraph above is withdrawn.

Instrument: extend `DIAG_VETO` to print, for the same chain, the residual of the curve as
chosen BEFORE the F1 block, the post-F1 residual, `cylR->radius`, and the axial offset
between the pre- and post-F1 circle centres. Diagnostic build only, no arm.

### P84 — REFUTED. F1 is a no-op here; the CYLINDER RADIUS is wrong by 3.75 %

```
DIAG_P84 f1=1 preKind=2 preResid=0.00563002 postResid=0.00563002
         preR=0.15562995 postR=0.15562995 dCentre=0.00000000 cylR=0.15562995
```

F1 ran (`f1=1`) and changed nothing: same radius, same centre, same residual to eight
decimals. **F1 is exonerated** — the rule is judging exactly the curve that was chosen, and
any fix that touches F1 is aimed at the wrong thing.

The number that matters is on the same line. `truth.json` gives this model **one cylinder,
r = 0.15**. The fitted `cylR->radius` is **0.15562995** — too large by 0.00562995, which is
`preResid` to eight decimals. The residual is not a curve-choice problem at all: it is
**entirely the cylinder's radius error**, reappearing as the distance from a circle of the
wrong radius to mesh vertices that lie on the right one.

For scale: the `fine` deflection on this model is 4.4845/2000 = **0.00224 mm**, so the fit
error is **2.5× the tessellation error** — well outside anything the mesh can excuse.

**This changes what "fixing the curve rule" means.** At n5h the chain was accepted and the
model reported 1 cylinder — but that cylinder was 3.75 % oversized, and the count never said
so. `720320a`'s rule is **right** to veto it: the chosen curve genuinely does not fit the
points. Relaxing the rule, widening the budget, or exempting closed360 caps would all buy the
count back by re-admitting a measurably wrong cylinder. That is not a fix; it is restoring a
defect the new rule exposed.

The defect to fix is upstream: **why does the cylinder fit return 0.15563 for a 0.15 feature?**
If that is corrected the residual collapses on its own, the chain passes the rule unchanged,
and the cap builds. Recorded as the next arm; `NEG_SOT-1334-1_fine` is the reproducer.

## P85 — the radius is inflated by the COARSE sec-lift, on a model that is not coarse

Chain of measurements on `NEG_SOT-1334-1_fine`, each one narrowing the previous:

| where | value |
|---|---|
| mesh vertices, radial distance about the built axis (52 of them) | **0.150000** exactly, min = max |
| `eberlyCenterRadius` on the 52-triangle region | **R = 0.14999999**, point radials 0.14999993…0.15000002 |
| `fillCylinderRegion` for that same 52-triangle region | **R = 0.15562995** |
| the built cylinder in arm A's STEP | **R = 0.15562995** |

The fit is correct. The radius is inflated **after** it, inside `commitEval`, and the only
thing between the two is the sec-lift:

```
if (!lawBand && coarseFusionBand(mv) && ev.d2.nSides >= 3 && !ev.d2.spanReject)
    refineCylinderRadius(...);
```

`coarseFusionBand(mv)` is `mv.nTri >= 500 && mv.nTri <= 1200`. **This model has exactly 500
triangles** — it sits on the first integer of the band. It is not a coarse mesh: it is a 4.5 mm
part at `fine`, deflection 0.00224, whose vertices lie on the cylinder to 1e-7. A triangle
count is being used as a proxy for tessellation coarseness, and on a small part the proxy is
simply wrong.

**P85:** inside `refineCylinderRadius`, `rPick` comes from `rChordMed` (not `rInscribed`), and
`rChordMed` > R because `chord` is measured as a **3-D** distance, `(p1 - p0).Modulus()`, while
the angle `dAng` that divides it is purely **azimuthal** (computed from `r0`, `r1`, the
axis-projected components). Any vertex pair that spans two rings of the cylinder therefore
contributes `sqrt(chord_perp² + dz²) / (2 sin(dAng/2))`, which is larger than R by exactly the
axial term. On a two-ring cylinder most pairs are cross-ring, so the median is inflated.

**Refutation conditions:** `rPick` comes from `rInscribed` instead (then the defect is the
`nEff <= 12` inscribed branch, not the chord math); or `rChordMed` ≈ 0.15 and the lift comes
from somewhere else entirely; or the chord pairs turn out to be same-ring only.

If P85 holds, the fix is not in `720320a`'s curve rule at all — the rule was right, and it was
the first thing in the pipeline honest enough to notice a 3.75 % radius error that n5h shipped
silently.

### P85 — CONFIRMED, exactly as written

```
gate OFF  DIAG_LIFT Rin=0.14999999 nEff=26 nChord=52 rChordMed=0.15562995
                    rInscribed=0.15110169 rPick=0.15562995 rHint=0.15000008
gate ON   DIAG_LIFT Rin=0.14999999 nEff=26 nChord=52 rChordMed=0.14999999
                    rInscribed=0.15110169 rPick=0.14999999 rHint=0.15000008
```

`rPick` came from `rChordMed`, not `rInscribed` (`nEff = 26` excludes the inscribed branch's
`nEff <= 12` anyway), and `rChordMed` was inflated by exactly the axial term. Using the chord
of the **projected** circle collapses it to `0.14999999` — the eberly value, to eight decimals.

`NEG_SOT-1334-1_fine`: **0 → 1 cylinder**, and the cylinder is now geometrically right —
built `R = 0.14999999` against a truth of 0.15, where arm A shipped **0.15562995**. So this is
not the count being bought back: n5h's "+1" was a 3.75 %-oversized cylinder, and the fix
produces a correct one.

**The fix, and why it is not in `720320a`.** `refineCylinderRadius` (`refit_math.cpp` 625–945)
derives a radius from `chord / (2·sin(dAng/2))` at **five** sites. `dAng` is azimuthal
throughout — computed from `r0`, `r1`, the components with the axis projected out — while
`chord` was the full 3-D distance `(p1 - p0).Modulus()`. Any vertex pair spanning two rings
therefore divides `sqrt(chord_perp² + dz²)` by an angle that only accounts for `chord_perp`.
On this model a 0.01 mm ring separation at r = 0.15 and 26 sides yields exactly the +3.75 %
observed. The patch adds `Vtx::rvec` and takes the chord between radial components at all
five sites, behind `STL2STEP_P85_PLANAR_CHORD`.

`720320a`'s curve rule needed no change. It was the first stage in the pipeline honest enough
to notice a wrong radius that n5h had been shipping silently; the defect it exposed is two
subsystems upstream.

**Why this model and not others.** The sec-lift only runs inside `coarseFusionBand(mv)` =
`nTri >= 500 && nTri <= 1200`. `NEG_SOT-1334-1_fine` has **exactly 500 triangles** — the first
integer in the band — while being a 4.5 mm part at `fine` whose vertices sit on the cylinder
to 1e-7. The band is a triangle-count proxy for tessellation coarseness, and on a small part
the proxy is simply wrong. That misclassification is a separate latent defect: worth its own
arm, not fixed here, because correcting the chord math removes the damage regardless of which
models the band captures.

Out of scope, recorded: `archChainRadiusFromPatch` computes `rChord` the same way. It is a
different, heavily-tuned subsystem gated on `radius >= 15`, so it is left alone and named here.

Gates running (`p85-sweep`, 281 models × 2 variants × 2 configs, timeout 1200 s):
PARITY (gate off, must be DATA-identical to arm B everywhere) and P85ON (delta and worse).

### P85 gate results — parity perfect, negatives fixed, main set FAILS

`p85-sweep`, binary `p85-2396b5a97c26` vs arm B `n6-877511d32a98`, 281 models, timeout 1200 s.

| config | set | A | B | delta | worse | DATA-identical |
|---|---|---|---|---|---|---|
| PARITY (gate off) | main 203 | 381 | 381 | 0 | **0** | **203 / 203** |
| PARITY (gate off) | neg 78 | 277 | 277 | 0 | **0** | **78 / 78** |
| P85ON | neg 78 | 277 | 278 | **+1** | **0** | 76 / 78 |
| P85ON | main 203 | 381 | 374 | **−7** | **2** | 193 / 203 |

Parity is exact everywhere, so the patch and all its diagnostics are provably inert when the
switch is off. On the negatives it does exactly and only what it was written to do:
`NEG_SOT-1334-1_fine` 0 → 1, nothing else moves.

**On the main set it fails the gate as written:** `L08_pillow_block_normal` 10 → 0 and
`L10_cross_slide_normal` 23 → 21, against `L09_crank_arm_normal` 2 → 7.

## P86 — but first: are those counted cylinders REAL? (pending, 2026-09-11)

Before calling −7 a regression, the same discipline applied to the negatives in
`VERIFY-2026-09-10.md` — check the count against truth. Built radii vs `truth.json`:

| model | truth radii (faces) | arm B builds | P85ON builds |
|---|---|---|---|
| `L08_pillow_block` | 2.5, 6.0, 15.0 (4) | **10**: 2.5×2, 6.0, 14.93, 14.99, **17.07×2, 17.89×2, 31.87** | 0 |
| `L10_cross_slide` | 2.0 (4) | **23**: 1.0×6, 2.0, **7.21, 7.25×7, 7.56, 7.70×4, 9.70×2** | **21**: 1.0×6, 2.0, **5.67×8, 5.95×4, 9.70×2** |
| `L09_crank_arm` | 2.5, 4.0, 8.0, 10.0 (5) | **2**: 2.5, 4.0 | **7**: 2.5, 4.0, 10.08, **13.03×2, 13.31×2** |

On `L08`, five of arm B's ten cylinders have radii that appear nowhere in the source CAD. On
`L10`, sixteen of twenty-three do. Both arms fabricate; they merely fabricate different radii.

**P86:** across the main 203, a material fraction of the cylinder faces counted by
`ab_corpus.py` have radii absent from `truth.json`, and under radius-matched counting the
P85ON −7 shrinks or reverses. **Metric consequence, stated plainly: "analytic cylindrical
faces in the written STEP" is not recall.** It cannot distinguish a recovered CAD cylinder
from an invented one, and it is the metric the whole `+189` in `VERIFY-2026-09-10.md` rests on.

**Refutation conditions:** the unmatched radii turn out to be legitimate (fillet strips or
split faces of a truth cylinder at a tolerance my matcher is too tight to see) → P86 refuted
and the counts stand; or the matched-only delta reproduces −7 → P85ON really is worse and the
chord fix needs narrowing, not the metric.

Measurement: per model and per arm, classify each built cylinder face as MATCHED (radius
within `max(0.5 %, 1e-4)` of some `truth.cyl_radii` entry) or UNMATCHED, on the main 203 at
`normal`. Radius equality is a necessary condition, not a sufficient one — a matched radius in
the wrong place still counts as matched here, so the matched figure is an UPPER bound on real
recall.

---

## P87 — SOT-23W: localise the single FaceBuildFailed (pending, 2026-09-11)

Arm B, `NEG_SOT-23W_Handsoldering_fine`:
`buildFaces-false exit=j6-uncollapse line=5354 regions=58 rejects[FaceBuildFailed=1,
FilletConsensus*=3,None=57,VertexResidual*=8]`.

Read of the control flow: `FaceBuildFailed` on its own is survivable — the cascade explodes
the region to facets, and line 5046 rewrites the reject to `ChainUnstable`. What is fatal is
the exit at 5351: once a J6 uncollapse pass has run (`j6UncollapsePass > 0`) and the rebuild
still fails, `buildFaces` returns false with no explode-recover, and the whole component is
reverted. So one unbuildable region out of 58 costs the model everything.

`buildOneRegion` can set `FaceBuildFailed` at five sites (4768 `failRidHits`, 4803
`isleRefuse`, 4849, 4906, 4942).

**P87:** the failing region is a **closed360 cylinder** and the site is NOT 4803 — ISLE_CAP is
already excluded by measurement (`noISLE` at HEAD left this model at 0, see the P83 table) and
4768 only fires under `STL2STEP_FAIL_RID`, which is unset. It will be one of 4849 / 4906 /
4942, i.e. a failure after `trySeamed360` and `tryTwoHalves` have both been tried.

**Refutation conditions:** the failing region is a plane or a fillet strip; or the site is
4803 after all (then the `noISLE` measurement was mis-read); or more than one region fails
(the `FaceBuildFailed=1` tally is per-pass and the rebuild retries could hide others).

Instrument: at each of the five sites, print rid, region type, `closed360`, `nSides`, radius,
triangle count, loop roles, and `builtAs`. Diagnostic build only, in the existing `wt-p84`
worktree, no arm.

### P87 — REFUTED in its specifics, and the failing region is a FALSE cylinder

```
SOT-23W    DIAG_FBF rid=0 type=Cylinder closed360=0 nSides=10 R=1.747997 nTris=18
                    maxVertexDev=0.286285 rms=0.254513 chordSag=0.085553
                    origin=CylGrow lawBand=0 spanU=3.2358 nTriMesh=658 loops=[Outer/8]
SuperSOT-3 DIAG_FBF rid=0 type=Cylinder closed360=0 nSides=10 R=1.587180 nTris=18
                    maxVertexDev=0.156546 rms=0.124880 chordSag=0.077682
                    origin=CylGrow lawBand=0 spanU=3.1917 nTriMesh=668 loops=[Outer/8]
```

P87 said closed360. It is **closed360 = 0** — a partial cylinder spanning 185°. Refuted.

What the line actually says is worse than a build bug. `maxVertexDev = 0.286285` on
`R = 1.747997` is **16.4 % of the radius**, against the region's own `chordSagitta` of
0.0856 — a factor of 3.3 beyond what the tessellation can explain. And SOT-23W's truth radii
are `{0.1, 0.28}`: **1.748 appears nowhere in the source CAD.** This region is not a cylinder.
It is 18 triangles of the package body that the grower accepted as one, and the G2 acceptance
gate let it through at 16 % deviation.

It is the same defect class as `NEG_SOT-1334-1_fine`, one stage earlier: there a real cylinder
got a wrong radius, here a non-cylinder got accepted outright. Both are fit-acceptance, not
face-building, and both models sit in `coarseFusionBand` — **658 and 668 triangles**, alongside
SOT-1334-1's 500.

`NEG_SuperSOT-3_fine` carries the *same* false region (rid 0, 10 sides, 18 tris, 10 % dev) and
still ships 12 cylinders, so the false region is not by itself fatal. What is fatal on SOT-23W
is the exit at 5351: the region fails to build, a J6 uncollapse pass runs, the rebuild fails
again, and `buildFaces` returns false for the whole component with no explode-recover.

**P88 (pending):** the G2 branch that admitted rid=0 is the coarse one, and its tolerance was
widened by the sec-lift: `g2Tol = max(g2Tol, lift * 1.15 + chordSagitta(...))` where
`lift = radius - rBeforeRefine`. For `maxVertexResidual = 0.2863` to pass, `lift` must be
≈ 0.23, i.e. `refineCylinderRadius` raised this region's radius by ~15 %. The same routine
that inflated SOT-1334-1's radius is here buying a false cylinder its acceptance, twice over —
once by moving the radius, once by widening the gate in proportion to how far it moved it.

**Refutation conditions:** `lift = 0` on rid=0 (then G2 passed on `epsCylAccept` or the
`tris <= 8` ring term and the sec-lift is exonerated here); or the region is admitted by a
non-coarse path. Note P85's planar-chord fix did NOT recover this model in the sweep, so if
P88 holds, the lift here must come from a term that fix does not touch — `rInscribed`, or
`rHint` — and the diagnostic must say which.

### P88 — CONFIRMED. The sec-lift buys the false cylinder its acceptance, twice

```
gate OFF  DIAG_G2 coarse=1 R=1.747997 rBefore=1.492783 lift=0.255214 nSides=10 nTris=18
                  eps=0.017480 sag=0.026556 g2Tol=0.320052 maxVertRes=0.286285
gate OFF  DIAG_LIFT Rin=1.49278273 nEff=8 nChord=2  rChordMed=1.74799672
                    rInscribed=1.61577639 rPick=1.74799672 rHint=1.49332445 spanRad=3.23849
```

`lift = 0.255214` — `refineCylinderRadius` moved this region's radius **+17 %**, from the
eberly value 1.492783 to 1.747997. G2's own tolerance is then
`g2Tol = lift*1.15 + sag = 0.2935 + 0.0266 = 0.3201`, and `maxVertRes = 0.2863` slips under
it. **Without the lift `g2Tol` would be `max(eps 0.01748, sag 0.02656) = 0.0266` and the
region would fail G2 by a factor of ten.** Exactly as predicted: the lift admits the false
cylinder once by moving the radius and once by widening the gate in proportion to the move.

Note `nChord = 2`. The inflated median that decided a 17 % lift was the median of **two**
samples.

**And this is why P85's planar-chord fix does not recover SOT-23W** — the diagnostic answers
the question P88 raised:

| | gate off | planar-chord on |
|---|---|---|
| `nChord` | 2 | 22 |
| `rChordMed` | 1.74800 | **1.49409** (≈ eberly, the chord term is fixed) |
| `rInscribed` | 1.61578 | 1.61578 |
| `rPick` | 1.74800 (chord) | **1.61578 (the inscribed branch takes over)** |
| `g2Tol` | 0.32005 | 0.16599 |
| `maxVertRes` | 0.28629 → passes | 0.15406 → **still passes** |

P85 fixes the chord estimator and the `rInscribed > rPick*1.003 && nEff <= 12` branch simply
becomes the binding one. The false cylinder is admitted either way; only its fabricated radius
changes. That is the same shape as the P86 finding on `L10_cross_slide`, where both arms
fabricate and only the radii differ.

**The structural defect, stated once:** G2 judges the fit at the **lifted** radius and widens
its own tolerance by the size of the lift. A region whose radius had to be moved 17 % is
precisely the one that deserves more scrutiny, not less. The lift's rationale is defensible in
isolation — if R is raised to a circumscribed radius, vertices on the inscribed ring sit ~lift
away by construction — but the consequence is that the acceptance test can no longer fail: any
region can be admitted by lifting it far enough.

**P89 (pending, and the last investigative round on this defect under R1):** compute
`maxVertexResidual` at `rBeforeRefine` as well as at the lifted radius, for rid=0 on SOT-23W
and SuperSOT-3 and for every coarse-band region on `L08_pillow_block` and `L10_cross_slide`
(where the lift is load-bearing for the counted gains). Prediction: on rid=0 the residual at
the **fitted** radius is also far outside `max(eps, sag)`, so judging G2 at `rBeforeRefine`
rejects the false cylinder; and on the L-models the genuine cylinders pass at `rBeforeRefine`
too, so the same rule does not cost them. Refuted if the L-model cylinders only pass at the
lifted radius — then the lift is load-bearing for real geometry and the fix must separate the
two cases on something other than residual.

### P89 — half confirmed, and it produced a better rule than the one predicted

`DIAG_G2` extended with the residual evaluated at `rBeforeRefine` (`resAtFit`) beside the one
at the lifted radius (`maxVertRes`). Rows below are coarse-band regions with a non-zero lift:

| model | R | rBefore | lift | maxVertRes (lifted) | resAtFit | tolAtFit | G2 verdict |
|---|---|---|---|---|---|---|---|
| SOT-23W | 0.514448 | 0.345923 | 0.168525 | **0.043052** | 0.211577 | 0.003459 | passes |
| SOT-23W **rid=0** | 1.747997 | 1.492783 | 0.255214 | 0.286285 | **0.031071** | 0.022679 | passes |
| SOT-23W | 2.012960 | 1.859732 | 0.153227 | 9.188519 | 9.341747 | 0.018597 | fails G2 |
| SuperSOT-3 **rid=0** | 1.587180 | 1.462362 | 0.124818 | 0.156546 | **0.031728** | 0.022217 | passes |

P89 predicted rid=0's residual would be far outside tolerance at the fitted radius too. It is
outside, but only by 1.37× (0.0311 vs 0.0227) — not "far". Half confirmed.

**What the table actually shows is the discriminator the fix needs.** The lift is not uniformly
good or bad:

- row 1: the lift takes the residual **down**, 0.2116 → 0.0431. Genuine coarse cylinder whose
  vertices sit inside the true circle; eberly under-reports and the lift corrects it. This is
  the case `refineCylinderRadius` was written for, and it must keep working.
- rid=0, both models: the lift takes the residual **up**, 0.0311 → 0.2863 (9×), and then
  `g2Tol = lift*1.15 + sag` widens the gate by more than that, so the region is admitted on
  the strength of how badly the lift fit it.

**P90 (pending) — keep the lift only when it improves the fit.** After
`refineCylinderRadius`, if `maxVertexResidual` at the lifted radius exceeds the residual at
`rBeforeRefine`, restore `rBeforeRefine` and recompute `d2`, leaving `lift = 0` so G2's
tolerance is not widened either. There is precedent for exactly this shape in the same
function: the archChain block already does `ev.radius = oldR` when its own result fails G2.

Predicted consequence, model by model, from the table:
- SOT-23W rid=0: lift reverted, then G2 with `tolAtFit = 0.0227` against `resAtFit = 0.0311`
  → **region rejected**, no false cylinder, no `FaceBuildFailed`, no `j6-uncollapse` exit,
  and the model builds.
- SuperSOT-3 rid=0: same rejection (0.0317 vs 0.0222). Its 12 cylinders come from other
  regions and must survive — if they do not, this fix costs the n6 win and is refuted.
- Row 1's lift is kept (residual improves), so genuine coarse cylinders are untouched.

Refutation conditions: SuperSOT-3 drops below 12; or the main set loses cylinders that are
truth-matched (as opposed to the fabricated ones P86 is counting).

### P90 — REFUTED, and the refutation is the most useful result in this arm

`STL2STEP_P90_LIFT_MUST_IMPROVE=1` on binary `wt-p84`:

| model | base | P90 | P90 + P85 |
|---|---|---|---|
| `NEG_SOT-23W_Handsoldering_fine` | 0 | **0** | 0 |
| `NEG_SOT-1334-1_fine` | 0 | 1 | 1 |
| `NEG_SuperSOT-3_fine` | 12 | **0** | 0 |
| `NEG_SC-59_fine` | 12 | **0** | 0 |
| `NEG_SOT-143_fine` | 16 | **0** | 0 |
| `NEG_TSOT-23_fine` | 12 | **0** | 0 |

SOT-23W is not recovered, and all four CAD-verified sentinels collapse to zero. Refuted on
both halves.

**But the failure mode is not the one that was there before, and that is the finding.**

```
P90 on, NEG_SC-59_fine      revertCause "budget dV=0.026630 budget=0.002045"   FBF count 0
P90 on, NEG_SuperSOT-3_fine revertCause "budget dV=0.006252 budget=0.002301"   FBF count 0
```

`FaceBuildFailed` is **gone** — rejecting the false cylinder does exactly what P89 predicted
at the build level, the `j6-uncollapse` exit no longer fires, and the component builds
cleanly. It is then discarded by the **volume budget**, 13× over on SC-59.

So the sec-lift is not a fit-quality correction at all. **It is load-bearing for volume**, and
judging it by vertex residual — which is what P89 and P90 did — misunderstands what it is for.
A lift that makes the vertices fit worse can still be the lift that makes the solid's volume
right, and on these five models it is.

**Consequence for P85, which matters for the promotion decision.** P85 corrected the chord
maths so the radius comes out geometrically exact (0.15000 against truth 0.15, where n5h
shipped 0.15563). On the negatives that is unambiguously right. On the main set it cost 7
cylinders. The same mechanism is the likely explanation: `refineCylinderRadius` has been
carrying a volume compensation inside a routine named and documented as a radius refinement,
and removing its arithmetic error also removes the compensation. **A geometrically correct
radius is not automatically the promotable one here**, and P85 must not be promoted on the
strength of "the radius is now exact" alone.

### Parking SOT-23W (R1)

Three rounds spent: P87 (localised the failing region, refuted on closed360), P88 (confirmed
the sec-lift admits it, and showed why P85 does not reach it), P89/P90 (fix attempted from the
residual criterion, refuted). **Parked**, with the state written down rather than a fourth
guess:

- The failing region is `rid=0`, an 18-triangle 185° arc that both SOT-23W and SuperSOT-3
  carry, fitted as a cylinder of R≈1.5–1.75 that appears nowhere in either model's truth.
- It is admitted because `g2Tol = lift*1.15 + sag` widens the gate in proportion to the lift.
- Rejecting it removes the build failure but fails the volume budget, so the next arm is the
  **volume budget and what the lift contributes to it**, not the acceptance gate. Whoever
  takes it should start by measuring `dVolPredicted` per region with and without the lift,
  on SC-59 (the cleanest: 13× over) — not by tuning G2.
- `NEG_SOT-1334-1_fine` remains fixed and independent of all of this: P90 and P85 both keep
  it at 1.

### L08_pillow_block — P85's one genuine regression, localised but NOT explained

`L08_pillow_block_normal` is the only model that loses **truth-matched** cylinders under P85
(5 → 0). Measured, in order:

1. It is not a revert. `usedRefit=true`, `revTrue=0`, cause string
   `counted-not-reverted usedRefit=true cyls=0 planCyl=10 planPl=13`. The component is
   ADOPTED with zero surviving cylinders — `smoothAdoptedNoCyl`, the honest counter.
2. It is not a face-build failure either: `DIAG_FBF` count is **0** under both configs.
3. It is the explode cascade. `DIAG_EXPLODE` shows **one** region exploded in the base config
   (`rid=3`, R=15.000014) against **essentially every region** under P85.
4. And the fits P85 produces are *better*, not worse — among the exploded regions:
   `rid=1 R=6.000000 maxVertexDev=0.000000`, `rid=12/13 R=2.500000 maxVertexDev=0.000000`.
   Those are exactly `truth.cyl_radii = [2.5, 6.0, 15.0]`, fitted to zero deviation, and they
   are exploded anyway. Whatever kills L08, it is not fit quality.

**Hypothesis tested and refuted.** The obvious candidate was sewing: `0efdb79` deleted the
`0.2929*R` floor from `meshTolCap`, and an inflated radius could have been compensating for
the missing slack. Restoring the floor alongside P85 changes nothing:

| model | base | P85 | P85+FLOOR | FLOOR only |
|---|---|---|---|---|
| `L08_pillow_block_normal` | 10 | 0 | **0** | 10 |
| `L10_cross_slide_normal` | 23 | 21 | 21 | 23 |
| `L09_crank_arm_normal` | 2 | 7 | 7 | 2 |
| `NEG_SOT-1334-1_fine` | 0 | 1 | 1 | **1** |
| `NEG_SuperSOT-3_fine` | 12 | 12 | 12 | 12 |
| `NEG_SC-59_fine` | 12 | 12 | 12 | 12 |

So L08's collapse is independent of the tolerance floor. **Left unexplained, deliberately** —
the next step is to find which region explodes FIRST under P85 and why, since the cascade is
clearly one failure propagating, and that is a fresh arm rather than a fourth guess on this one.

One incidental result worth recording: **`FLOOR only` also recovers `NEG_SOT-1334-1_fine`**
and disturbs nothing else in this set. It is a one-line revert of `0efdb79` rather than a
five-site chord-maths fix — but it recovers the count by restoring the 0.15563 radius, i.e.
by masking the defect, where P85 recovers it at the correct 0.15000. Cheaper and wrong.

**L08 — the lead, recorded rather than guessed further.** Explode order (not sorted):

```
base   1 explode  : rid=3  R=15.000014 nTris=60 nSides=69 dev=0.001071
P85   23 explodes : rid=15 R=14.907676 nTris=7  nSides=53 dev=0.003037   <- first
                    rid=16 R=14.907676 nTris=7  nSides=53 dev=0.003037
                    then rid=0 (plane, 91 tris), rid=1 (R=6.000000), rid=2, rid=3, ...
```

Under P85 the model's R≈15 feature is no longer **one** 60-triangle region at a single radius;
it is fragments — `rid=14` R=14.985691 (10 tris), `rid=15`/`rid=16` R=14.907676 (7 tris each) —
and the first two to explode are those 7-triangle arcs, after which the cascade takes
everything including the perfectly-fitted `rid=1` R=6.000000.

The mechanism that suggests, and which the next arm should test before anything is changed:
the sec-lift was **normalising** radii across co-radial fragments (all pulled to 15.000014),
and the coaxial merge — which keys on radius agreement — then joined them into one region.
Correcting the radii makes the fragments genuinely differ (14.9077 vs 14.9857, 0.5 % apart),
the merge no longer fires, and small arcs that cannot build on their own are left behind.
If that holds, the fix is in the merge tolerance, not in either the chord maths or G2.

## The +179 decomposed: +25 real, +154 fabricated

`radius_audit.py`, A = `v1.1.0-n5h` (8790b98b85c8, the live engine), B = `n6-oracle-test`
(877511d32a98), main 203 at `normal`, no env on either arm.

```
=== normal: MATCHED (upper bound on real recall) ===
  A (n5h)  matched 187   unmatched  15
  B (n6)   matched 212   unmatched 169
  matched delta +25      unmatched delta +154
  models worse-on-matched 0 | better-on-matched 6
      L04_soap_bar_normal          0 -> 12
      L08_pillow_block_normal      0 ->  5
      SpeedTestStructure_normal    0 ->  3
      L05_t_pipe_normal            0 ->  2
      L09_crank_arm_normal         0 ->  2
      L10_cross_slide_normal       0 ->  1
```

The raw main-set gain measured in `VERIFY-2026-09-10.md` was **+179**. Split against truth it
is **+25 truth-matched and +154 with radii that appear nowhere in the source CAD** — **86 % of
the headline is fabricated geometry.**

Per model, against the recoveries the verification report named:

| model | raw | matched |
|---|---|---|
| `L04_soap_bar` | 0 → 12 | **0 → 12** — fully real |
| `L10_cross_slide` | 0 → 23 | **0 → 1** |
| `SpeedTestStructure` | 0 → 130 | **0 → 3** |
| `L08_pillow_block` | 0 → 10 | 0 → 5 |
| `L09_crank_arm` | 0 → 2 | 0 → 2 |
| `L05_t_pipe` | 0 → 2 | 0 → 2 |

And the baseline moved in a way that matters on its own: n5h fabricates **15 of 202**
(7 %), n6 fabricates **169 of 381** (44 %). The n6 work did not only recover more cylinders —
it multiplied invented ones elevenfold.

**Zero models are worse on matched count.** So n6 is a real improvement in recall, +25, with
no truth-matched loss anywhere on the main set. That part of the verification stands, and it
is a smaller and more honest number than +179.

### What this does to the promotion decision

Nothing here is a reason to reject n6: on truth-matched counting it is +25 and 0 worse. But
three things change.

1. **The gate as written cannot see the problem it should care about.** `models worse = 0` on
   a metric that counts invented cylinders would pass a change that replaced every real
   cylinder with two fake ones. The gate needs the matched split, and `radius_audit.py` now
   produces it.
2. **The claimed recoveries need restating.** "SpeedTest 0 → 178" (DeepSeek) / "0 → 130"
   (verified here) is **0 → 3** real cylinders. `L10_cross_slide` 0 → 23 is **0 → 1**. Only
   `L04_soap_bar` survives its headline intact.
3. **Fabrication at 44 % is a defect in its own right**, and it is the same defect this arm
   has been chasing all along: `refineCylinderRadius` moving radii, and G2 widening its
   tolerance by the size of the move. `NEG_SOT-1334-1`, SOT-23W's `rid=0`, `L08`'s 17.07 /
   17.89 / 31.87 and `L10`'s 7.2 / 7.7 / 9.7 are all the same mechanism seen from different
   sides.

Recorded, not acted on. Promotion remains Tommaso's call, and it should now be made on
+25 / 0 worse / 44 % fabricated rather than on +189.

## The negatives, and the resolution of the promotion blocker

```
=== fine: MATCHED ===  A = n5h, B = n6
  A (n5h)  matched 253   unmatched 14
  B (n6)   matched 265   unmatched 12
  matched delta +12      unmatched delta -2
  models worse-on-matched 0 | better-on-matched 1
      NEG_SuperSOT-3_fine   0 -> 12
```

**Zero models worse on matched count — including the two rows that blocked promotion.** Their
per-model records say why:

| model | truth radii | n5h built | matched? | n6 built |
|---|---|---|---|---|
| `NEG_SOT-1334-1_fine` | [0.15] | 1 face, **R = 0.1556** | **no** (3.7 % off) | 0 |
| `NEG_SOT-23W_Handsoldering_fine` | [0.1, 0.28] | 1 face, **R = 0.5144** | **no** | 0 |
| `NEG_SuperSOT-3_fine` | [0.1, 0.25] | 0 | — | **12, all matched** |

`0.5144` is recognisable: it is the lifted region from the P88 table
(`R=0.514448 rBefore=0.345923 lift=0.168525`). Both "lost" cylinders are inventions of the
sec-lift, and n6 loses them because it stopped inventing them.

**So the `models worse = 0` gate never actually failed.** It failed on a metric that cannot
tell a cylinder from a coincidence. Measured against truth:

| set | n5h matched | n6 matched | delta | worse | fabrication n5h → n6 |
|---|---|---|---|---|---|
| main 203 (normal) | 187 | 212 | **+25** | **0** | 15 → 169 |
| negatives 78 (fine) | 253 | 265 | **+12** | **0** | 14 → 12 |
| **total** | **440** | **477** | **+37** | **0** | 29 → 181 |

### Verdict, revised

`n6-oracle-test` is **+37 truth-matched cylinders with zero truth-matched regressions on
either set**. The two rows in `VERIFY-2026-09-10.md` that forced the three-way choice —
investigate, re-scope, or waive — are resolved by measurement: there is nothing to investigate,
nothing to waive, and no manifest question, because neither row was a real cylinder. Option 1
of that report is withdrawn, and `NEG_SOT-1334-1`'s "fix" (P85) turns out to be recovering a
cylinder n5h never correctly had.

The open issue is the other direction, and it is new: **n6 raises fabricated cylinders on the
main set from 15 to 169.** That costs nothing on this corpus's gate but it is 44 % of what the
output claims to be analytic geometry, and downstream consumers cannot tell the difference
either. It is the same `refineCylinderRadius` / G2 mechanism documented throughout this arm.

Still Tommaso's call. What changed is that it is now a clean decision — promote +37/0, with
fabrication logged as the next arm — rather than a trade against two regressions that do not
exist.

---

## CADScore — one number, used from here on

`scripts/cadscore.py`. Per model: `matched` = built cylinder faces whose radius is within TOL
of a truth radius, **capped at that model's truth face count** so N copies of one real radius
cannot buy recall. Micro-averaged over the set:

```
recall    = sum matched / sum truth_faces      did we find the cylinders
precision = sum matched / sum built_faces      did we invent any
CADScore  = 100 * 2PR/(P+R)
```

A model with no truth cylinders and none built counts 1/1 (a free 100); building anything
there scores 0 for its contribution. **Always an upper bound** — a right radius in the wrong
place still counts as matched.

Baseline, `v1.1.0-n5h` vs `n6-oracle-test`:

| set | arm | CADScore (≤0.5 %) | recall | precision | CADScore (≤5 %) |
|---|---|---|---|---|---|
| main 203, 796 truth faces | n5h | **50.18** | 34.30 | 93.49 | 50.18 |
| main 203 | n6 | **46.88** | 37.31 | 63.06 | **66.93** |
| negatives 78, 1156 truth faces | n5h | 36.36 | 22.49 | 94.89 | 36.92 |
| negatives 78 | n6 | **37.78** | 23.53 | 95.77 | 38.19 |

Two readings, both new:

1. **On the main set n6 is a net REGRESSION at exact tolerance**, 50.18 → 46.88: +3 points of
   recall bought with −30 of precision. The `+189` read as a large win only because the metric
   had no precision term. On the negatives n6 is a genuine small gain, 36.36 → 37.78.
2. **The whole gap between "regression" and "large win" is the SpeedTest 1.7 % radius bias.**
   Counting those 127 faces as found takes the main set to **66.93**. One defect is worth
   20 CADScore points — more than everything else in this arm combined.

Target for the fabrication work, in order:
- **SpeedTest +1.7 % radius bias**, 127 faces, worth ~+20 points on main.
- **~48 genuinely invented faces** (39 main + 9 neg), worth the remaining precision.

---

## CORRECTION to the "44 % fabricated" figure, and the real fabrication target

The MATCHED/UNMATCHED split used a single `0.5 %` threshold, which lumps two very different
failures together. Re-binned by relative error to the **nearest** truth radius:

| bucket | n5h main | n6 main | n5h neg | n6 neg |
|---|---|---|---|---|
| ≤ 0.5 % — matched | 187 | **212** | 253 | **265** |
| 0.5–5 % — right feature, wrong radius | 0 | **127** | 4 | 3 |
| 5–20 % | 0 | 3 | 0 | 0 |
| > 20 %, or the model has no truth cylinder at all — invented | 15 | **39** | 10 | 9 |

**"44 % fabricated" was wrong and is withdrawn.** 127 of the 169 are a single model,
`SpeedTestStructure_normal`, all at exactly `R = 0.2034` against a truth radius of
`0.199996` — **1.7 % oversize**. Those are its real Ø0.4 holes, built slightly too large, not
invented geometry. The audit's threshold, not the engine, put them in the wrong bucket.

Fabrication is also far more concentrated than "44 %" implies: **10 of 203 models fabricate
anything at all**, and outside SpeedTest the whole main set contributes 42 faces.

| model | unmatched | tris | unmatched radii |
|---|---|---|---|
| `SpeedTestStructure` | 127 | 6216 | 0.2034 (truth 0.199996) |
| `L10_cross_slide` | 22 | 536 | 1.0, 7.21, 7.25, 7.56, 7.70 (truth 2.0 only) |
| `L01_trunc_cone` | 8 | 594 | 15.07, 15.10, 15.12, 17.10 (**truth has no cylinder**) |
| `L08_pillow_block` | 5 | 566 | 17.07, 17.89, 31.87 |
| six others | 1–2 each | 20–816 | — |

### Two separate defects, and the priority order changes

1. **A systematic +1.7 % radius bias on SpeedTest, 127 faces.** This is the single largest
   effect in the corpus and it is pure correctness: fixing it converts 127 near-misses into
   matched and takes n6's real recall from **+37 to +164**. SpeedTest has 6216 triangles, so
   `coarseFusionBand` (500–1200) does **not** apply and `refineCylinderRadius` never runs —
   this is a different inflation path from everything documented above, and must be measured,
   not assumed to be the same bug.
2. **~48 genuinely invented faces** (39 main + 9 neg), concentrated in the coarse band, from
   the `refineCylinderRadius` / G2 mechanism already documented. `L01_trunc_cone` is the
   cleanest reproducer in the corpus: **truth has zero cylinders** and n6 builds 8.

Taking (1) first: bigger, cleaner, and its reproducer is unambiguous.

---

# GOAL (set by Tommaso, 2026-09-11): rebuild 90 % of the cylinders in mechanical parts

**Measured as:** CADScore recall on the **main 203-model set** (alphaevolve designed +
reconstructed, SpeedTestStructure, gancio, clamp_half_a) — the mechanical corpus. The 78
KiCad `Package_TO_SOT_SMD` negatives are a precision guard, not part of this target.

A cylinder counts as rebuilt when an analytic cylindrical face reaches the written STEP with
a radius within the model's **mesh deflection** of a truth radius. The goal is SHAPE, not
metrology: below the deflection the mesh carries no information distinguishing two radii.

| | faces |
|---|---|
| truth cylinder faces, main 203 | 796 |
| rebuilt today (`n6-oracle-test`) | **424 — 53.3 %** |
| target 90 % | 716 |
| **gap** | **+292** |

## The gap is two buckets, and they are enough

| bucket | missing | note |
|---|---|---|
| **31 models that rebuild ZERO cylinders** | **202** | whole-component discard |
| **SpeedTestStructure** | 155 | builds 130 of 285 |
| 5 other models, partial | 15 | |

Recovering both buckets gives ~98 %. **Nothing else needs to move to reach 90 %.**

## The 31 zero-cylinder models are not a detection problem

Their radii are **17–55× the mesh deflection** — well-tessellated, unambiguous cylinders. The
engine finds and builds them: `L09_clamp` segments 17 regions with `rejects[None=17]` — not
one region rejected — and is still discarded whole. `gancio_parametric` segments 293.

They die at one of two deliberate all-or-nothing exits in `buildFaces`:

- **line 5354, `exit=j6-uncollapse`** — dominant in the census. Once a J6 heal pass has run
  (`j6UncollapsePass > 0`), any remaining failure returns false for the entire component with
  no explode-recovery, by design: *"after the heal, do not explode recover — that dirties
  vertex TShapes and worsens R2 volΔ"*.
- **line 5511** — the shell is closed but `BRepCheck`-invalid and the cascade ladder is
  exhausted (`plan.hostR2 || cascadeSt.u2Done || !shValid` — note `!shValid` is always true
  inside that branch, so the disjunction always fires). RULE 1.4: never ship an invalid shell.

Both are defensible in isolation and together they set the recall ceiling. **This is the
n7-partial-adoption problem**, and it is where the 90 % target has to be won.

Smallest reproducer in the corpus: **`L07_spool_normal`** — `rejects[None=7]`, seven regions,
none rejected, component discarded.

## On using a vision model for this (asked 2026-09-11)

Not the right tool, on the evidence above. Detection is not failing — the engine already
segments, fits and builds these cylinders; it then throws them away because the sewn shell is
not valid. A VLM cannot make a shell sew. The only place a learned component has a plausible
job here is **ranking which region the cascade should explode when it cannot identify a
culprit**, which is geometric-feature ranking (the parked `n6-brep-delta` GNN), not vision —
and it should not be reached for while the deterministic path is discarding work it has
already completed successfully.

## B-Rep validity: 99 % there, and n6's three flagship wins are the three it breaks

`radius_audit.py` now also reports B-Rep health of the written STEP (solids, free edges,
`BRepCheck_Analyzer`).

| set | arm | closed valid solids | has a solid | free-edge-free |
|---|---|---|---|---|
| main 203 | n5h | **202 / 203** | 203 | 203 |
| main 203 | n6 | **200 / 203** | 203 | 203 |
| neg 78 | n5h | 77 / 78 | 78 | 78 |
| neg 78 | n6 | 76 / 78 | 78 | 78 |

Every model ships a closed solid with **zero free edges** — the facet fallback guarantees
that. So the validity half of "recreate a B-Rep shape" is essentially solved, and the entire
remaining deficit is analytic-face recall. Validity is therefore a **guard** on the CADScore
work, not a target: it must not drop.

**But n6 makes exactly three models invalid, and they are its three showcase results:**

| model | cylinders n6 builds | `BRepCheck` |
|---|---|---|
| `SpeedTestStructure_normal` | 130 | invalid |
| `L08_pillow_block_normal` | 10 | invalid |
| `NEG_SuperSOT-3_fine` | 12 | invalid |

All three are closed, single-solid, free-edge-free. The defect is specific and identical:

```
NEG_SuperSOT-3   FACE UnorientableShape 1   WIRE SelfIntersectingWire 1
                 invalid faces: cylindrical 0, other 1
L08_pillow_block FACE UnorientableShape 2   WIRE SelfIntersectingWire 2
                 FACE BadOrientationOfSubshape 1
                 invalid faces: cylindrical 0, other 3
```

**Not one cylindrical face is invalid.** The cylinders n6 recovers are sound; what breaks is a
neighbouring **planar** face whose boundary wire self-intersects. That is the pinch-vertex
defect already characterised in `n5e` (a region whose outer walk visits the same vertex twice),
with its two candidate repairs already written down there: split the region along an interior
edge path, or admit two coincident TVertex.

For contrast, `L10_nut_housing_normal` is invalid on **both** arms and is a different defect —
`UnorientableShape` on 2 **cylindrical** faces, pre-existing, not n6's doing.

**Consequence for promotion:** n6 buys +25 matched cylinders on main and pays 2 valid solids.
That is a real cost and it was invisible until now — but it is a bounded, named, already-
diagnosed defect (n5e pinch vertices on planar faces), not a property of the recall work.

## Census of the 31 zero-cylinder models, and a correction to the arithmetic

| exit | models | truth faces lost |
|---|---|---|
| `j6-uncollapse` @5354 | 13 | **79** |
| no cause string emitted | 11 | 61 |
| `none` @5511 (closed shell, `BRepCheck`-invalid, ladder exhausted) | 4 | 45 |
| `built-empty-main` @5085 | 2 | 11 |
| `heal-discard` @5419 | 1 | 6 |
| | **31** | **202** |

**Correction:** recovering all 31 gives 424 + 202 = 626 / 796 = **78.6 %**, not 90. SpeedTest's
155 faces are required too — 424 + 202 + 155 = 781 = **98 %**. SpeedTest is the single largest
item in the gap, larger than any exit bucket, and it is a *different* failure: the component
survives (130 faces are written), so faces are being lost inside an adopted component rather
than by whole-component discard.

Cleanest partial-adoption targets, all `@5354` with **no region rejected at all**:
`L07_spool` (7 regions), `L08_motor_bracket` (14), `L09_clamp` (17).

Largest single member of `@5354`: `gancio_parametric`, 25 faces, 293 regions.

## The three clean reproducers: every cylinder found and accepted, none shipped

New instrument `STL2STEP_DIAG_REJECTS` (the reject histogram was previously emitted only
inside a revert cause, so an ADOPTED component that drops its cylinders showed nothing):

| model | regions | rejected | cylinder regions | cylinders in STEP |
|---|---|---|---|---|
| `L07_spool_normal` | 7 | **0** | 2 | **0** |
| `L09_clamp_normal` | 17 | **0** | 8 | **0** |
| `L08_motor_bracket_normal` | 14 | **0** | 6 | **0** |
| `L10_linear_bearing_normal` | 25 | 1 | 8 | **0** |

Nothing is rejected. Every cylinder is segmented, fitted, accepted and built — and then the
whole component is thrown away. This is a 100 % avoidable loss and needs no better detection.

And SpeedTest is the OPPOSITE failure, confirmed from its counters:

```
smoothCylinders 144   smoothBuiltCylinders 130   smoothRejected 263
smoothRevertedTrue 0  smoothAdoptedNoCyl 1       truth cyl_faces 285
```

The component is adopted; 130 faces ship. Of its 155 missing faces, ~141 are **never
proposed** (144 cylinder regions against 285 truth faces) and ~14 are proposed and lost. A
fit-acceptance problem at the opposite end of the pipeline from the 31.

## P92 — let the cascade recover after a J6 heal (pending, 2026-09-11)

`refit_build.cpp` ~5346: once `j6UncollapsePass > 0`, any remaining failure does
`out.clear(); return false` for the whole component. The comment states the reason —
*"after the heal, do not explode recover — that dirties vertex TShapes and worsens R2 volΔ"*
(revert-class Body9/12/18/20). When `j6UncollapsePass == 0` the same situation instead falls
through to the R1 / explode-recover path.

**P92:** removing that early return (env-gated) so the post-heal case falls through to the
same recovery path recovers cylinders on the 13 `@5354` models — 79 truth faces — without
touching the four CAD-verified sentinels.

**Refutation conditions, stated in advance:**
- the models come back but are then discarded by the **volume budget** (`revertCause
  "budget dV=..."`), reproducing exactly the P90 lesson — the guard is load-bearing for volume
  and the fix must address volume, not the exit;
- any of `NEG_SC-59` / `NEG_SOT-143` / `NEG_TSOT-23` / `NEG_SuperSOT-3` drops below
  12 / 16 / 12 / 12;
- CADScore on the main set falls, or B-Rep valid-solid count drops below n6's 200/203.

Note the comment names a real measured harm, so a refutation here is the expected outcome,
not a surprise. The value of running it is that it separates "the exit is the problem" from
"the volume budget is the problem" with one measurement.

---

# THE DENOMINATOR WAS WRONG: 278 of the main set's truth faces are not in the mesh

`truth.json` stored `cyl_radii` **deduplicated**. `SpeedTestStructure` listed
`[0.199996, 10.0, 20.0]` and looked balanced. Per-face measurement from the source B-Rep
(`scripts/truth_face_radii.py`, now writing `cyl_radii_hist`):

```
R=0.2000   278 faces
R=10.0000    5 faces
R=20.0000    2 faces
```

Its `normal` deflection is **0.3545 mm — larger than the 0.2 mm radius**, so the linear chord
criterion constrains nothing and only BRepMesh's angular limit applies. Even at `fine`
(0.1773) it is 2.2 facets around a full circle. **278 of 285 faces are not representable in
the mesh**, and SpeedTest alone was **36 % of the main set's 796-face denominator**.

Scoring geometry the mesh cannot carry is not a measurement of the engine. `cadscore.py` now
excludes truth faces with `radius < deflection`, and also drops built faces matching an
excluded radius from `built` — penalising the engine for reconstructing something we just
declared unrecoverable would be incoherent.

## Corrected baseline, resolvable geometry only

| set | arm | CADScore | recall | precision |
|---|---|---|---|---|
| main 203 (**518** resolvable faces) | n5h | 67.41 | 52.70 % | 93.49 % |
| main 203 | n6 | **68.91** | **57.34 %** | 86.34 % |
| negatives 78 (1156, none excluded) | n5h | 36.36 | 22.49 % | 94.89 % |
| negatives 78 | n6 | 37.78 | 23.53 % | 95.77 % |

**Two of my own figures are withdrawn:** n6 is **+1.5** CADScore on main, not +16.75 — the
larger number came from a denominator stuffed with unrecoverable faces. And SpeedTest's 155
"missing" faces are **not a target**; they are a corpus artefact of a 354 mm part meshed at
diag/1000.

## The goal is now one problem

90 % recall on resolvable main geometry = **466 of 518**. Today **297**. Gap **+169**.
The 31 zero-cylinder models hold **202** resolvable faces (radii 17–55× deflection, every one
found, fitted and accepted before the component was discarded) → **96.3 %**.

**Stop discarding components that have already been built successfully, and the goal is met.**

## P92 — CONFIRMED in direction, REFUTED in magnitude

Full main-set sweep, binary `p92-*` vs itself with the switch off:

```
matched 212 -> 220 (+8)    unmatched +0    models worse 0 | better 3
B-Rep valid solids 200/203 -> 200/203
CADScore 68.91 -> 70.11    recall 57.34% -> 58.88%   precision 86.34% -> 86.65%
    L10_linear_bearing 0 -> 5
    L09_clamp          0 -> 2
    L07_collar         0 -> 1
sentinels 12/16/12/12 unchanged; soap_bar 12, pillow_block 10, cross_slide 23, crank_arm 2
```

The exit at `refit_build.cpp:5346` is a real, safe-to-remove cause: letting the post-heal case
use the same explode-recover path as the pre-heal case costs nothing measurable. **The comment
that blocked it — "dirties vertex TShapes and worsens R2 volΔ" — does not reproduce**: zero
regressions, zero new fabrication, zero validity loss across 203 models.

But P92 predicted ~79 faces across the 13 `@5354` models and delivered **+8 across 3**. The
other 10 reach the recovery path and still ship nothing, so there is a **second blocker behind
the same exit**. That is the next arm, and `L07_spool` (7 regions, 0 rejects, 2 cylinder
regions, still 0 after P92) is its minimal reproducer.
