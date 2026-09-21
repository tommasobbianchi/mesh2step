# The feature pass as a loop — design, prototype and measurement

*Branch `feat/agent-loop`, worktree `.worktrees/agent-loop`, base `a087327`. Prototype: not
deployed, not merged. Written 2026-09-21.*

The competitor case (Backflip AI) is that the difference between a scrapped generation and a
shipped one was the feedback edge: reconstruct, **check your own work, iterate**. mesh2step
already has the candidate generation — seven builders — and already computes every quantity a
self-check needs. What it did not have is the edge: `feature.reconstruct` builds seven
candidates, gates each ONCE, keeps the one closest in volume and discards the rest with
everything they recovered.

This branch adds two things to that function and nothing else.

## 1. IP4 — the rejection names its clause (guideline §2.1, mandatory, was partial)

Every candidate now logs the clauses it failed, in severity order, with the Acilindria defect
code:

```
feature stepped:  REJECT dist_p95 [AC-B3]  {... 'cylinders': 11, 'support': 1.0 ...}
feature turned:   REJECT solids [AC-B2] also=['dv_pct', 'dist_p95']  {'solids': 4, ...}
feature block:    REJECT dv_pct [AC-B2] also=['support']  {...}
feature extrude-y:REJECT no_output [AC-NOBUILD] {}
```

Three decisions worth stating, because they change what the next session reads:

* **Severity order, not gate order.** The named clause is the one whose repair the others wait
  on. A build with four solids has a meaningless volume, so reporting it as a volume failure
  sends the reader to the wrong organ.
* **`AC-B4` keeps its meaning.** The physiopathologia defines it as *passed every shape gate and
  was refused for inventing*. A build that fails `solids` **and** `support` is coded `AC-B2`.
* **`no_output` is `AC-NOBUILD`, not a defect.** Three of the seven builders routinely write
  nothing (an extrusion builder refuses a part that is not an extrusion). Coding that as a fault
  would bury the real ones.

`support` is now computed for every candidate that built a cylinder, not only for those that
passed the shape gate, or the immune rejections could not be told apart from the carpentry ones.
It costs one `quads.classify` per part, cached, which the pass already paid on any accepted
build.

## 2. The loop — a rejected candidate gets one targeted second chance

On a named rejection the pass retries instead of discarding. `MESH2STEP_LOOP=0` disables it;
`MESH2STEP_LOOP_BUDGET_S` (default 240 s) bounds the whole pass, and `LOOP_MAX_ATTEMPTS` (2)
bounds each candidate. Both bounds exist because runtime is already a product problem —
mechparts/6 converts in 1968 s.

| Named clause | Action | Why it is not a relaxation |
|---|---|---|
| `solids` | keep the largest solid (`solidfix.largest_solid`) | a selection among solids already built; no face is moved, fitted or added |
| `valid`, `free_edges` | re-sew the faces and `ShapeFix` (`solidfix.sew_fix`) | the face set is unchanged; it closes the shell that carries the cylinders already built |
| `dv_pct` / `dist_p95`, **near-miss only** | re-run the SAME builder at its own higher sampling density (`stepped` 60→180 slices, `turned-envelope` 400→1200 stations) | a better-measured build of the same kind, which must then pass the identical gate |
| everything else | none | a build 500% out on volume is not nearly right, it is wrong |

**The immune system is untouched.** `MIN_SUPPORT`, the mesh-backed radius test and every
threshold keep their values, and a repaired candidate faces the identical gate. The loop earns
cylinders by fixing the SOLID or by measuring the part more finely — never by lowering the bar on
the FEATURE (guideline §0.3.2, §4.B.3).

A refine is refused when the candidate also fails `support`: spending minutes on a denser re-run
of a build that invents is buying confabulation (`AC-B6`).

## 3. The second opinion — the loop's one change to how a rejection is answered

A rejection that names `support` **and nothing else** gets one more question asked, because the
radius test is blind in both directions and mechparts/19 is the proof:

```
19 extrude-z  1 solid, valid, 0 free edges, dv -0.217%, p95 0.018 vs a 2.30 limit
              42 cylinders, radius support 0.21  -> REJECTED
              ...and it puts 17 of 17 mesh cylinder patches on analytic curved faces.
```

`support` asks whether the mesh shows a cylinder of that radius ANYWHERE.
`backing.backed_fraction` asks whether the mesh carries wall at THIS face's axis, radius and
axial extent, with a radial normal — the normal test being what stops a cone from backing the
staircase of cylinders a slicer cuts out of it. `MIN_SUPPORT` is unchanged, the shape gate must
already have passed, and the check costs 0.15–0.8 s of numpy.

It is not a looser test. Measured on the canonical confabulators it is far harsher than the one
it backs up (§5.2). `MESH2STEP_LOOP_BACKING=0` disables it alone.

