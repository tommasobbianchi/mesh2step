# n7 — partial adoption: ship what is good instead of discarding the component

Opened 2026-09-07. bd: projects-ajv. The largest single lever measured in this campaign.

## The defect, measured

On SpeedTestStructure_normal `buildFaces` builds **178 valid cylinder faces and 521 valid plane
faces**, then returns false at exit `j6-uncollapse`, calls `out.clear()`, and the whole component
reverts to facets. Every one of those faces is discarded because the SHELL will not close.

How close it gets: the J6 heal takes the shell from **444 free edges to 4** (n5j lets it continue
while it makes progress; a third pass closed it in combination with the n5e curve rule). The
component is discarded over a residue of 4 edges out of 444.

P65 established the faces themselves are sound: across 5 models and 14 passes, **zero cylinder
faces are ever invalid**; all invalidity is in plane faces, and n6's oracle ban clears those
(75 -> 0 on this model) at zero cylinder cost.

So the component is discarded not because its analytic faces are wrong, but because the
all-or-nothing acceptance has no way to say "keep these, facet the rest".

## The claim

The engine ALREADY builds mixed shells: `built` contains region faces AND `makeFacet` triangles
for exploded regions and islands (P65's census separated them with a `src=region|facet` column).
Partial adoption is therefore not a new capability, it is the existing capability applied at the
closure failure instead of a wholesale revert.

## Arms and predictions (pending; a refuted prediction rewrites its arm, never edited)

- **P68a** the free edges remaining when J6 gives up are LOCALISED: they touch a small number of
  regions, not a diffuse set. Predicted: on SpeedTestStructure_normal the 4 residual free edges
  touch <= 8 regions.
- **P68b** exploding ONLY the regions adjacent to those residual free edges closes the shell,
  while every other region keeps its analytic face. Predicted: the component is adopted, the
  shell closes, and smoothBuiltCylinders lands within a few of 178 rather than at 0.
- **P68c** the discarded work is not recoverable by any cheaper means: the residual edges are
  not healable by a further uncollapse pass (n5j alone measured 436 -> 8 and then stalled
  because the heal found no matching collapsed chain).

Falsified if the residual free edges touch a large fraction of the regions (then localisation is
false and exploding them approaches a full revert anyway), or if exploding them fails to close
the shell (then closure is blocked by something other than those regions).

## Why this is ordered first

246 of the 474 truth cylinders in the corpus (52 %) are in SpeedTestStructure, and 144 of them
are in band. No other single change reaches that many. It is also NOT blocked by n5g constant 2 --
that was a phantom (the 2.0 deg constant lives only in the Python audit; the engine has none).

## Gates (unchanged, full set)

MISSED = 0 on the 26 negatives; 2b v2 with no row worse; **models worse = 0** on the FULL
333-model corpus with NEG_SC-59_fine (12), NEG_SOT-143_fine (16), NEG_TSOT-23_fine (12) as named
sentinels; recall strictly up; geometric equivalence per differing model; one defect per commit;
BISECT before attributing any regression.

## Relationship to the other branches

- `n5j-j6-progress` (c3c3a56): lets the heal continue while it makes progress. Committed, inert
  alone. If partial adoption removes the need for a perfect close, n5j may become unnecessary --
  or may compose with it. Measure both arms.
- `n6-p66-chainban` (ff4127bec0d7): oracle-driven per-chain ban, clears invalid plane faces at
  zero cylinder cost, no recall gain alone. Likely composes with this.
- `n5e-honest-cap` (720320a): the +190 stack WITH the 40-cylinder regression. Its mechanism is
  still unexplained (bd projects-6p0) and must not be closed by association.

## P68 — RESULTS (W8, binary 3fafc66308d0, parity SAME on the DATA SECTION for L06 and
## NEG_SC-59; branch n7-p68-locality from c3c3a56, excludes 720320a)

**P68a CONFIRMED on SpeedTestStructure_coarse.** 52 residual free edges touch **26 of 744
regions = 3.49 %**, every one a Plane with nTris=3, in two contiguous id runs (442-463,
695-716), all 104 endpoints inside x [20.163635, 20.207247], y [142.513748, 142.836807],
z [180.141403, 223.923462]. One vertical seam, not a diffuse failure. 13 of the 52 edges are
zero-length on a region face and 13 more zero-length on rid=-1 (facet/island) faces.

### CORRECTION TO THE CONTEXT I SUPPLIED — my error, caught by the worker

I told the worker, as measured fact, that SpeedTestStructure_normal runs 444 -> 4 free edges and
gives up at `j6-uncollapse`. On this branch it runs **436 -> 8 and does NOT give up there**; it
exits at line 5015 with `exit=none`. My P61 measurement was taken on the n5e-stack binary and I
generalised a binary-specific behaviour into a property of the model. The 444 -> 4 sequence
belongs to the n5e stack; the give-up at j6-uncollapse belongs to COARSE (24 -> 52).

### The five reverting models fail by FOUR different causes

| model | revert cause | J6 entries |
|---|---|---|
| SpeedTestStructure_normal | cascade give-up, `exit=none line=5015` | 2 (436 -> 8) |
| SpeedTestStructure_coarse | `j6-uncollapse line=4858` | 2 (24 -> 52) |
| L08_T_bracket_recon_normal | cascade give-up, `exit=none line=5015` | 1 |
| L04_soap_bar_normal | VOLUME BUDGET, dV=39.412300 vs budget=16.620928 | 0 |
| clamp_half_a_normal | `sameparameter-threw` (Geom2dConvert Concatenation Error) | 0 |

So "the component discard" (bd projects-ajv) is NOT one defect. It is at least four, and the
issue must be split.

### What line 5015 actually is, and the decisive counters

Line 5015 is the CASCADE give-up, not J6: the block sets `g_bfSkips[-4] = !shValid` and
`[-5] = culprits.size()`, then `restoreShared(); out.clear(); return false`.

Measured on SpeedTestStructure_normal:

    -4:1   shell closed but INVALID
    -5:73  culprits identified -- NOT an empty set
    -13:73 invalid faces
    -11:73 of them Plane      -10:0 Cylinder      -12:0 other
    -14:72 mixed-neighbour    -2:1 hostR2         -3:1 u2Done

Consistent with P65's independent count of 73 invalid plane faces in the final pass.

**The component is discarded because of 73 invalid PLANE faces that the cascade has already
identified by id, taking 178 valid cylinder faces with them.**

## P69 — pending. Explode the named culprits instead of the component

Claim: the cascade computes the culprit set and then throws away everything instead of applying
it. Exploding ONLY those 73 culprit plane regions to facets, and keeping every other region
analytic, yields a closed valid shell.

- **P69a** all 73 culprits are Plane regions and none is a Cylinder, so exploding them cannot
  cost a cylinder face by construction. (Already measured: -11:73, -10:0.)
- **P69b** after exploding the 73, the shell is closed AND BRepCheck-valid, the component is
  adopted, and smoothBuiltCylinders on SpeedTestStructure_normal goes 0 -> of order 178.
- **P69c** the same treatment applied to L08_T_bracket_recon_normal (same exit, same cause)
  adopts that component too.

Falsified if exploding the culprits leaves the shell invalid (the culprit set is then incomplete
or wrong), or if the explosion cascades into further invalidity.

Note the OTHER three causes are out of scope for P69 and need their own predictions: coarse's
unclosed seam (P68a's 26 regions), L04_soap_bar's volume budget (dV 39.41 vs 16.62 -- and the
standing instruction is NEVER to suppress a revert by widening a budget), and clamp_half_a's
`sameparameter-threw` exception.

## P69 — RESULTS (W9, binary 1a8d860fbc1e, parity SAME with env unset on L06 and NEG_SC-59;
## branch n7-p69-explode-culprits, contains c3c3a56, excludes 720320a; commit 1a8d860fbc1e)

Change: at the cascade give-up, explode ONLY the already-identified culprit regions and rebuild,
instead of `out.clear()` on the whole component. Behind STL2STEP_EXPLODE_CULPRITS. RULE 1.4
preserved (empty culprit set still escalates). 4-round termination guard.

**P69a CONFIRMED.** 73 culprits exploded on SpeedTestStructure_normal, 1 on L08_T_bracket, 0
elsewhere. All six sentinels identical on every column with STEP data SAME:
NEG_SC-59_fine 12, NEG_SOT-143_fine 16, NEG_TSOT-23_fine 12, L06_adapter_plate 14, L01_rod 1,
gripper_gear 11. The explosion cannot cost a cylinder, as predicted from -11:73 / -10:0.

**P69b HALF CONFIRMED, HALF REFUTED.** The component ADOPTS -- smoothRevertedTrue 1 -> 0,
usedRefit true, shell watertight, freeEdges 0, solids 1, facesAfterUnify 5064 -> 3724,
volumeDeltaPct 0.000542. The all-or-nothing discard is FIXED and costs nothing.
But smoothBuiltCylinders stays **0**, not ~178. The model lands in smoothAdoptedNoCyl.

### MY ERROR, the second instance of the same mistake

I have been asserting "178 valid cylinder faces are built and then discarded". That was measured
on the **n5e-stack binary** (W3's DIAG_PLAN, emitted=1 on 178 of 303 cylinders). On THIS branch
and on the LIVE baseline, SpeedTestStructure_normal plans 183 cylinders and builds **zero**
cylinder faces. P65's own table reported it -- "SpeedTest_normal, final pass, cylinder faces 0" --
and I read that zero as "no cylinders available to be invalid" rather than "no cylinder faces
exist". This is the same error as the 444 -> 4 sequence: an n5e-stack measurement generalised
into a property of the model. Twice.

| branch | SpeedTest_normal cylinder faces BUILT |
|---|---|
| live v1.1.0-n5h / n5j / n7 | **0** (183 planned) |
| n5e stack (720320a, curve rule) | **178** |

### What this relocates

**The n5e curve rule is what makes those cylinders constructible at all.** That is the
unexplained mechanism of bd projects-6p0, and it is now a precise question rather than a vague
one: why does KEEPING POLYLINES on certain chains allow cylinder FACES to be built, when
collapsing those chains to analytic curves prevents it?

The component discard was never the only lock on this door; it was the second one. P69 opened it
and the first lock is still shut.

### Status of the four causes in this chapter

| cause | models | state |
|---|---|---|
| cascade give-up (shell closed, invalid, culprits named) | ST_normal, L08_T_bracket | **FIXED by P69**, no cylinder gain |
| j6-uncollapse unclosed seam (26 of 744 regions, 3.49 %) | ST_coarse | open; P68a measured, no fix |
| volume budget dV 39.4123 vs 16.6209 | L04_soap_bar | open; NEVER widen the budget |
| sameparameter-threw (Geom2dConvert) | clamp_half_a | open, an exception not a decision |

P69 is worth landing on its own merits -- it converts a wholesale discard into a targeted one at
zero sentinel cost -- but it does NOT satisfy "recall strictly up" alone, so it cannot be
promoted by itself under the standing gate.

---

## E1 — the ENABLING PAIR (P69 + P58), branch `e1-enabling-pair` off main

Opened 2026-09-08 11:4x. Written BEFORE the build, per method. Id taken from the registry
(next free was P80; P72-P79 are all defined elsewhere).

### What P58 concretely is, read from the code rather than from memory

`refit_build.cpp` (P69 tree, line ~4191) has two symmetric acceptance sites:

- **cylinder|cylinder**: `acceptCap = intAnaAcceptResidual(mv, ch, sewTol, A, B)` — a MEASURED
  budget, the same helper used at :1004 and :1013.
- **plane|plane**: `acceptCap = std::max(sew * 50.0, 1.0)` — the rubber stamp. It raises the cap
  to whatever the residual happens to be, so anything under 1 mm is admitted unconditionally.

P58 is therefore one substitution: **give plane|plane the budget cylinder|cylinder already uses.**
It is not a new mechanism and it introduces no constant — it deletes one.

### Why the pair is enabling and cannot promote alone

Neither recovers a cylinder by itself. P69 makes `SpeedTestStructure_normal` ADOPT (closed, valid,
3,724 faces, **0 cylinders**); P58 corrects the curve choice without adding recall. Under
`recall strictly up` neither passes a promotion gate on its own, so they land together with
whatever does recover cylinders (P71, or n5g's floor). Exploration only this turn.

### P80 — the pair is inert on the sentinels and adopts on SpeedTestStructure

**Predicted.**
1. `SpeedTestStructure_normal` ends **closed and BRepCheck-valid**, component **adopted**
   (`smoothRevertedComponents = 0`), as P69 alone already does.
2. The six sentinels — `NEG_SC-59_fine` (12 cyl), `NEG_SOT-143_fine` (16), `NEG_TSOT-23_fine`
   (12), `L06_adapter_plate_normal` (14), plus `gripper_gear_normal` and
   `SpeedTestStructure_coarse` — are **DATA-section byte-identical** to v1.1.0-n5h.
3. Cylinder count on `SpeedTestStructure_normal` stays at **0**. The pair does not recover
   cylinders and is not expected to.

**Falsified if** any sentinel's DATA section moves, or if adding P58 to P69 breaks the adoption
P69 achieves alone. Either outcome means the pair is NOT inert and cannot be treated as a free
carrier for a later recall change.

**Reachability control.** `intAnaAcceptResidual` must be observed returning a value DIFFERENT from
`max(sew*50, 1.0)` on at least one plane|plane chain, or "no sentinel moved" is consistent with
the substitution never having executed, and proves nothing.

### P80 — REFUTED by its own reachability control (binary e1-2a5aa8a69703, branch `e1-enabling-pair`)

The control fired first, exactly as it was written to: on `SpeedTestStructure_normal` the
substitution executed **2,679 times** and `differs=1` on **ZERO** of them. Every plane|plane
chain got `newCap = oldCap = 1.000000000`.

**Cause, read from the helper rather than inferred.** `intAnaAcceptResidual`
(`refit_build.cpp:593`) opens with

    double acceptR = std::max(sewTol * 50.0, 1.0);

and thereafter only ever RAISES it with `std::max`. **The "measured budget" contains the rubber
stamp as its floor and can never be smaller than it.**

**This overturns what I wrote in the P80 entry above, and I am not editing that entry.** I claimed
the cylinder|cylinder site "already judges against a MEASURED budget" and that P58 was one
symmetric substitution that deletes a constant. Measured: both sites are rubber-stamped by the
same `max(sewTol*50, 1.0)` floor; cyl|cyl merely adds `fit * k + eps` terms on top of it. My
substitution is a **no-op by construction** — it cannot tighten anything, only loosen.

**What P58 actually requires**, re-read from `n5e-wire-chaining.spec.md:170-176`: the rule is to
use the intersection line *only when it is WELL-CONDITIONED* — i.e. **REJECT** the analytic curve
when the terminal residual exceeds a budget, and fall back to the polyline. That is a rejection
gate, not a snap cap. Capping `snapCap` cannot express it, because `snapCap` only governs how far
a TVertex may be moved, not whether the curve is used at all.

P58 is therefore **not implemented** and its arm is rewritten: the next attempt must act at the
curve-CHOICE site, with a budget that does not inherit the 1.0 floor. Round 1 of 3 (R1).

### The P69 switch is env-gated, and the "adopts" claim does not match the counters

`STL2STEP_EXPLODE_CULPRITS` (`refit_build.cpp:699`) gates the culprit explosion, cached once.
Without it the run is baseline. With it, on `SpeedTestStructure_normal`:

| | switch off | switch ON |
|---|---|---|
| facesAfterSmooth | 5064 | **3724** |
| watertight / openShells / solids | true / 0 / 1 | true / 0 / 1 |
| smoothBuiltComponents | 0 | **0** |
| smoothRevertedComponents | 1 | **1** |
| smoothBuiltCylinders | 0 | 0 |

The 3,724 figure reproduces exactly, so the P69 path IS executing and the shape IS closed and
single-solid. But **the component is still REVERTED, not adopted** — `smoothBuiltComponents = 0`,
`smoothRevertedComponents = 1`, both times.

"P69 makes SpeedTestStructure_normal ADOPT" is therefore not what this binary's own accounting
says. Either "adopt" was an over-reading of "closed + valid + 3724 faces", or the component
counters mis-report (the same class of defect as the watertight flag n5h had to fix). Not settled
by assumption: the P0 re-measure on this binary decides it, because if the component is still
reverted the 246 truth cylinders do NOT move into scope and the "in-scope pool >= 79 + 246"
expectation is refuted.

---

## P81 — the comb's rounded prong edges are TANGENT fillets, and tangency is why IntAna fails

Written 2026-09-08 14:5x, BEFORE any measurement, from Tommaso's reading of the vision renders:
`SpeedTestStructure` is a **comb** — three parallel plate-like prongs on a common base — and its
246 truth cylinders are the **rounded vertical edges of those prongs**.

### The claim

A rounded prong edge is a **fillet**: a partial cylinder (~90 deg of arc) **tangent** to the two
planes it joins. A tangent plane-cylinder junction is ill-conditioned *by construction* — the
surfaces touch along a line rather than crossing, so `IntAna_QuadQuadGeo` returns
empty / same / a degenerate conic. That is a different failure from a badly-fitted surface: the
intersection is genuinely undefined, not merely inaccurate.

### Prediction (pending)

On `SpeedTestStructure_normal`, for every FAILING chain (the four Elips chains 180-183 and every
`IntAna cyl|cyl empty/same`):

- the pair is a **small-radius cylinder (R ~ 0.2-0.4)** and a plane whose normal is **within
  ~2 deg** of the cylinder's surface normal at the junction — i.e. tangency;
- whereas **hole** cylinders meet their plates at **~90 deg** and do not fail.

Measured as: per failing chain, the angle between the plane's normal and the cylinder's surface
normal evaluated at the chain's MIDPOINT (not its terminals — the terminals are where the
snapping already distorts the picture).

**Falsified if** the failing population's junction angles are spread across the range, or if
non-failing chains show the same near-0 deg angles. Either would mean tangency is a correlate,
not the cause — the same trap P55's length-to-tolerance ratio fell into.

**Reachability control:** the ~90 deg hole population must be OBSERVED in the same dump. If every
chain in the dump reads near-tangent, the measurement cannot discriminate and proves nothing.

### If it holds

The edge at a tangent junction is the cylinder's **ruling line** at the tangency angle — analytic,
exact, and needing no intersection at all. P58's rejection rule then gets a **tangent branch**:
never call `IntAna` when the dihedral is below the budget; emit the ruling line instead.
