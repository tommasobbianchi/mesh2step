# DELEGATION SPECIFICATION: which Phase-B gate rejects real holes (n5-seed-gates)

> **SUPERSEDED for the fix, 2026-09-05.** P6 answered this spec's question — the loss is a
> component-level revert, not a per-band gate — so the remedy is no longer "relax a gate".
> The work is split into three attributable specs, in this order:
> **`n5a-tessellation-aware-budget`** (the revert budget; smallest change, gain quantified
> by P7), **`n5b-coaxial-merge`** (blocked: P8 refuted as a check, needs n5a's output to
> re-test), **`n5c-mixed-boundary`** (the seamed360/cone case; P9 mechanism confirmed).
> This file is kept for P6's record and the fork arrangement. Do not implement from it.

**Status: PROPOSAL. Step 1 (P6) is a read-only measurement and may be run on approval.
No fork change may be made until P6 has a result.**

Supersedes the earlier `n5-seed-exclusion.spec.md`, which framed the problem as "stop the
engine seeding a designed prism". P3 showed that is only half of it, and the smaller half.

## 0a. CORRECTIONS TO THIS FILE'S OWN RECORD (2026-09-06)

**The revert site cited below (`stl2step.cpp:1063`) is WRONG.** That line is the volume
**WARNING** budget. The per-component revert is the `ok` flag at **~`stl2step.cpp:637`**,
where FOUR independent failures collapse into one boolean: `refit::buildFaces()` returning
empty, shell-not-closed, BRepCheck invalid, and the volume budget. That fusion is arm A7,
and it is now separable with the fork's `--diag-revert-cause`.

**A fifth conflation lives in the COUNT, not the flag.** `smoothRevertedComponents` also
increments for components whose rebuild SUCCEEDED and was adopted (`usedRefit == true`) but
contributed no surviving cylindrical face. Measured: `sample_0024` and `sample_0037` report
`counted-not-reverted usedRefit=true cyls=0 planCyl=1`. Neither was reverted. **Any figure
of the form "N reverts" in earlier notes includes non-reverts.**

**n5a (tessellation-aware budget) is REFUTED** — implemented, byte-parity verified, measured:

| model | truth cylinders | n5a OFF | n5a ON |
|---|---|---|---|
| `L04_soap_bar` | 12 | rev=1, step vol 4102.934 (= mesh) | rev=0, cyl=12, step vol **-2512.010** |
| `L10_tool_holder_recon` | **0** | rev=1, step vol 2.497 | rev=0, **cyl=1**, false rebuild |

The revert budget is load-bearing: widening it produced a NEGATIVE-volume solid. The work
moves to `n5d-buildfaces-empty.spec.md`; `P7` is queued behind the validity gate (§2b of
the n4 spec) and P16.

## 0. WHY THIS EXISTS — P3 rewrote the question

P3 predicted that no circle `canonize` finds on the corpus has < 72 segments. Measured:
**all 157 have 24–59 segments**, θ = 6.1°–15°. Not one is ≥ 72.

Those bands are INSIDE the Phase-B seed band `[thetaCylLoDeg 5.0, thetaCylHiDeg 60.0]`
(`refit.hpp:69-70`). So the engine seeded them and then **rejected** them, while it
**accepts** a designed 8-gon at 45° (P0/P1, ratio 1.110721 confirmed to 6 decimals).

The engine is not failing to look at these bands. It is looking and saying no. The
symmetric defect is therefore:

| case | θ | engine | correct |
|---|---|---|---|
| designed 8-gon prism, r=20 | 45° | **accepted** → +11.07 % invented | reject |
| real tessellated hole, corpus | 6.1°–15° | **rejected** → left faceted | accept |

Fixing only the first (the old n5) would still leave every real hole on the floor.

## 1. STEP ONE — P6, read-only, no instrumentation

- **P6:** the corpus's real holes are lost to a **component-level revert**, not to a
  per-band gate. That is, `smoothRevertedComponents > 0` on the affected models and the
  engine emits its "analytic rebuild reverted on one component — kept faceted" warning;
  the per-band gates G1–G5 pass. | **Alternative** if reverts are 0: a per-band gate,
  most likely **G5 band-continuity** (`spanDeg >= 300` with `nSides >= 6`, else
  `spanDeg >= 40` with `nBands >= 4`, `refit_grow.cpp:979-988`) or **G3** residual
  window `[0.35·delta, 2.00·delta]` (`refit_internal.hpp:85-86`), which is skipped
  entirely when `delta <= epsMesh` and `epsMesh = max(weldTol, 1e-4·diag, 1e-3)`.
  | result: **CONFIRMED 2026-09-05.** All three models revert:
  `07_all_four_types_truth` smoothCylinders=1 **reverted=2**; `L06_adapter_plate`
  smoothCylinders=0 **reverted=1**, step volume 28564.118610 vs mesh 28564.118611 —
  identical to 9 decimals, i.e. the rebuild was computed and thrown away;
  `L04_cyl_bottom_chamf` smoothCylinders=0 **reverted=1**, 7580.157371 vs 7580.157368.
  All three carry `smooth: analytic rebuild reverted on one component -- kept faceted`.
  It is the component revert, not a per-band gate — no instrumentation was needed.
  **Second mechanism seen alongside it** (not predicted, recorded here): the first model
  emits ~80 `smooth: IntAna cyl|cyl empty/same — keeping mesh polyline` and 6
  `smooth: analytic MakeEdge failed` warnings, and the third emits
  `seamed360: BRepCheck invalid on seamed face` with `J6: shell not closed`. Analytic
  EDGE construction is failing independently of the revert, and probably feeds it.

