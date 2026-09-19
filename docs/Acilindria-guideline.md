# Acilindria — treatment guideline and control standard

*Companion to `Acilindria-physiopathologia.md`, which diagnoses. This one treats, and fixes the
process so the same defect cannot return unnoticed.*

**Status:** normative for all cylinder-recovery work in mesh2step. Issued 2026-09-19 against
`main` @ `9ca4f47`. Home issue `bd projects-3md`.

A physician treats the patient in front of them. A quality engineer asks why the defect reached
the patient at all, and changes the process so the next one is caught at the station that made it.
This document is the second discipline applied to the first's findings. Every clause is either a
**control** (prevents or detects), a **treatment** (corrects), or a **rule of evidence** (decides
whether a treatment worked). Clauses are numbered so a review can cite them.

---

## 0. Scope and principles

**0.0 Two clocks, and nothing here slows a conversion.** This document governs two different
activities and they must not be confused.

| | **Runtime controls** (§2) | **Engineering protocol** (§3, §5, §6) |
|---|---|---|
| Who runs it | the service, on every conversion | a person or agent investigating a defect, or validating a change |
| How often | per upload | once per investigation, or once per candidate change |
| Cost budget | **≤ 1 s added, and only cheap counters** (§2.3) | minutes to hours, off the hot path |
| If it is slow | it is out of process — cut it | expected |

**No user upload waits for a diagnosis.** §3's protocol is a bench procedure for whoever is
holding the defect; §5 and §6 apply to a proposed change before it merges. The only thing the
product does per conversion is record a handful of counters it is already most of the way to
having (§2.3).

**0.1 Scope.** Any change touching cylinder or plane recovery: the native engine's invocation,
`canonize`, `rebuild`, `intent`, `feature`, the builders in `tools/feature_recon`, decimation, or
the acceptance gates of any of them.

**0.2 The product characteristic under control.** Not volume, not face count, not CADScore:
**the count of the part's own cylinders that arrive as analytic faces in the delivered STEP.**
Everything else is a covariate.

**0.3 Three principles, in precedence order.**

1. **Absence beats confabulation.** A missing cylinder is visible to the user; an invented one is
   not. Any change is judged on *two* numbers — recovered ↑ and invented ↓ — and a change that
   raises both is a regression however good the first number looks (§5.4).
2. **Granularity before looseness.** The gates are mostly right. Where the pipeline fails it is
   deciding per *build* what it must decide per *feature*. Loosening a threshold to buy cylinders
   is prohibited without an explicit written decision by Tommaso (§4.B.4).
3. **The measurement is part of the product.** An unvalidated metric has caused more lost days
   here than any geometric bug. No metric judges a change until it has passed §5.1.

**0.4 Defect codes.** `AC-A1`…`AC-D5`, defined in `Acilindria-physiopathologia.md` §2 and
summarised in §1.2 below. Every non-conformance, issue note and commit message naming a cylinder
defect cites its code.

---

## 1. Definitions

**1.1 Terms.**

| Term | Meaning here |
|---|---|
| **Recovered** | A cylinder of the part matched one-to-one, greedily, largest first, by a cylindrical face of the delivered STEP within 0.5% radius (`feature.pair_radii`) |
| **Invented** | A cylindrical face in the delivered STEP that no cylinder of the part or patch of the mesh backs |
| **Represented** | A mesh cylinder patch whose own triangle centroids lie within 1% of the diagonal of an *analytic curved* face of the model (`scripts/patch_representation.py`) |
| **Declined** | The feature organ produced no qualifying build, so the engine's faceted output ships (`stats.backend == "native"`) |
| **Escape** | A defect that reached a user because no inspection point was looking for it |

**1.2 Defect taxonomy.**

| Code | Defect | Group |
|---|---|---|
| `AC-A1` | Evidence destroyed by decimation (iatrogenic) | Pre-analytic |
| `AC-A2` | Evidence never existed — coarse export tessellation | Pre-analytic |
| `AC-A3` | Designed prism correctly kept faceted — **not a defect** | Pre-analytic |
| `AC-B1` | Rim amnesia: STEP-side rim search starved, mesh has the evidence | Inference |
| `AC-B2` | Whole-build rejection of a build that recovered cylinders | Inference |
| `AC-B3` | Near-miss on a shape threshold | Inference |
| `AC-B4` | Correct immune rejection (recovers some, invents many) | Inference |
| `AC-B5` | Immune blind spot: support undefined, treated as failure | Inference |
| `AC-B6` | Confabulation: invented cylinders shipped | Inference |
| `AC-C1` | Recovered work destroyed by a later fault in the same pass | Post-recovery |
| `AC-C2` | Selection by the wrong criterion | Post-recovery |
| `AC-D1`–`D5` | Measurement-system defects (see §5) | Systemic |