## 3b. IP4 for the engine — detected and not built (`AC-B2/engine`)

A real user's hotend assembly, live service at `a087327`, 2026-09-21: the engine detected **36
cylinders, 126 fillets, 1 424 planes** and built **none of them**; the delivered STEP is 4 777
planar faces and not one quadric. Nothing in the log said so.

**The counter that looks like it says so is a false witness.** `smoothRevertedComponents` read 1
while `smoothRevertedTrue` read 0 and `usedRefit` was true: the component passed every gate in
`stl2step.cpp` and was ADOPTED, and `refit::buildFaces` produced zero analytic faces from a plan
of 1 586 regions (engine diagnostic `STL2STEP_DIAG_REJECTS=1 --diag-revert-cause`:
`counted-not-reverted usedRefit=true cyls=0 planCyl=36 planPl=1424`). An attribution keyed on that
counter sends the next session after a revert that never happened.

So `attribution.engine_analytic_loss_note` keys on **plan versus built**, which is always present,
and flags the counter when it contradicts `smoothRevertedTrue`:

```
ENGINE_ANALYTIC_LOSS [AC-B2/engine] cause=analytic-intersection-empty(x43)
  detected cylinders=36 fillets=126 -> built cylinders=0 fillets=0 (lost 162)
  (revertedComponents=1 is NOT a revert: revertedTrue=0) warnings=47
```

It costs nothing and changes no decision. **The loss is not reachable from Python**: the analytic
intersections between adjacent regions return `IntAna_Empty`/`IntAna_Same`, so the boundary chains
stay raw mesh polylines and the analytic shell cannot close
(`refit_build.cpp` `intersectSurfaces`/`pickIntAna`, ~1105-1200, bail at 725). By the time Python
reads the STEP the analytic faces were never written. Out of scope here, named so it is not
re-derived; the C++ side is being handled separately.

## 3c. What per-feature salvage would take (fix spot #2) — evaluated, not implemented

See §6 below: on the measured evidence it is not an operation `feature.py` can perform.

## 4. Instrument

`scripts/agent_loop_bench.py`, two arms from this one worktree (`MESH2STEP_LOOP=0` vs `1`),
sharing one engine STEP per part, scored by `scripts/patch_representation.py:represent`
(centroid sampling, analytic quadrics only) with the ISO-10303 text census as an independent
witness. A part whose feature pass qualifies nothing delivers the ENGINE STEP, as the service
does, so every number is the score of the file a user would download.

**It is not the live service.** The webapp adds weld/fix, the force-sew retry and the edgebuild
path, so these absolute numbers are NOT comparable with `mechparts-baseline.tsv`; only arm
against arm is.

## 5. Results

Two arms, `MESH2STEP_LOOP=0` vs `1`, from this worktree, 2026-09-21, on `~/corpora/mechparts`
plus the hotend upload. Per-part table: `docs/agent-loop-results.txt`. Where the loop took no
action the two arms execute the same instructions, so one run serves both columns; every part
where it acted was run twice.

```
36 of 39 mechparts + hotend measured
mesh cylinder patches on an analytic curved face:  891 -> 908  of 1184
parts better: 1        parts worse: 0
FAILURES (not missing data): parts 12, 30, 39 -- the ENGINE exceeded the 3600 s cap under the
  five-way contention of this sweep itself. Arm-independent: the same binary runs in both arms
  and the loop never executes. They are excluded from the totals above and counted here.
```

**The whole movement is one part.**

| part | patches | off | on | what happened |
|---|---|---|---|---|
| **19** | 17 | **0** | **17** | `extrude-z` -- 1 solid, valid, dv -0.217%, p95 0.018 vs a 2.30 limit -- was refused at radius support 0.21. The mesh backs 42 of its 42 cylindrical faces at their own locations. Accepted. 42 `CYLINDRICAL_SURFACE` in the delivered file. Runtime 109.7 s -> 110.2 s |
| 4 | 28 | 0 | 0 | the denser `stepped` re-run PASSES the shape gate and the radius test and is refused by the loop's own backing rule: 46 cylinders, 7 backed, 4 of 28 patches. Cost 51 s -> 194 s for nothing. See §5.3 |
| 16 | 8 | 0 | 0 | no candidate is both sound and honest: `extrude-z` misses `dv` by 1.170% against 1.0% and carries 2 of 8 patches anyway; `stepped` builds 148 cylinders the mesh backs 14 of |
| 6 | 52 | 14 | 14 | `stepped` is ACCEPTED outright, so there is no rejection for a loop to react to. The 38 missing patches are a builder gap |
| 33 | 121 | 81 | 81 | same: two candidates accepted outright |
| hotend | 52 | 0 | 0 | no candidate within reach: `stepped` models a quarter of the volume (dv -72%, repaired to one solid and still -75%), `turned` +433%, `block` +39.5%. Front: builders, and the engine (§3b) |

