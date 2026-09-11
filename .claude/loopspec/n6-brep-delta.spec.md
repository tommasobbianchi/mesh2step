# E2' / n6-brep-delta — a GNN proposes, the deterministic fit disposes

Opened 2026-09-08 by Tommaso. Python side only; **no fork change**. Predictions below are on disk
BEFORE any instrumentation, per method. A refuted prediction rewrites its arm and is never edited.

## The shape of the thing

The GNN never writes geometry. It reads the ENGINE OUTPUT's face-adjacency graph and emits
*proposals*: facet islands it believes are a cylinder the engine left faceted, grouped into rings.
`rebuild.py` fits each proposed ring with the **existing residual gate** and either rebuilds it or
leaves it faceted with a **state-2 warning line**. A hallucinated proposal therefore cannot ship
geometry — it can only produce a warning. That property is the whole reason this is allowed to be
a learned component at all, and it must not be weakened for recall.

## Premises checked before writing this (measured, not assumed)

| premise as stated | measured | verdict |
|---|---|---|
| "the 1,225 designed octagons are the negatives" | **1,227**, from the full KiCad Packages3D library — 6,822 parts with true B-Rep (`n4-cylinder-intent-gates.spec.md:174`) | holds, number corrected |
| corpus supplies the labels | `truth.json` = **57 models, 41 with cylinders, 474 truth cylinder faces**, and it is **per-MODEL counts only** | **face-level truth does not exist and must be built** |
| KiCad gives training volume | 6,822 parts with true B-Rep | holds — this, not cadbench, is the training set |
| designed-polygon logic exists | `intent.py` already reasons about designed polygons (`:173`, `:338`, `:405`) and `canonize.py:MIN_SEGMENTS` | holds, reusable |

`truth.json` carries `faces / cyl_faces / planar_faces / other_faces / circle_edges / cyl_radii /
circ_radii` **per model**. There is no per-face type anywhere. The A/B-matched face labels this
plan needs are derivable from each model's source B-Rep (`src` field, and the KiCad STEPs) but
they are WORK, not data we have. That is P0.

## P0 — the reachability gate. No model is trained until this passes.

v1 excludes reverted (facet-soup) components. Recall is 87/474 = 18.4 %, so **387 truth cylinders
are missing**. If most of them sit in components the engine REVERTED, they are out of v1 scope by
construction and "+≥ 100 cylinders" is unreachable before a single epoch is run.

Known risk from the existing measurements: `SpeedTestStructure_normal` alone holds **102 truth
cylinders below the seed band**, and its component is exactly the one the cascade discards
(165 built cylinder faces at pass 0 → 0 by pass 5). Those 102 are almost certainly out of scope.

**Measure, per truth model, for every missing cylinder: is its region in an ADOPTED component or
a REVERTED one?** One parallel sweep of the 57 truth models through the live engine plus the
existing revert diagnostics. No ML, no fork change.

- **P0 prediction (pending):** ≥ 150 of the 387 missing cylinders lie in ADOPTED components, so
  the +100 target is reachable with headroom.
- **Falsified if < 100 are in adopted components** — in which case the +≥100 prediction below is
  refuted before training, and the chapter is re-scoped to reverted components or parked.

## Arms and predictions (all pending)

- **P75 — labels are recoverable.** Output faces A/B-match to source-B-Rep faces well enough to
  label plane / cylinder / designed-polygon / other, on ≥ 95 % of output faces across 5 models.
  Falsified if matching is ambiguous for > 5 % — then the label set is the defect, not the model.
- **P76 — the signal exists in the stated features.** Node features (face type, area, normal,
  dihedral to neighbours, loop count, neighbour-is-analytic) separate "missed cylinder ring" from
  "designed polygon" at ≥ 90 % precision / ≥ 80 % recall on below-5° rings, held out **by model**.
  Falsified if a small inspectable model cannot reach it — a bigger model is NOT the next step;
  the feature set is.
- **P77 — the contract holds under adoption.** On adopted components: corpus recall **+ ≥ 100**
  cylinders, **zero designed polygons rebuilt**, and `MISSED_silent_wrong_rebuild = 0` on the
  labelled negatives. Falsified by a single rebuilt designed polygon — that is a state-2
  violation, not a precision statistic.
- **P78 — rejection is visible.** Every rejected proposal emits exactly one state-2 warning line;
  no proposal is silently dropped. Reachability control: a run with a deliberately absurd proposal
  must produce a warning, or the zero is not a measurement.

## Split discipline

**By MODEL, never by face.** Faces within one model are not independent — a ring's neighbours are
the same ring. A face-level split would leak the answer across the split and report a precision
that does not exist. Explicitly recorded because it is the single easiest way to fake this result.

## Gates (promotion, as for n5d — R2)

- `MISSED_silent_wrong_rebuild = 0` on the labelled negatives for that sha.
- 2b v2, no row worse than the production baseline.
- **models worse = 0** on the FULL 333-model corpus, with `NEG_SC-59_fine` (12),
  `NEG_SOT-143_fine` (16), `NEG_TSOT-23_fine` (12) as named sentinels — CAD-verified truth.