---

## 2. Control plan — runtime

The inspection points, in pipeline order. These are **in the product** and run per conversion,
under the cost budget of §2.3. **Reaction plan** is what must happen when the criterion
fails — never "note it and continue".

| IP | Station | Characteristic | Instrument | Acceptance | Reaction |
|---|---|---|---|---|---|
| **IP0** | Upload | Facet angle adequate for the seed band | triangle count, bbox diagonal | advisory | Warn before, not after, a long conversion (§4.A.1) |
| **IP1** | Decimation | Evidence survives reduction | mesh cylinder patch count before vs after | **no patch lost** | Refuse silently-destructive presets; require user confirmation (`bd projects-qqf`) |
| **IP2** | Engine output | Cylinders the engine formed | `stats.smooth_cylinders` | record | If 0 and patches > 0 → suspect `AC-B1`, run §3 |
| **IP3** | Rim/band rebuild | Bands located vs patches present | `find_circles` count, `find_bands` count, `quads.classify` count | bands ≥ patches, else `AC-B1` | Seed from mesh (§4.B.1) |
| **IP4** | Feature acceptance | Which clause rejected each candidate | `feature` log line per candidate | every rejection attributable to one named clause | Classify as `AC-B2/B3/B4/B5`; never "it didn't qualify" |
| **IP5** | Delivered STEP | Cylinders built, patches the mesh shows, how many match | counters already in hand (§2.3) | record, no ratio (§5.2) | Counts in the result; a user upload has no truth to score against |
| **IP6** | Bench only | Recovered / invented / represented | `cylinder_coverage.py`, `patch_representation.py` | §6 gates | Non-conformance record (§8) — **never in the conversion path** |

**2.1 IP4 is mandatory and currently partial.** A rejection that cannot be attributed to a named
clause is itself a non-conformance: it makes the next session guess. The attribution logic exists
in the session diagnostic and belongs in `feature.reconstruct`'s log line.

**2.2 A timeout is a failure, not missing data.** Censoring is the commonest way a corpus lies: 74
of 351 logged conversions once sat at a cap, making every mean meaningless. A timed-out part is
reported as a failed part and counted in the denominator. Where a run is censored, report
quantiles and the censored count, never a mean.

**2.3 Runtime cost budget — measured, and the reason these controls are affordable.**
Every IP above is a counter the pipeline can afford; the expensive instruments are bench-only.

| Control | Cost | Basis |
|---|---|---|
| mesh cylinder patch count (`quads.classify`) | 0.03 s @2.8k tris · 0.35 s @14k · **0.82 s @62k** | measured 2026-09-19; roughly linear, so ~1.6 s at the 120k input cap |
| built cylinder count | free | the STEP is already read for the existing stats |
| rim count (`find_circles`) | ~0.27 s/MB, already size-capped at 25 MB | `CANONIZE_MAX_BYTES`, already in the product |
| per-candidate rejection clause (IP4) | free | the measurements already exist; only the log line is missing |
| **`patch_representation.py`** | **seconds to minutes per part** | BRepExtrema per sample point — **bench only, never runtime** |
| **`cylinder_coverage.py`** | whole-corpus runs | needs CAD truth, which a user upload does not have — **bench only** |

Against a pipeline whose median conversion is seconds and whose tail is minutes (351 logged runs
span 3.3 s to 900 s), ≤1.6 s of counting is inside the noise. **If a proposed control cannot be
stated in this table with a measured cost, it does not go in the runtime path.**

---

## 3. Diagnostic protocol — bench, not runtime

**Run by an engineer or agent holding a defect, once per investigation. NOT part of a conversion:
no upload ever waits for this.** Deterministic, ~10 minutes of bench time, run **before** writing
a fix. Output is a defect code.