**Source synthesis behind P6.** Walking `commitCylinder` for a corpus hole (r ≈ 2.5 mm,
32 sides, θ = 11.25°) none of the per-band gates obviously bites: G4 needs
`2·epsPlane < radius < 2·diag` and `epsPlane = max(epsMesh, sewTol, 0.02) ≥ 0.02`, so a
0.95 mm radius still clears it; G5's closed branch needs span ≥ 300° and `nSides ≥ 6`,
and a through-hole spans 360°; G3's centroid residual for an inscribed polygon is
`R(1−cos(π/n)) = delta` exactly, i.e. ratio 1.0, inside `[0.35, 2.00]`. Everything passes
on paper — yet the holes arrive as polylines. The remaining mechanism that can discard a
whole component's worth of passing bands at once is the volume guard at
`stl2step.cpp:1063`, `budget = max(1e-4·refVol, 3·dVolPredAbs)`, whose revert warning has
already been observed in this project. Hence P6.

- **One-command check (three models, no code change, no instrumentation):**

```bash
for m in 07_all_four_types_truth L06_adapter_plate L04_cyl_bottom_chamf; do
  STL2STEP_SEGMENT_SUMMARY=1 ~/.local/share/mesh2step-native/run.sh \
    /tmp/awk/cadbench/${m}_normal.stl -o /tmp/n5_${m}.step --engine trueform 2>&1 \
  | grep -E 'RESULT|revert|SEGMENT' | tail -5
done
```

  Read from each `RESULT`: `smoothCylinders`, `smoothRevertedComponents`, `warnings`.
  Then `find_circles` on each output and compare its count against the model's
  `cyl_faces` in `/tmp/awk/cadbench/truth.json`.
  - reverts > 0 → **P6 confirmed**: the fix is the volume guard's budget, not a gate.
  - reverts == 0 and cylinders < truth → **P6 refuted**: it is a per-band gate, and the
    next step is the minimum instrumentation to print `gateName(ev.failGate)` per
    rejected band (`refit_grow.cpp:788` already has the function) — in the FORK only.

## 2. STEP TWO — the minimal fork change (only after P6 has a result)

Shape depends on P6 and must not be chosen before it. Both candidates keep the default
byte-identical and put the policy in the caller:

- if **P6 confirmed**: expose the revert budget, or make the revert per-band rather than
  per-component, so one bad band cannot discard a component of good ones.
- if **P6 refuted**: relax the identified gate for bands that pass the tessellation
  fingerprint, and/or add `--cyl-seed-max-turn <deg>` so a designed prism above the
  model's own fingerprint is never seeded.

## 3. FORK ARRANGEMENT (recorded from the user, 2026-09-05)

Separate checkout of `stl2step` at **7cf77a2** — the commit `refs/stl2step` is on, verified
— with its own build directory. `MESH2STEP_NATIVE` is pointed at that build **only for the
A/B**. `refs/` and the frozen binary at `~/.local/share/mesh2step-native/` stay untouched.

**Not yet created on disk**: no such checkout exists (`~/projects/stl2step*` is empty).
Creating it is the first action of step two, not of step one — P6 needs no build.

## 4. GATES for any fork change

- [ ] default path byte-identical to the frozen engine on all 57 corpus models;
- [ ] the 8-gon archetype keeps its facets (volume == mesh volume to 1e-6, `smoothCylinders` = 0);
- [ ] a 40-facet cylinder (θ = 9°, inside the corpus's real range) is STILL rebuilt;
- [ ] corpus recall >= baseline on every model, strictly better on >= 1;
- [ ] zero false rebuilds (volume moved away from B-Rep truth);
- [ ] **the new designed-polygon negatives (§5) are in the corpus and none is rebuilt.**

## 5. PREREQUISITE — the corpus has no negative class

Measured in n4: of 52 candidate bands with B-Rep ground truth, **all are cylinders**. The
corpus cannot fail a prism test because it contains no prisms. Until real designed
polygons are in it, no threshold here may be called validated, and no learned gate can be
trained at all.

Wanted: hex standoffs and spacers, nuts, octagonal bosses — KiCad's 3D model library is
the nearest real source; ABC if more are needed. Each needs the same treatment as the
existing 57: a B-Rep STEP as truth, tessellated at recorded deflections.
