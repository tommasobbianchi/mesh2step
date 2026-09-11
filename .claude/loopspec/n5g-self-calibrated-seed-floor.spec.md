# n5g — a self-calibrated Phase-B seed floor

**Status: RECORDED, not started. Runs AFTER n5e** — ranked by in-band cylinders unblockable
(n5e ~144, n5g ~68 realisable now), not by model.

## 0. AN ABANDONED ROAD, REOPENED — and why the old reason no longer applies

`--cyl-seed-lo` (a GLOBAL lower seed threshold) lost the real-CAD A/B: **12.9 % against a
21.3 % baseline**. That result was recorded as the reason not to touch the seed floor again.

**It no longer applies, and the measurement says why.** That A/B ran while the
plate-orientation defect discarded whole components: **18 of 19 reverts, and 15 of 18 by
`buildFaces-empty`** — the engine was throwing away entire components for two mis-oriented
wires. A seed change measured against that noise floor could not show its own effect. n5d
removed that discard (recall 50/474 -> 87/474, zero models worse), so the A/B can now
measure the seed floor rather than the discard.

**This is still NOT a global lower constant.** The floor is derived per model:
`seed_floor = f(median facet angle of the model's curved bands)`, from the same (d, alpha)
fingerprint the audit and the n5d rule already use. One fingerprint, now three consumers.

## 1. WHY IT MATTERS — the measured population

Corpus-wide, over all **474** truth cylinders, classified by per-facet angle against the
Phase-B seed band `[thetaCylLoDeg 5.0, thetaCylHiDeg 60.0]`:

| theta per facet | cylinders | share |
|---|---|---|
| in band [5, 60] | 304 | 64.1 % |
| **below 5 (never seeded)** | **170** | **35.9 %** |
| above 60 | 0 | 0 % |

**36 % of the corpus's cylinders are unreachable at any point downstream** — no cascade, no
budget and no face-build fix can recover them, because Phase B never seeds them.

Per model, for the two that dominate:

| model | truth | in band | below 5 |
|---|---|---|---|
| `SpeedTestStructure` | 246 | 144 | 102 |
| `gripper_gear` | 75 | 20 | **55** |

## 2. PREDICTIONS (recorded BEFORE any build)

- P36: on the n5d binary with a self-calibrated floor, `gripper_gear` recovers **>= 40 of
  its 55 below-band cylinders**. | result: pending
- P37: corpus-wide, **models worse = 0** and **MISSED_silent_wrong_rebuild = 0** — the
  designed-polygon negatives are octagons at 45 deg/facet, far ABOVE the floor and therefore
  untouched by lowering it. | result: pending

## 3. GATES

Corrected §2b (closure relative to the input mesh; `|dV| <= dV_legit + max(1e-4*V,
3*dVolPredAbs)`), `MISSED = 0`, models worse = 0, and parity or ID-independent geometric
equivalence on every model that already builds. Recall (P20) strictly up, reported against
BOTH denominators: raw (/474) and in-band (/304).

### P53 — measured-deviation vertex tolerances will EXPOSE masked defects (written before n5e (b))

Recorded 2026-09-06, before any part of n5e (b) is written.

The `0.2929*R` cap is applied 16 566 times across 105 models, 100% of them wider than `sewTol`,
widest 15.83 mm (§29). A tolerance that large is a sphere around each vertex inside which OCCT
will identify anything; faces that pass `BRepCheck` today may be passing only because that
sphere covers a gap that is really there.

Prediction: replacing it with the measured vertex-to-analytic-curve deviation (bounded by the
measured sagitta) will make some currently-building faces FAIL, and the gate's "models worse =
0" may go red **for the right reason** -- the defect was always present, and the honest
tolerance stopped hiding it.

Standing instruction if that happens: **do not re-widen the tolerance.** Fix the exposed
defects, and promotion waits on them. A recall drop after (b) is discovery, not regression --
and it is still a block. Distinguishing the two cases is the whole content of the check: for
each newly failing face, show whether the geometry was ever sound at the honest tolerance.

# ============================================================================
# CONSTANT 2 — the near-flat 2.0 deg gate, self-calibrated from alpha
# ============================================================================
# Status: pending. Written 2026-09-07 while W1 measures P59; no instrument yet.
# Order: constant 2 PRECEDES constant 1 -- 246 cylinders (144 in band) outrank the 170
# below band, 102 of which sit inside SpeedTestStructure and stay blocked until it builds.