**5.1 Runtime.** Unchanged everywhere the loop does not act (identical to the second on 26 of 28
parts). The backing second opinion costs 0.15-0.8 s. The refine costs a full builder re-run:
+143 s on part 4, +6 s on the hotend, and it bought nothing on either.

**5.2 Two-sided (guideline 0.3.1, 5.4).** The one part that changed ships 42 cylindrical faces
for 17 mesh patches, and the mesh backs **42 of 42** at their own axis, radius and extent. No
part ships a face the mesh does not carry that it did not ship before. The backing instrument
was validated against five cases whose answer is known independently before it judged anything
(guideline 5.1):

| case | radius support | backing | truth |
|---|---|---|---|
| mechparts/19 `extrude-z` | 0.21 (refuse) | **1.00** | 17/17 patches represented -- refusing it was the defect |
| mechparts/19 `stepped` | 0.01 | 0.13 | 94 cylinders, 8/17 -- confabulation |
| mechparts/16 `stepped` | 0.05 | 0.09 | 148 cylinders, 6/8 -- confabulation |
| L09_valve_body `stepped` | 0.19 | 0.16 | the canonical 15-real-plus-65-invented case -- still refused |
| L04_puck `extrude-z` | 0.00 (`AC-B5`) | 1.00 | the blind-spot case guideline 4.B.5 says should be accepted |

**5.3 The repair ladder measured zero.** `largest_solid` fired on `L08_angle_bracket` (4 solids,
18 cylinders) and produced a 12-face solid with 2 cylinders still 238% out on volume -- the
cylinders were in the debris, not in the big solid -- and on the hotend, where it made one solid
out of two and changed no verdict. `sew_fix` never fired: no candidate in the corpus failed
`valid` or `free_edges` alone. The refine fired twice on mechparts and won nothing; its only win
is `clamp_half_a` (cadbench: 0/9 -> 7/9 patches, `dist_p95` 0.443 -> 0.108, 22 cylinders), and a
cadbench win is not a win (guideline 5.5.2).

**5.4 Which front each number belongs to.** Parts 19, 4, 16 are `feature.py` (candidate gate).
Parts 6 and 33 are the builders. The hotend is the engine (§3b) plus the builders, and nothing in
this branch can move it.

## 6. Per-feature salvage (fix spot #2): not reachable from `feature.py`

The brief's strategic prize is keeping a rejected build's recovered faces and merging them into
the winner. The measurements say it is not an operation this module can perform.

* **Into the engine's solid** -- the carrier guideline 4.B.2 names -- means replacing a fan of
  planar facets with one analytic face and rewiring its neighbours' edges. That is exactly
  `rebuild.rebuild_cylinders`, driven by a located band, and that path is fix spot #1, recorded
  as producing `valid=False` alone and together. Salvage inherits an unsolved problem.
* **Into another candidate's solid** means a boolean, which means re-cutting the feature rather
  than transplanting a face -- that is what `autoblock2` already does, so the work is a better
  feature list for a builder, not a merge in `feature.py`.
* And the case that motivates it does not survive contact: on mechparts/16 the build holding the
  cylinders (`stepped`, 148 of them, backed 14) is the one that must not ship, and the sound
  carrier (`extrude-z`) has 2 of 8 patches. Grafting 14 backed faces onto it would be the one
  honest version, and it needs the face-swap machinery above.

**Verdict: blocked on fix spot #1, not on this loop.**

## 7. Verdict

Ship the attribution and the second opinion. Do not ship the repair ladder.

* **IP4 attribution** closes an open non-conformance (guideline 9, "Partial: exists in
  diagnostics, not in `feature.reconstruct`"), costs nothing, and produced every finding above.
  It is what turned "part 19 declines" into "part 19 is refused by one clause on a build that is
  right".
* **The backing second opinion** is the only mechanism that moved the product characteristic:
  +17 patches on a named user part, 0 worse, no runtime cost, and it is harsher than the test it
  supplements on all four confabulation cases. It also closes `AC-B5` (`L04_puck`).
* **The repair ladder and the refine** measure 0 better / 0 worse on mechparts and cost up to
  +143 s on a single part. By guideline 5.5.5 that does not ship: risk surface with no return.
  Keep them on this branch with this measurement recorded.

Not verified: G6 (live). These numbers come from the feature pass driven directly, not through
the webapp, which adds weld/fix, the force-sew retry and edgebuild -- which is why parts 1, 2, 3,
5, 22 and 27 score lower here than in `mechparts-baseline.tsv` while 6, 9, 11, 23, 33 and 37
match it exactly. Part 19 ships faceted through the WHOLE live pipeline today, so its gain is new
to the product, but it must be confirmed on a service instance before anyone believes it.
