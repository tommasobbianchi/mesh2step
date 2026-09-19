# Acilindria — physiopathologia

*A clinical description of the failure to form cylinders and planes in mesh2step.*

Acilindria: the absence, in the delivered STEP, of the cylindrical surfaces the part possesses.
The patient presents with a valid solid whose holes, bores and bosses are triangle fans. It is
not one disease. It is a syndrome with at least nine distinct aetiologies, each arising at a
different point in a pipeline that is otherwise working as designed, and each with its own
treatment. Treating the wrong one is how a session spends a day and moves nothing.

Written 2026-09-19 against `main` @ `c45d11d`. Every number below is measured, and the measuring
instrument is named so it can be re-run. Where a claim is an inference and not a measurement, it
says so.

---

## 1. Physiology — how a cylinder is supposed to form

A cylinder in the output is not carried through the pipeline. It is **lost at the door and then
reconstructed from evidence**, three times over, by three independent organs. Understanding that
the input contains *no cylinders at all* is the whole of the physiology.

### 1.0 The lesion is congenital: the mesh has no curved surfaces

An STL is triangles. A Ø7 bore is a ring of flat strips. Nothing in the file says "cylinder" —
the radius, the axis and the very fact of curvature must be **inferred from the arrangement of
flat facets**. Every organ below is an inference engine, and every pathology below is an
inference that failed. There is no transport failure to look for, because there is nothing to
transport.

### 1.1 First organ — the engine's seed band (`trueform`, native v1.8.1)

Adjacent facets whose normals differ by less than the smoothing angle are grouped into a *seed
band*, and a band that closes on an axis becomes an analytic cylindrical face. This is the
cheapest and by far the most productive organ: **98 of 109 cylinder-bearing corpus models are
carried by the engine and the feature pass together, and the engine alone fully recovers models
like `L06_hex_flange` (7/7) and `L10_nut_housing` (5/5)**.

Its competence is set by the angular threshold. A 96-sided cylinder puts 3.75° between facets,
under the 5° seed band, and is recognised. Refine the tessellation and each facet pair gets
*closer*, so the band holds. Coarsen it and the band breaks — which is why decimation is a
cylinder-destroying operation and not a neutral one.

### 1.2 Second organ — rim canonisation and band rebuild (`canonize`, `rebuild`, `intent`)

What the engine emitted as flat strips still carries its *rims*: the closed polylines where the
wall meets the end faces. `canonize.find_circles` fits circles to those polylines.
`rebuild.find_bands` pairs **two rims of equal radius on a common axis**, verifies that the faces
between them form a continuous wall (coaxiality is necessary and nowhere near sufficient — two
holes through opposite walls of a box are perfectly coaxial with 38 mm of air between them), and
emits a `CylinderBand`. `rebuild_cylinders` then drops the strips and builds one seamed 360° face,
rewiring each neighbour's chain of rim chords onto that face's own circular edge so the edge is
shared by construction and sewing has nothing to bridge.

Before any geometry is touched, `intent.classify` asks a question the rest of the pipeline cannot:
**was this band tessellated from a curve, or designed flat?** A tessellator applies one chord
tolerance to the whole model, so the sagitta `s = R(1 − cos(π/sides))` that a band realises must
agree with every other band's. Genuine cylinders spread 1.0×–3.24× the model tolerance over the
57-model ground-truth corpus; a designed 24-gon measures **106×**. The threshold is 8.0, sitting
2.5× above every real band observed and an order of magnitude below the designed-polygon
population. Ambiguity resolves to *warned*, never *rebuilt* — a wrong rebuild is worse than none.

### 1.3 Third organ — feature reconstruction (`feature.py`)

Seven builders (`extrude-x/y/z`, `stepped`, `turned-envelope`, `turned`, `block`) each attempt to
rebuild the part from its features and write a complete candidate solid. A candidate replaces the
engine's output only if **all** hold: one solid, `BRepCheck`-valid, zero free edges, surface within
`MAX_DIST_P95_REL` (0.5% of the diagonal) of the mesh, volume within `MAX_DV_PCT`, more cylinders
than the engine built, and **`MIN_SUPPORT` = 0.35 of its cylinders backed by radii the mesh itself
shows** (`quads.classify`: paired triangles → quads → normal lines meeting on an axis).

That last clause is the immune system. Slicing a cone, a sphere or a blend invents staircases of
cylinders; those surfaces carry no quad cylinders, so the invented faces are unsupported. Every
build that invented cylinders measured ≤23.5% support; 28 of 29 verified mechparts builds measured
≥48%.

### 1.4 Healthy function, measured

`scripts/cylinder_coverage.py`, 109 cylinder-bearing cadbench models, CAD preset arm
(`trueform` + `feature`), scoring the STEP a user actually downloads:

```
cylinders recovered   363/706 = 51.4% micro · 93.4% macro
models fully recovered 100 of 109

backend=feature   98 models   96 full   0 zero   328/334 = 98.2%
backend=native    11 models    4 full   5 zero    35/372 =  9.4%
```

**Read that table before theorising about anything.** Where the feature organ functions the
promise is met; the entire disease burden is the eleven parts where it declines and the patient
is handed the faceted engine output instead.

---

## 2. Aetiology — the causes, by the organ that fails

### A. Pre-hepatic: the evidence is destroyed before any organ sees it

**A1 — Decimation.** Reducing triangles widens the angle between facets. Past the seed band the
cylinder ceases to exist as evidence and no later organ can recover it. The UI sets `keep=50%`
for the user on models over 20k triangles (`app.js:443`), so this is *iatrogenic*: the most common
cause of acilindria may be the treatment for slowness. `bd projects-qqf` (two-step flow) is the
consent form.

**A2 — Coarse tessellation at export.** Same mechanism, earlier. The part arrives already
acylindric and nothing downstream is at fault.

**A3 — Designed prisms.** Not a disease. A 24-gon is *meant* to be flat, `intent` correctly warns,
and a "missing cylinder" here is a healthy refusal. Distinguishing A3 from A1 is the sagitta ratio,
and it is the one differential the pipeline already makes rigorously.

### B. Hepatic: the organ runs and produces nothing usable

**B1 — Rim amnesia (the dominant lesion of the second organ).** Measured on `L09_valve_body`,
21 CAD cylinders: `find_circles` recovers **2** rims, of different radii, so `find_bands` yields
**0** bands and `rebuild_cylinders` returns `ok=False, 'no cylinder bands found'` — while
`quads.classify`, looking at the *mesh*, finds **14** cylinder patches. The organ is starved of
input, not defective. **The mesh knows 14; the STEP knows 2.** Confirmed as the blocking lesion
on `L08_angle_bracket` and `clamp_half_a` too (`rb_ok=no` on all three).

**B2 — Whole-build rejection (the dominant lesion of the third organ).** A candidate that
recovers the cylinders is discarded entire because the *solid* around them is wrong:
`L08_angle_bracket`'s `turned` and `block` builders each recover **4 of 4** cylinders and are
thrown away for `solids=4, dv=503%` and `solids=2, dv=69%`. The cylinders were found, then
discarded with the wreckage they came in.

**B3 — Near-miss on a shape threshold.** `clamp_half_a`'s `stepped` build recovers 6 of 11 and
fails on `dist_p95` 0.443 against a limit of 0.286 — nothing else. A rim 0.16 mm out costs the
patient every cylinder in the part.

**B4 — Correct immune rejection.** `L09_valve_body`'s `stepped` build now passes every shape
gate and is refused by `MIN_SUPPORT`: it recovers 15 real cylinders and **invents 65**. The gate
is right. This is not a threshold to relax — it is the case that proves acceptance must be
per-feature, because the only wrong answer here is *all or nothing*.

**B5 — Immune blind spot.** `L04_puck` is a literal puck. The quad detector finds **0** cylinders
in its mesh, so `support()` is 0.00 by construction and three builders that each recover its one
true cylinder are all refused. Absence of evidence is being treated as evidence of absence.
(Inference, not measurement: the likely mechanism is that a full-height single-cylinder patch
gives the classifier no second surface to disagree with.)

**B6 — Iatrogenic invention.** The opposite failure, and the reason B3–B5 must not be treated by
loosening. `SpeedTestStructure` ships **139 built cylinders of which 12 are real**. A relaxed gate
turns acilindria into confabulation, which is worse: the patient cannot see that the CAD is wrong.

### C. Post-hepatic: recovered and then lost

**C1 — A crashing candidate destroying accepted work.** `measure()` threw `Standard_NullObject`
on a builder that wrote a STEP with no transferable root, and `reconstruct()` let it escape,
killing the whole feature pass *including builds it had already accepted* —
`L10_idler_bracket`'s `stepped` had recovered 6 of 6. **Fixed in `c45d11d`**, with a regression
test verified to fail on the unfixed code. Cured, and named here because the class recurs: any
unguarded in-process OCCT call in a candidate loop is the same lesion.

**C2 — Selection by the wrong criterion.** The surviving build used to be chosen by closest
volume, making volume the arbiter of a shape question. Changed to select by cylinders the mesh
backs; measured effect on cadbench so far: **none** (0 better, 0 worse).

### D. Systemic: the measurement itself is diseased

Not a cause of acilindria, but the reason it went unnoticed, and the failure mode most likely to
waste the next session.

**D1 — Denominators that flatter.** Every pre-existing gate had the *build* as denominator —
`support` asks what share of what we built is real — so recovering one hole in twelve and getting
it right scores perfectly. Coverage inverts it: of the cylinders the part HAS, how many returned.

