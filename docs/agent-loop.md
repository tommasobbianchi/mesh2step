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

<!-- RESULTS -->