```
STEP 1  Is there evidence?
        quads.classify(mesh) patch count == 0  →  AC-A1/A2 (or a genuinely flat part).
        intent.classify says sagitta > 8x model tolerance  →  AC-A3, healthy. STOP.

STEP 2  Which organ declined?
        stats.backend == "feature"  →  98.2% of cylinders recover here. Rare defect; go to STEP 4.
        stats.backend == "native"   →  9.4%. This is the diseased population. Continue.

STEP 3  Found and discarded, or never found?   (the whole differential, two calls)
        canonize.find_circles(step)  vs  quads.classify(mesh)
          mesh >> STEP                     →  AC-B1   treat per 4.B.1
          rebuild.find_bands == 0 with circles present  →  AC-B1 (pairing), treat per 4.B.1
        Re-run the candidate builders with per-clause attribution:
          a candidate recovered cylinders and failed on solids/free_edges/dv/dist
                                           →  AC-B2 or AC-B3   treat per 4.B.2
          a candidate passed shape and failed MIN_SUPPORT while inventing
                                           →  AC-B4   treat per 4.B.2, never by loosening
          support == 0.00 because the mesh detector found nothing
                                           →  AC-B5   treat per 4.B.5
        No candidate recovered anything    →  builder capability gap. Separate work item.

STEP 4  Did the delivered STEP invent?
        built cylinders vs recovered       →  AC-B6 if the gap is large. Highest severity.
```

**3.1 Record the code before writing code.** A change whose issue note does not name the defect
code it treats is out of process.

---

## 4. Treatment protocols

### Group A — pre-analytic. The evidence is destroyed before any organ sees it.

Prevention only. No downstream cleverness recovers a facet angle that was widened.

**4.A.1 — `AC-A1`, iatrogenic decimation.** The UI sets `keep=50%` for the user over 20k triangles.
Treatment is **informed consent, not silent reduction**: two-step flow (`bd projects-qqf`) —
decimate, show the reduced mesh and its integrity figures, convert only what the user approved.
**Control:** IP1 — report mesh cylinder patch count before and after reduction. A reduction that
loses patches is presented as a loss, in numbers, *before* the user waits.

**4.A.2 — `AC-A2`, coarse export.** Not our defect, but it is our diagnosis to make and our message
to write. Say "this mesh does not contain the curvature to rebuild; re-export at a finer chord
tolerance", and say it at upload (IP0), not after a 400-second wait.

**4.A.3 — `AC-A3`, designed prisms.** No treatment. Protect the existing refusal: `intent`'s
sagitta ratio separates real bands (1.0–3.24× model tolerance) from designed polygons (106×) with
a threshold at 8.0. **Any change that would rebuild a band at ratio > 8.0 is rejected outright.**

### Group B — inference. The organ runs and the cylinder does not arrive.

**4.B.1 — `AC-B1`, rim amnesia. Feed the organ from the side that knows.**
The band search reads rims from the STEP and needs two equal-radius coaxial ones; the mesh it was
made from still holds the evidence (`L09_valve_body`: STEP 2 circles → 0 bands; mesh 14 patches).
Treatment: seed `find_bands` from mesh patches (`rebuild.bands_from_patches`, branch
`feat/mesh-seeded-bands`). **Additive only** — seeding may add a band the rim search missed and
may never remove or alter one, and every seeded band passes the same `intent` check.
*Current state:* location works (14/14); application yields an invalid solid, alone and together.
Next intervention is §4.B.1.a.

**4.B.1.a — extent snapping.** A rim-derived band's extent coincides with the neighbouring faces'
rim chord chains by construction; a mesh-derived extent does not, which is the suspected cause of
the topology failing to close. Snap the seeded extent to the actual chord chains
(`rebuild._is_rim_chord` already tests exactly this predicate) before rebuilding.

**4.B.2 — `AC-B2`/`AC-B3`/`AC-B4`, whole-build rejection. Change the granularity, not the limit.**
The pipeline decides per build what it must decide per feature. A build recovering 4 of 4, or 6 of
11, or 15 real cylinders alongside 65 invented ones, must contribute **its provable cylinders** to
the engine's solid rather than being accepted or discarded entire. The engine's solid stays the
carrier — it is topologically sound — and each feature is admitted on its own evidence. This is
why §4.B.1 is a prerequisite: grafting needs a located band.