**D2 — Deduplicated truth.** `truth.json`'s `cyl_radii` is `sorted(set(...))`
(`build_corpus.py:158`). `SpeedTestStructure` reads as 4 cylinders instead of 285. Use
`cyl_radii_hist`. This cost one full aborted measurement run.

**D3 — The mesh is not a denominator.** `mesh_cylinder_radii` finds **375** of the corpus's **706**
true cylinders (53%), and **7 of 285** on the worst part. Any per-conversion "coverage %" built on
it reads near-100% exactly where recovery is worst. On a user upload it is the only denominator
available, which is why per-conversion honesty means reporting *counts*, not a ratio.

**D4 — Radius matching counts noise.** A prior session established that the same physical feature
appears many times at radii differing in the fourth decimal (30 and 80 patches collapsing to 8 and
19 clusters), so radius-based coverage scores real geometry as missing. The metric that survives is
point-to-surface: `scripts/patch_representation.py`.

**D5 — The wrong corpus.** Every tuned constant was fitted to cadbench, which does not resemble
the user's machined parts. `n21` measured +1.07 CADScore on cadbench and removed **89%** of
recognised cylinder regions on `mechparts/11`. A cadbench A/B is not evidence.

---

## 3. Strategic fix spots — where to intervene, ranked

Ordered by measured burden, not by ease.

| # | Target | Site | Evidence | Status |
|---|---|---|---|---|
| **1** | **Seed the band search from the mesh** | `rebuild.bands_from_patches`, at the single `find_bands(merged)` call | B1: locates **14/14** where rims give 0 | Located; **application fails** (`valid=False` alone and together) — `feat/mesh-seeded-bands` @ `fec4584` |
| **2** | **Per-feature acceptance** | `feature.reconstruct` gate | B2, B4: builds recovering 4/4, 6/11, 15-of-21-real are discarded whole | Chosen route (user, 2026-09-19); depends on 1 |
| **3** | Snap seeded extents to rim chord chains | `bands_from_patches` extent + `_is_rim_chord` | The topology fails because a mesh-derived extent does not coincide with neighbour rim chords, which rim-derived bands get for free | Next attempt (attempt 1 spent) |
| **4** | Two-step decimate → confirm | `POST /api/decimate`, `app.js` | A1, iatrogenic | `bd projects-qqf` |
| **5** | Support when the mesh shows nothing | `feature.support` | B5 (`L04_puck`) | Open; narrow but undermines the gate's premise |
| **6** | Model→mesh distance | `feature.measure` | Would retire the volume gate honestly: `dist_p95` samples one direction only, so a solid enclosing the whole mesh scores 0.0 and volume is the only guard left | Open |
| **7** | Parts the builders cannot model | builders | `SpeedTestStructure` 285→12; untouched by 1–6 | Open, separate |

**Do not target:** `MAX_DV_PCT` and `MIN_SUPPORT` as a way of buying cylinders. They buy ~13
cylinders on two models and pay in B6.

---

## 4. The mind model

The clinical text above is for a human. This is the form I keep loaded.

**ACILINDRIA — five questions, in order. Never skip to the fix.**

1. **Was there ever evidence?** Facets too coarse (A1/A2) or a designed prism (A3) → the part is
   not sick, or the sickness is upstream. *Check the tessellation before the code.*
2. **Which organ declined?** `stats.backend`: `feature` → 98.2% recovered; `native` → 9.4%. One
   field separates a healthy part from a diseased one. *Always read it first.*
3. **Was the cylinder found and then thrown away, or never found?**
   - Found, discarded with the build → B2/B3/B4 → **per-feature acceptance**.
   - Never found by the STEP-side search but present in the mesh → B1 → **seed from the mesh**.
   - Found by nothing → builders (7), or genuinely absent.
   *`find_circles` count vs `quads.classify` count is the whole differential, and it is two calls.*
4. **Would the fix invent?** If the change lets through faces the mesh does not back, it converts
   acilindria into confabulation (B6). Refuse it.
5. **Measured how?** Truth = `cyl_radii_hist`, never `cyl_radii` (D2). Denominator = the part,
   never the build (D1) and never the mesh detector (D3). Corpus = `mechparts` before belief,
   cadbench for regression only (D5). Metric on parts without truth =
   `scripts/patch_representation.py`, sampling **centroids** not vertices.

**Three standing facts that override intuition:**
- The input contains no cylinders. Everything is inference; there is no transport bug to find.
- The gates are mostly *right*. The pipeline's problem is that it decides per build what it should
  decide per feature. Loosening is the wrong axis; granularity is the right one.
- A cadbench win is not a win.

**The promise being measured against** (`webapp/static/app.js:403`): *"Finds the real shapes —
cylinders, holes, rounded edges — and rebuilds them as CAD geometry. Slower on detailed models,
and worth it."*

---

Home issue: `bd projects-3md`. Baseline: `coverage-baseline.tsv`. Instruments:
`scripts/cylinder_coverage.py` (truth corpus), `scripts/patch_representation.py` (any part).