- recall strictly up; geometric equivalence for every model whose bytes differ.
- Exploration first: 5 models, parity-gated, minutes. No full sweep for a diagnostic.

## Costs to decide before adoption, not after

Adding torch + PyTorch Geometric to the REQUEST path invalidates the capacity envelope measured
2026-09-08 (~0.78 GB per concurrent conversion, 6 slots, 4.68 GB peak on six near-limit models).
Two ways out, both cheaper than re-doing the capacity work: run inference out of process, or run
it only on models the engine already flags as cylinder-poor. Decide at adoption.

## Out of scope for v1

Reverted (facet-soup) components — including `SpeedTestStructure_normal`, whose 102 below-band
truth cylinders are therefore NOT part of the +100.

---

## P0 — REFUTED (measured 2026-09-08 07:31, live engine v1.1.0-n5h sha 8790b98b85c8, 41/41 models, 0 errors)

Predicted: >= 150 of the 387 missing cylinders in ADOPTED components. Measured: **72**.

| bucket | models | want | got | missing |
|---|---|---|---|---|
| IN_SCOPE (all components adopted) | 30 | 157 | 85 | **72** |
| MIXED (adopted + reverted) | 3 | 9 | 2 | 7 |
| OUT_OF_SCOPE (all reverted) | 8 | 308 | 0 | **308** |
| TOTAL | 41 | 474 | 87 | 387 |

**Upper bound on reachable under v1 scope = 79 cylinders (72 + 7).**

### Consequence: P77's "+>= 100 cylinders" is not unlikely, it is IMPOSSIBLE

Only 79 missing cylinders exist in adopted-or-mixed components at all. P77 is refuted by
arithmetic before any model is trained. It must be re-scoped or the scope boundary must move.

### The opportunity is one model

| missing | bucket | model | want / got | components |
|---|---|---|---|---|
| 246 | OUT_OF_SCOPE | SpeedTestStructure_normal | 246 / 0 | 1 adopted=0 reverted=1 |
| **64** | **IN_SCOPE** | **gripper_gear_normal** | 75 / 11 | 1 adopted=1 reverted=0 |
| 25 | OUT_OF_SCOPE | gancio_parametric_normal | 25 / 0 | reverted |
| 12 | OUT_OF_SCOPE | L04_soap_bar_normal | 12 / 0 | reverted |
| 11 | OUT_OF_SCOPE | clamp_half_a_normal | 11 / 0 | reverted |

**64 of the 72 in-scope missing cylinders (89 %) are in `gripper_gear_normal` alone.** A
held-out-by-model evaluation therefore has effectively ONE model that matters, and P76's
">= 90 % precision / >= 80 % recall" cannot be measured meaningfully against it.

### What this says about where the cylinders actually are

**308 of 387 missing cylinders — 79.6 % — are lost to COMPONENT REVERTS**, not to failed
recognition. The engine adopted nothing in those eight models. E1/P71 (surgical culprit explosion
before the U2 blanket) addresses that population; this chapter, as scoped, cannot touch it.
The engine-side fix outweighs the learned proposal roughly **4 : 1** in reachable cylinders.

Worse for the ML case: `gripper_gear`'s missing cylinders are largely the **below-5-degree-band**
population that **E2 / n5g constant 1** already targets with a deterministic self-calibrated seed
floor (recorded: 170 truth cylinders below band, 55 on gripper_gear). So the GNN's one real
opportunity overlaps a cheaper deterministic lever that is already specified.

### Reachability controls (a zero is a measurement only once its counter is proven to move)

- `smoothRevertedComponents > 0` on **11** models — the zeros elsewhere are real.
- `smoothAdoptedNoCyl > 0` on **2** models — real.
- `smoothSkippedComponents > 0` on **0** models. **Its increment site is NOT proven reachable, so
  every `skipped = 0` above is an unverified zero, not a measurement.** It does not change the
  bucketing (skipped and reverted are both "lost"), but it must not be cited as evidence.

### Recommendation (decision is Tommaso's)

1. **Do E1/P71 first.** It targets 308 cylinders; this chapter targets at most 79.
2. **Re-measure this P0 after the revert fix.** The in-scope pool could grow by up to 308, at
   which point a learned proposer has a population worth training on.
3. **If n6-brep-delta proceeds now, re-scope P77** from "+>= 100" to a target inside 79, and
   accept that P76 is being evaluated on essentially one model — or first run n5g constant 1,
   which may take gripper_gear's 64 deterministically and leave the GNN with almost nothing.

---

## Correction 2026-09-08 (Tommaso): P0's conclusion is right on the LIVE engine, and understates the pool

P0 measured the live engine v1.1.0-n5h. On the **P69 binary** (`n7-p69-explode-culprits`,
1a8d860fbc1e) `SpeedTestStructure_normal` **ADOPTS** — closed, valid, 3,724 faces, 0 cylinders,
facet rings intact. That moves its **246 truth cylinders from OUT_OF_SCOPE to IN_SCOPE**, so the
79-cylinder ceiling is a property of the live binary, not of the problem.

