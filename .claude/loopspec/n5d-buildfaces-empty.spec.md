# n5d — two culprit faces discard a whole component's rebuild

> **CLAIM REWRITTEN 2026-09-06 from the actual site.** Earlier framings ("one unbuildable
> region empties the component", "per-region rejection instead of all-or-nothing") are
> WRONG and are kept below only as superseded record.

**Status: SYNTHESIS. No engine code until the predictions below have results.**
Subject: the models whose components are reverted with cause `buildFaces-empty` and which
emit NO construction warning at all — the cleanest signal in the corpus.

## 0. WHY THIS IS THE TARGET

Diagnosed cause distribution (fork's `--diag-revert-cause`, original budget, all 57 models):
**18 actual reverts — `buildFaces-empty` 15 (83.3 %), `budget` 3 (16.7 %)**, plus 2
components counted as reverted that were not reverted at all. n5a was refuted on the budget
minority, twice: by outcome (a -2512 mm3 solid) and by mechanism (in all 3 budget cases the
actual volume change exceeds the regions' OWN prediction by 2.4x-56x, so the budget is a
plan-vs-outcome agreement check and those rebuilds were simply wrong).
`buildFaces` returning empty is not a budget problem and never was — the analytic faces are
never built, so there is nothing for any budget to judge.

## 1. CLAIM (from the exit site, measured — supersedes everything below)

**The regions are accepted, the faces are built, and the component is discarded anyway
because the assembled SHELL is invalid and the cascade ladder runs out of moves.**

Exit site `refit_build.cpp:4571`, condition verbatim:

```cpp
// RULE 1.4: empty culprit set + invalid shell => escalate, never ship.
CascadePlan plan = cascadeLadderPlan(cascadeSt, culprits, rs, exploded, false);
if (applyCascadePlan(plan)) { recoverPass++; goto try_rebuild; }
if (plan.hostR2 || cascadeSt.u2Done || !shValid) {
    restoreShared();
    out.clear();
    return false;                      // <-- 4571
}
```

Values measured at that line:

| model | regions | rejects | faces built | `plan.hostR2` | `cascadeSt.u2Done` | `!shValid` | culprits |
|---|---|---|---|---|---|---|---|
| `L06_adapter_plate` | 20 | `None=20` | **20** | 1 | 1 | 1 | **2** |
| `L08_cable_clamp` | 9 | `None=9` | **9** | 1 | 1 | 1 | **2** |

**Two culprit faces cost 20 built faces and 14 truth cylinders on one model, and 9 faces on
the other.** The all-or-nothing is real but lives at the SHELL level, not the region level:
`collectShellCulprits` already names the offending faces, and the ladder discards the whole
component rather than shipping an invalid shell (RULE 1.4).

**The fallback that follows from this site** — keep the faces that are not culprits, revert
only the culprit faces to facets, re-assemble — is the same "keep them faceted, build the
rest" idea, but applied to the culprit set that the engine already computes, NOT to rejected
regions (of which there are none).

**P19 answered:** offending regions = **0**; offending shell faces = **2 of 20** and
**2 of 9**. The "<= 10 % offending" prediction holds at the shell level (10 % and 22 %),
and the recovery ceiling is 90 % and 78 % of built faces respectively.

---

## 1b. SUPERSEDED: the earlier claim from the source of `buildFaces` (`refit_build.cpp:3633`)

**`buildFaces` is all-or-nothing per component, and every one of its failure exits is
silent.** It returns `false` with `out` empty at four places, none of which calls `warn()`:

| exit | line (fork @ 7cf77a2) | behaviour |
|---|---|---|
| degenerate input (`mv.nTri == 0`, `verts.size() < mv.nVtx`) | 3637–3638 | silent |
| **`regionSetConsistent()` false** | 3639–3645 | marks **EVERY** region `Reject::ChainUnstable`, `BuiltAs::NotBuilt`, returns false |
| `built.empty()` (two sites) | ~4253 (`out.clear()`), ~4277 | silent |
| **J6 heal fallback** `j6UncollapsePass > 0` | ~4447 | `restoreShared(); out.clear(); return false;` — its own comment names a *"Revert-class (Body9/12/18/20)"* |

Consequence: **one unbuildable region empties the whole component.** `gripper_gear`
(75 truth cylinders) and `SpeedTestStructure` (246) lose everything to whatever single
region fails — candidate (i) confirmed IN SOURCE, not inferred from behaviour.

## 2. ARMS

- D1 *all-or-nothing*: there is no partial-build path. A component either yields every
  analytic face or none. The blast radius of one bad region is the entire component, which
  is why the loss is so large on the models with the most cylinders.
- D2 *silence is structural*: the failure exits predate the warning vocabulary. The
  IntAna/MakeEdge/seamed360 warnings come from INSIDE the build attempt; the four exits
  above bypass them. "No warnings" therefore never meant "no construction failure" — the
  error that invalidated P10's classification.
- D3 *the cause is already recorded, just not surfaced*: `regionSetConsistent` writes
  `r.reject = Reject::ChainUnstable` on every region before returning. A per-region cause
  needs no new computation — only an accessor. **This is the cheap diagnostic, and it comes
  after the attribute table below, not before.**
- D4 *the J6 heal is a distinct mechanism*: `j6UncollapsePass > 0` discards a component
  that was otherwise built, after a heal attempt. The corpus emits `J6: shell not closed`
  warnings, so this path is live here and is NOT the same failure as `regionSetConsistent`.

## 3. PREDICTIONS (fill `result:`, never edit the prediction)

- P17: the warning-free `buildFaces-empty` models are discriminated from the models that
  build by **`other_faces` > 0** in `truth.json` — cones/tori/spheres adjacent to the
  cylinders, which TrueForm has no primitive for. | check: tabulate the failing models
  against the building ones on `faces`, `cyl_faces`, `planar_faces`, `other_faces`,
  `circle_edges` — **no engine code** | result: **CONFIRMED 2026-09-06.**
  `other_faces > 0` in **11 of 15** `buildFaces-empty` models (73.3 %) against **2 of 38**
  that build cleanly (5.3 %) — a 14x difference in rate. Extremes: `L07_flanged_bushing`
  and `L08_T_bracket` are 32 of 34 faces "other"; `SpeedTestStructure` has 100. TrueForm
  has no primitive for cones/tori/spheres/splines, so these components contain regions it
  can never build — and D1 says one such region empties the whole component.
  **Not the whole story:** 4 failures have `other_faces = 0` (`L06_adapter_plate` 14 cyl,
  `L06_motor_mount` 5, `L08_rail_mount` 4, `L08_cable_clamp` 3) — pure plane+cylinder
  parts that still fail. See P18.
- P18: if P17 fails to discriminate, the discriminator is component COUNT or size, not face
  type: `buildFaces` empties on components above some triangle count where the J6 heal
  engages (`nTri >= 10000` is named in the source as skipping the heal for Body11). |
  check: same table plus triangle counts per model | result: **REFUTED AS STATED,
  INFORMATIVE 2026-09-06.** The J6 `nTri >= 10000` threshold is NOT the mechanism: no
  corpus model comes close (max 5964). But triangle count does separate sharply —
  every one of the 38 models that builds cleanly is **under 449 triangles** (median 154,
  range 12-448), while the 4 `other_faces=0` failures run 388-1620 (median 530) and the
  11 `other_faces>0` failures 438-5964 (median 1586).
  **Reframing:** the discriminator is not one attribute but COMPLEXITY. The corpus's
  successes are mostly trivial parts (median 7 faces, 1 cylinder); `buildFaces` succeeds on
  simple geometry and fails on anything substantial, with `other_faces` the sharpest single
  proxy. This also means the corpus's 38 "clean builds" are weak evidence of health.
- P19: `regionSetConsistent` is the exit taken, not the J6 path, for the warning-free
  models — because the J6 path emits `J6:` warnings and these models emit none. | check:
  surface `Reject::ChainUnstable` per region (D3) once P17/P18 have results | result: pending

## 4. GATES

Item 3 of the 2026-09-06 direction applies in full: **revert count is not a success
metric.** Every non-reverted component on all 57 + the 26 negatives must satisfy the
validity gate in `n4-cylinder-intent-gates.spec.md` §2b — closed shell, BRepCheck clean,
positive volume, `|V_step - V_mesh|` within the model's tessellation tolerance. n5a would
have failed this on its first model.