## Why this constant is now the root of three separate defects

1. L07_flanged_bushing_recon's 1.7 % volume move (P48/P50): planes absorbing curvature with
   spread in (1.0, 2.0] deg -- 181 faces on L07, 77 on L08_T_bracket, 2 on sample_0037,
   counted PER FACE, never per component.
2. The vertex bumps on SpeedTestStructure (P56/P57): two near-flat planes at 2.0016 and
   2.1394 deg intersect in a line whose position is hypersensitive to their normals, landing
   0.058 / 0.072 mm off a perfectly straight chain.
3. The bad ellipses on SpeedTestStructure (P55 rewritten arm): every one of the four invalid
   edges pairs region 242 with a near-flat micro-region at 2.0016 or 2.1394 deg.

Two and three are the same regions. That is the argument for doing constant 2 before
constant 1, and it is measured, not assumed.

## Predictions (pending)

- **C2a** the near-flat population is bimodal in alpha (the model's own tessellation angle):
  genuine flats sit far below alpha, absorbed curvature sits within a small multiple of it.
  Predicted: on L07, the 181 absorbing planes have spread/alpha clustered above 1, the
  non-absorbing planes below.
- **C2b** a threshold expressed as a multiple of alpha reproduces the current 2.0 deg gate's
  decisions on the models where 2.0 deg is right (L08_T_bracket 77, sample_0037 2) while
  dissolving SpeedTestStructure's 2.0016 / 2.1394 micro-regions into their neighbours.
  Predicted: one multiple exists that does both; if none does, the arm is wrong and the gate
  is not a single constant.
- **C2c** dissolving those micro-regions removes both the bumps and the bad ellipses on
  SpeedTestStructure, because both are consequences of the pairing.
  Predicted: with the micro-regions merged, chains 180-183 no longer exist as plane|cylinder
  pairs at all.

One-command check (worker task, NOT yet dispatched): per model, alpha from the mesh; per FACE,
normal spread and whether it absorbed curvature; the ratio spread/alpha; the population split.
No engine change for the measurement -- alpha and per-face spread are computable from the mesh
and the region dump.

## Standing constraint

P53 in force. This is a gate that currently ACCEPTS regions; tightening it will reject some,
and any face that turns red is fixed, never re-covered. Full 206-model set: this is a
tolerance change in all but name.

### CONSTANT 2 — SCOPE CORRECTION, and C2c REFUTED (W7 census, binary abbabea19b41,
### parity SAME on L06 and NEG_SC-59, branch n5g-c2-census from main, excludes 720320a)

**The premise of this chapter was wrong, and it is my error.** `_NEAR_FLAT_DEG = 2.0` exists
ONLY in the Python audit (`src/mesh2step/intent.py:486`). The ENGINE has no near-flat constant:
grep for nearFlat / near_flat / NEARFLAT across the fork's sources returns nothing. Engine plane
acceptance runs on `DerivedTols::kGaussPlanarity` plus deviation tests
(`refit_grow.cpp:333, 338, 376, 646`). intent.py's own comments describe 2.0 deg as "the
engine's ABSOLUTE near-flat gate" -- that description is FALSE and must be corrected in the code.

Independent proof from the census: L07's plane regions reach spreadDeg **118.7626**, and L08
reaches 53.4631. No 2 deg gate could admit those. Whatever absorbed them, it was not a 2 deg
threshold.

Consequence: changing constant 2 changes what the audit FLAGS, not what the engine BUILDS. It
cannot unlock a single cylinder. This chapter cannot be the lever the campaign needed.

**Mesh tessellation (all edge-adjacent facet pairs, degrees):**

| model | nTri | turnP10 | turnMedian | turnP90 | turnMax |
|---|---|---|---|---|---|
| L07_flanged_bushing_recon_normal | 738 | 0.6440 | 7.0828 | 11.9180 | 135.6020 |
| L08_T_bracket_recon_normal | 884 | 0.1244 | 3.7642 | 18.1099 | 125.3875 |
| sample_0037_normal | 232 | 0.0000 | 8.7212 | 90.0000 | 135.0000 |
| SpeedTestStructure_normal | 5964 | 0.0009 | 3.2764 | 68.6666 | 97.3520 |
| SpeedTestStructure_coarse | 4474 | 0.0000 | 4.5839 | 79.1420 | 97.1872 |
| L06_adapter_plate_normal | 1620 | 0.0000 | **0.0000** | 90.0000 | 90.0000 |
| NEG_SC-59_fine | 708 | 0.0000 | **0.0000** | 90.0000 | 90.0000 |

Note L06 and NEG_SC-59 have median turn 0.0000 -- most adjacent facets are exactly coplanar --
so any "multiple of the median turn" rule is DEGENERATE on them (division by zero). Any
alpha definition must handle that; the worker recorded those rows as a convention, not a
measurement, and said so.

**C2a CONFIRMED, but it separates a different population than predicted.** Plane spread
normalised by the model's own median facet turn:

| model | ratio < 1 | 1-2x | 2-4x | 4-8x | >= 8x |
|---|---|---|---|---|---|
| L07 | 2 | 3 | 26 | 4 | 1 |
| L08_T_bracket | 2 | 1 | 7 | 26 | 2 |
| SpeedTest_normal | **542 (all)** | 0 | 0 | 0 | 0 |
| SpeedTest_coarse | **593 (all)** | 0 | 0 | 0 | 0 |

**C2c REFUTED.** SpeedTestStructure's plane regions -- including the 2.0016 deg (3 tris) and
2.1394 deg (4 tris) micro-regions behind the bad ellipses -- all have spread BELOW their own
mesh's median facet turn. They are legitimately flat at that tessellation, not flattening
artifacts. Dissolving them was never going to remove the vertex bumps or the bad ellipses,
because they are not over-absorbed in the first place.

**What survives.** The ratio is a real discriminator and it isolates L07 and L08, which is
exactly where the measured 1.7 % volume error lives. The engine constant to examine for that is
`kGaussPlanarity`, not a 2 deg gate.

Absolute spread buckets, for the record (plane regions, count / summed mm2):

| bucket | L07 | L08 | ST_normal | ST_coarse |
|---|---|---|---|---|
| [0, 0.5) | 2 / 4.4986 | 2 / 5.0306 | 193 / 293680.4 | 217 / 308008.4 |
| [1.5, 2.0) | 0 | 0 | **301 / 388.8** | **310 / 300.0** |
| [2.0, 2.5) | 0 | 0 | 8 / 15.1 | 39 / 55.2 |
| [5.0, inf) | **34 / 3.9111** | **36 / 7.5264** | 0 | 0 |

The 301/310 spike in [1.5, 2.0) on SpeedTestStructure is repeated identical features (identical
spread and area, e.g. 63 regions at spreadDeg 1.7526 / area 0.6305) -- this model is a
deliberately repetitive speed-test part, not a gate artifact.

**Coverage caveat the worker raised and I am keeping:** the DIAG_C2 row counts are RegionSet
regions (L07 36 planes, L08 38), which do NOT equal the "181 / 77 / 2 absorbing planes" quoted
earlier in this campaign. Those earlier counts were STEP faces, a different population that
includes exploded facet islands. The two must not be compared.

# ============================================================================
# CONSTANT 1 — named sites and the mechanism prediction (written 2026-09-08,
# BEFORE any instrument, per the method rule)
# ============================================================================

## The two sites the 5 deg floor actually gates

`thetaCylLoDeg = 5.0` (`src/refit.hpp:70`) becomes `tol.thetaCylLo` at
`src/refit_segment.cpp:34` and is then tested in **two** places, not one:

1. **SEED** — `seedInBand(phi, tol)` at `src/refit_grow.cpp:738`, called from
   `refit_grow.cpp:1521` (`if (!seedInBand(a.phi, tol)) continue;`).
2. **GROW** — `src/refit_grow.cpp:1616`,
   `if (phi < tol.thetaCylLo - angleBandEps(tol.thetaCylLo)) continue;` — the test that
   admits an adjacent provisional into an ALREADY-SEEDED cylinder set.

Note `adaptCoarseSegmentParams` (`refit_segment.cpp:20-23`) already raises `thetaCylHiDeg`
per model when `coarseFusionBand(mv)` holds. **A per-model adaptation of this band is
therefore existing, accepted machinery, not a new idea** — the HI end is already calibrated
and the LO end is not.

## P72 — the floor excludes twice, and grow is the larger share

Prediction, recorded before the instrument exists: on `gripper_gear`, of the 55 truth
cylinders whose per-facet angle is below 5 deg, **more are lost at the GROW gate (1616) than
at the SEED gate (1521)** — because a chamfer/fillet band only needs ONE facet pair above the
floor to seed, but every subsequent facet must clear the same floor to be admitted, so a band
that seeds can still be starved to a stub.

Falsified if the split is seed-dominated. Either way the split decides where a
self-calibrated floor has to be applied: if it is grow-dominated, changing only `seedInBand`
recovers nothing, and an arm that changes only the seed site would be a false negative.

**Reachability control (mandatory before the zero is believed):** both counters must be shown
non-zero on at least one model that must read non-zero. A 0 at site 1616 is a measurement only
after site 1616 is proven to fire at all.

## P73 — alpha is not yet computed anywhere

There is **no** `medianFacetAngle` / `alpha` / curved-band fingerprint symbol in `src/`. The
spec's phrase "the same (d, alpha) fingerprint the audit and the n5d rule already use" does
not correspond to an engine symbol; grep for it returns nothing. So the self-calibrated floor
needs alpha to be COMPUTED, and P36 cannot be tested until it is.

Prediction: alpha (median per-facet turn angle over provisionals that are neither planar nor
sharp) on `gripper_gear` is **below 5 deg**, which is why its 55 cylinders are below band;
and on a model whose cylinders are in band it is **above 5 deg**. If alpha does not separate
the two, a floor derived from alpha cannot work and the arm is dead before it is built.

## Chamfers are in scope

Tommaso, 2026-09-08: "chamfers are cylinders' parts too". A chamfer is a cylindrical (or
conical) band of small angular extent; on a fine mesh its per-facet angle is small by
construction. That is exactly the below-5-deg population, and it is 170 of the corpus's 474
truth cylinders (35.9 %).

## RESULTS — P72 confirmed, P73 refuted (branch `n5g-seedfloor-diag` off main `abbabea`,
## head `2ebb11c`; instrumented sha `3385d5a11e0cae56`, baseline `8790b98b85c8b833`;
## parity 4/4 MATCH on STEP DATA md5 with the diag env var off)

### P72 — CONFIRMED. The grow gate loses more than the seed gate.

`gripper_gear_normal`: `seed_rejected_lo` **164**, `grow_rejected_lo` **272**. A fix applied
only to `seedInBand` (site 1521) would leave the larger share on the floor. **Both sites must
change together**, and an arm that touches only the seed site would read as a false negative.

### P73 — REFUTED, twice over, and the self-calibrated floor is DEAD as specified.

Predicted alpha < 5 deg on gripper. Measured **alpha = 9.278 deg** (n=696) — nearly double the
floor it was supposed to justify lowering. On L06 it is 13.846 deg. A floor set to f(alpha) with
alpha above the current constant does not lower the floor, it raises it.

Worse, and decisive: **alpha is UNDEFINED on all three CAD-verified sentinels.** n=0 on
NEG_SC-59_fine, NEG_SOT-143_fine, NEG_TSOT-23_fine. This is a proven measurement, not a dead
loop: the control `alpha_ctx` (every non-planar facet edge, sharp included) reads n=278/368/290
with **min 44.513 deg** — those meshes contain no gently curved facet edge at all. A per-model
floor derived from alpha cannot be computed on precisely the models that must not regress.

**Instrument-domain caveat, stated rather than hidden.** alpha was measured over edges with
`thetaPlane < phi < thetaSharp` = (2, 30) deg, but the rejected population runs from **0.847**
deg. alpha's own window excludes part of the population it was meant to characterise, so its
VALUE on gripper is biased upward and is not a clean refutation of "alpha is small". The
sentinel result does not depend on the window (min 44.5 deg over ALL non-planar edges), so the
"undefined on the sentinels" half stands on its own and is what kills the arm.

### The measurement hands over a much simpler hypothesis: THE GAP

| model | LO-rejected phi (min/p25/med/p75/max, deg) | n (seed + grow) |
|---|---|---|
| gripper_gear_normal | 0.847 / 2.778 / 3.12-3.94 / 4.13-4.18 / **4.184** | 164 + 272 |
| NEG_SC-59_fine | **0 / 0 / 0 / 0 / 0** | 1 + 4 |
| NEG_SOT-143_fine | **0 / 0 / 0 / 0 / 0** | 1 + 4 |
| NEG_TSOT-23_fine | **0 / 0 / 0 / 0 / 0** | 1 + 6 |
| L06_adapter_plate_normal | no LO rejection at all | 0 + 0 |

Every chamfer facet gripper loses sits in **[0.847, 4.184]**. Every facet the three sentinels
lose sits at **exactly 0.000** — genuinely coplanar, and correctly rejected. Between them is an
empty interval **(0, 0.847)**, and L06 has no traffic in this test at all.

So the population does not need a per-model formula to be separated. It needs a floor inside
the gap. **The 5 deg constant is not too high by a subtle margin; it is above the ENTIRE
chamfer population on this model.**

## P74 — a fixed floor inside the measured gap (recorded BEFORE the build)

Change `thetaCylLoDeg` 5.0 -> **0.5** (inside the empty interval), applied at BOTH sites.

- P74a: `gripper_gear_normal` builds **>= 40 additional cylinders** (spec P36's bar), because
  all 436 of its LO rejections are above 0.5 deg and none of the sentinels' are.
- P74b: the three fine-mesh sentinels keep **12 / 16 / 12** exactly. Their LO rejections are at
  phi = 0.000 and stay rejected by a 0.5 deg floor; nothing else in their traffic moves.
- P74c: `L06_adapter_plate_normal` is **byte-identical** on the STEP DATA section — it has zero
  LO rejections, so a change to the LO test cannot reach it. This is the arm's null control:
  if L06 moves, the change is doing something other than what it says.
- P74d: `MISSED_silent_wrong_rebuild = 0` on the 26 negatives. The designed-polygon negatives
  are octagons at ~45 deg/facet, far above any floor in play and therefore untouched.

Falsified if gripper gains < 40, or if any sentinel loses a cylinder, or if L06 changes.

**The known counter-evidence, not suppressed.** A GLOBAL `--cyl-seed-lo` lost its real-CAD A/B
at 12.9 % against a 21.3 % baseline, and that is the reason this road was abandoned. It ran
while the plate-orientation defect discarded whole components (18 of 19 reverts, 15 by
`buildFaces-empty`), which n5d removed. The A/B must therefore be REDONE, not cited either way.
A recall drop that survives on the n5h baseline refutes P74 regardless of the gap.

**Risk this arm carries, named in advance.** Admitting facets down to 0.5 deg into cylinder
claims is the near-flat population that n5g constant 2 is about, and the source of the bad
plane-cylinder ellipses. The protection is `models worse = 0` on the full set plus MISSED = 0,
and neither may be relaxed to let this land.

---

## Decision 2026-09-08 (Tommaso): alpha-derived floor retired, fixed 0.5 deg floor proceeds

**P73 REFUTED — stands.** The alpha-derived (self-calibrated) seed floor is retired. It is not
re-attempted and not re-argued; the chapter's floor is now a fixed constant, not a function of the
model's own tessellation.

**P74 — the fixed 0.5 deg floor at BOTH sites** proceeds as already written. Arbiter is the FULL
set A/B, no exceptions:
- `models worse = 0` on the full corpus,
- `MISSED_silent_wrong_rebuild = 0`,
- sentinels `NEG_SC-59_fine` 12 / `NEG_SOT-143_fine` 16 / `NEG_TSOT-23_fine` 12,
- **`L06_adapter_plate` byte-identical as the NULL CONTROL** — if the null control moves, the A/B
  is measuring something other than the floor and the run is void before its rows are read.

### P79 — the near-flat models must be reported by name, not absorbed into the aggregate

Written BEFORE the A/B is read, so the rows cannot be rationalised afterwards.

**Prediction.** `L07_flanged_bushing_recon`, `L08_T_bracket_recon` and `sample_0037` **CHANGE**
under a 0.5 deg floor. Their 1-2 deg facets sit in the band where a plane claim and a cylinder
claim are both admissible, so lowering the floor to 0.5 deg makes those facets contested rather
than automatically planar.

**Reporting obligation.** These three rows are reported EXPLICITLY, each with either geometric
equivalence (bytes differ, geometry does not) or the signed cylinder delta. They may not be
reported only inside the corpus aggregate, where three contested models are invisible against 333.

**Falsified if all three are byte-identical** — the floor then does not reach the near-flat
population at all, and the 2.0 deg constant-2 gate, not the seed floor, is what governs them.
This is a genuine possibility and would itself be the finding: it would mean constant 1 and
constant 2 are independent, which the chapter currently assumes without having measured.

**Not a promotion blocker by itself.** A change on these three is expected, not forbidden; what is
forbidden is shipping it unnamed. A cylinder LOSS on any of them is a `models worse` row and
blocks under the normal gate.