**4.B.3 — prohibited treatments.** Raising `MAX_DV_PCT` or lowering `MIN_SUPPORT` to buy cylinders.
Measured value: ~13 cylinders on two models. Measured cost: `AC-B6` on every part where a builder
over-slices. Requires Tommaso's explicit written decision, recorded in `bd projects-3md`.

**4.B.4 — permitted threshold work, and its evidence bar.** A threshold may change when the change
is *principled* rather than bought: e.g. volume was demoted from gate to bounded backstop because
Tommaso ruled on 2026-09-13 that volume is a diagnostic, not grounds to discard a closed valid
B-rep with recognised geometry. Even then it ships only under §5.5 — and the demotion measured
0 better / 0 worse on cadbench, so on that evidence it does not ship.

**4.B.5 — `AC-B5`, blind spot. Undefined is not failed.**
`support()` returns 0.00 when the mesh detector finds no cylinders at all, which refuses three
builders that each correctly recover `L04_puck`'s single cylinder. Treatment: where the detector
finds *nothing*, support is **undefined**, and an undefined support must fall through to a
different, positive test (e.g. point-to-surface representation of the built face against the mesh)
rather than being scored zero. **Constraint:** the zero-detection case is also how cones, spheres
and blends are caught, so the fallback test must be positive evidence, never an exemption.

**4.B.6 — `AC-B6`, confabulation. Containment first.**
Highest severity: the user cannot see that the CAD is wrong. On detection, the containment action
is to report the invented count in the result, not to silently ship. Any change raising invented
count is reverted before its recovery gain is discussed.

### Group C — post-recovery. The cylinder was found and then lost.

**4.C.1 — `AC-C1`, fault contagion.** An in-process OCCT call inside a candidate loop must not be
able to destroy already-accepted work. `feature.py`'s docstring promised this for the subprocess
builders and did not hold it for the in-process read of what they wrote; the throw destroyed a
build that had recovered 6 of 6. Fixed in `c45d11d`.
**Standing control:** every candidate loop wraps *both* the production and the evaluation of a
candidate; a candidate may cost itself and nothing else. Review any new loop against this clause.

**4.C.2 — `AC-C2`, selection criterion.** The survivor among qualifying builds is chosen on
recognised geometry (cylinders the mesh backs), never on volume proximity — volume must not
arbitrate a shape question. Ties break on volume.

### Group D — systemic. See §5; this is where the process defects live.

---

## 5. Rules of evidence — measurement system control

The clauses that decide whether a treatment worked. Violating one invalidates the result, however
good it looks.

**5.1 Gauge validation before use (MSA).** A metric may not judge a change until it has been run
on **at least two parts whose answer is known independently**, one positive and one negative, and
reproduced both. Worked example: `patch_representation.py` was validated on `L06_flange_plate`
(all 7 cylinders recovered → 8/8 represented) and `L09_valve_body` (faceted → 0/14) *before* being
pointed at anything unknown. That validation immediately exposed a sampling bug — vertices instead
of centroids scored the good part 2 of 8, because a hole's rim vertices lie on the flat face as
exactly as on the cylinder.

**5.2 Denominator discipline.**
- The denominator is **the part**, never the build (`AC-D1`: build-denominated metrics score
  1-of-12-done-right as perfect).
- Truth comes from `cyl_radii_hist`, **never** `cyl_radii` — deduplicated at `build_corpus.py:158`,
  which reads `SpeedTestStructure` as 4 cylinders instead of 285 (`AC-D2`).
- The mesh detector is **not** a truth denominator: 375 of 706 corpus cylinders, 7 of 285 on the
  worst part (`AC-D3`). It is legitimate only as a *lower-bound* input, and any figure derived from
  it carries that statement.

**5.3 Never score competing fits with the metric one of them was fitted to minimise.** This voided
two adjudications in a previous session in opposite directions. Use point-to-surface distance to
the model, or fit both candidates and compare each to the mesh.

**5.4 Two-sided reporting.** Every result reports recovered **and** invented. A table showing only
recovery is not a result (§0.3.1).

**5.5 Change validation protocol.** Before any cylinder-affecting change merges:

1. **Two arms, isolated.** Pre-change arm from a git worktree at the base commit, post-change arm
   from the candidate, each its own service on a port claimed from the majordomo pool. Never
   compare against a remembered number.