Expected in-scope pool on the P69 binary: **>= 79 + 246 = 325**.

### Order (binding)

1. **P69 + the P58 plane|plane rule are ENABLING changes.** Neither recovers a cylinder by itself,
   so neither can be promoted alone under `recall strictly up`. They land TOGETHER with whatever
   does recover cylinders, in one gate.
2. **P71** attempts the deterministic recovery inside the cascade (surgical culprit explosion
   before the U2 blanket).
3. **Re-measure P0 on the P69 binary.** That re-measure, not the live-engine number above, is this
   chapter's scope.
4. **n6-brep-delta trains on what P71 does NOT recover.** Its target is set by the step-3
   re-measure; the "+>= 100" figure is void until then.

### Prediction ids renumbered (my error, corrected)

I wrote this spec's predictions as P72-P75 without checking the registry. **P72, P73 and P74 were
already defined in `n5g-self-calibrated-seed-floor.spec.md`.** Tommaso asked for P74 -> P75, but
that would have collided with this spec's own P75, and it would have left the P72/P73 collisions
standing. Renumbered as a contiguous block into free space instead:

| was | now | prediction |
|---|---|---|
| P72 | **P75** | labels are recoverable |
| P73 | **P76** | the signal exists in the stated features |
| P74 | **P77** | the contract holds under adoption (the "+>= 100" target — void, see above) |
| P75 | **P78** | rejection is visible |

Verified afterwards by parsing every spec for DEFINITIONS (heading or bold-bullet) rather than
mentions — a bare mention is a legitimate cross-reference, and treating those as collisions would
have invented 15 conflicts that do not exist. One genuine pre-existing duplicate remains and is
NOT mine to renumber silently: **P53 is defined in both `n5e-wire-chaining.spec.md` and
`n5g-self-calibrated-seed-floor.spec.md`.** Flagged for Tommaso.

---

## P0 RE-MEASURE on the P69 binary — CONFIRMED (e1-2a5aa8a69703, STL2STEP_EXPLODE_CULPRITS=1, 41/41 models)

Expected in-scope pool >= 79 + 246 = 325. **Measured: 326.**

| bucket | models | want | got | missing |
|---|---|---|---|---|
| IN_SCOPE | 34 | 412 | 86 | **326** |
| MIXED | 1 | 1 | 1 | 0 |
| OUT_OF_SCOPE | 6 | 61 | 0 | 61 |

`SpeedTestStructure_normal`: **IN_SCOPE**, want 246, `revertedTrue=0`, `adoptedNoCyl=1`.
Still out of scope, all with `revertedTrue=1`: gancio_parametric 25, L04_soap_bar 12,
clamp_half_a 11, L09_gear_blank 8, L10_cross_slide 4, L04_cyl_bottom_chamf 1.

### Instrument error caught (#13): `smoothRevertedComponents` counts adopted components as reverted

**This is my error and it produced a wrong answer that I reported before catching it.** My P0
harness bucketed on `smoothBuiltComponents` / `smoothRevertedComponents`. On
`SpeedTestStructure_normal` under P69 those read 0 and 1, so I classified it OUT_OF_SCOPE and
stated that the "+246" expectation was refuted. It was not.

`--diag-revert-cause` gives the component's own account:

    revertCauses: ["counted-not-reverted usedRefit=true cyls=0 planCyl=183 planPl=542"]
    smoothRevertedTrue = 0     smoothAdoptedNoCyl = 1     usedRefit = true

**The component was ADOPTED.** `smoothRevertedComponents` counts "adopted but built zero
cylinders" as a revert -- its own cause string says `counted-not-reverted`. The honest counters
are `smoothRevertedTrue` and `smoothAdoptedNoCyl`, both of which the harness already recorded.
Re-bucketing needed no re-run, only the right field.

Corrected, both datasets (adopted := built + adoptedNoCyl; lost := revertedTrue + skipped):

| binary | old bucketing | corrected |
|---|---|---|
| live v1.1.0-n5h | IN 72 / MIXED 7 / OUT 308 | **IN 79 / MIXED 0 / OUT 308** |
| P69 + P58 | IN 8 / MIXED 7 / OUT 308 | **IN 326 / MIXED 0 / OUT 61** |

The live-engine total is unchanged at 79 by coincidence (72+7 = 79), which is why the original
P0 verdict still stands; the P69 figure moves by 318.

**Standing lesson, same family as the n5h watertight flag:** a counter named for a state is not a
measurement of that state. `smoothRevertedComponents` is a misnomer, and it is the second lying
flag found in this engine. Before bucketing on any counter, read the cause string it ships with.

### Consequence for this chapter

P77's "+>= 100" is no longer impossible: the pool is 326 with SpeedTestStructure's 246 inside it,
and 89% of the opportunity is no longer one model. The GNN's scope is now what P71 does not
recover, measured against this 326 -- exactly as the four-step order requires.