2. **`mechparts` before belief; cadbench for regression only.** `n21` measured +1.07 CADScore on
   cadbench and destroyed 89% of recognised cylinder regions on `mechparts/11` (`AC-D5`). Run the
   curved parts first: 11, 25, 23, 9, 22, 32, 20, 12.
3. **Named parts are acceptance tests.** Any part Tommaso has named is run body by body and
   reported by face type, on the **live** service, not only in the corpus.
4. **Per-part deltas, not just totals.** A total can hide one part collapsing while another gains.
5. **No movement, no merge.** A change measuring 0 better / 0 worse does not ship: it is risk
   surface with no return. It may be kept on a branch with its measurement recorded.
6. **Long runs under `watchjob`**, and a timeout is a failure (§2.2).

**5.6 Traceability of a number.** Any figure quoted in an issue, commit or report names the
instrument, the corpus, the arm and the date. A number without these is an opinion.

---

## 6. Release gates

A cylinder-affecting change may deploy only when all hold:

- **G1 — No regression:** no part recovers fewer cylinders than on the base arm (§5.5.4).
- **G2 — No new confabulation:** invented count does not rise on any part (§0.3.1).
- **G3 — Movement:** at least one part recovers more, or a named defect code is provably closed
  (a crash fix may close `AC-C1` with a regression test in place of a coverage gain — state which).
- **G4 — Suite:** the test suite shows no failure absent from the base arm; known failures are
  listed by name, not by count.
- **G5 — Evidence attached:** the defect code, both arms' figures, and the instrument, recorded in
  `bd projects-3md` before merge.
- **G6 — Live verification:** after deploy, drive the running service with a real part and report
  its backend and face types. A deployed version string is not a working conversion.

---

## 7. Escalation and stop rules

**7.1 Two failed attempts, then a second opinion.** An attempt is a fix written and shown to fail.
After the second failure on the same defect, hand to `/ask-kimi` with: the measured facts labelled
not-to-be-re-theorised, every attempt already reverted (one line each), every premise found false,
and file paths with a request for `file:line` citations. Attempts 3..N inherit the same wrong model
and fail in new clothes.

**7.2 Stop on contradiction.** If a measurement contradicts a documented finding, stop and resolve
the contradiction before building on either. The contradiction is the most valuable thing on the
table.

**7.3 Stop on an unvalidated gauge.** If a number cannot be traced per §5.6, it does not enter a
decision.

---

## 8. Records

**8.1 Per conversion** (runtime, honest counts only — no ratio against an unsound denominator):
cylinders built, mesh patches detected, matched, backend, per-candidate rejection clause.

**8.2 Per change:** defect code, both arms, instrument, per-part deltas, gate results, and the
decision — including a decision *not* to ship and why.

**8.3 Baselines are files, not memories:** `coverage-baseline.tsv` in the repo. A baseline held
only in a session is lost at compaction, and the corpus that was destroyed by a reboot in 2026
cost every gate its measuring stick.

---

## 9. Open non-conformances

| Code | Part(s) | State | Clause |
|---|---|---|---|
| `AC-B1` | `L09_valve_body`, `L08_angle_bracket`, `clamp_half_a` | Location solved (14/14), application invalid | §4.B.1.a |
| `AC-B2` | `L08_angle_bracket` (4/4 discarded), `clamp_half_a` (6/11) | Open — needs §4.B.1 first | §4.B.2 |
| `AC-B4` | `L09_valve_body` (15 real / 65 invented) | Open — per-feature only | §4.B.2 |
| `AC-B5` | `L04_puck` | Open | §4.B.5 |
| `AC-B6` | `SpeedTestStructure` (139 built / 12 real) | Open, highest severity | §4.B.6 |
| `AC-A1` | all uploads > 20k triangles | Open | §4.A.1, `bd projects-qqf` |
| `AC-C1` | `L10_idler_bracket` | **Closed** `c45d11d`, regression test in place | §4.C.1 |
| IP4 attribution | — | Partial: exists in diagnostics, not in `feature.reconstruct` | §2.1 |

---

**Companion documents:** `Acilindria-physiopathologia.md` (diagnosis), mind model in the project's
auto-memory (`project_acilindria_mind_model`). Instruments: `scripts/cylinder_coverage.py`,
`scripts/patch_representation.py`.
