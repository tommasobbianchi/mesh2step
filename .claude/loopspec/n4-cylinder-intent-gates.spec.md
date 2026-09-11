# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

## 0. SYNTHESIS (ai-intuition, 2026-09-05 — read this BEFORE §1; §1's order is subordinate to it)

**ONE claim.** Whether a facet band becomes a cylinder is decided by its per-facet angular
step θ against fixed constants — TrueForm's 5° Phase-B seed band in the C++, canonize's
20° turn / 0.35 CoV / 0.05 mm and rebuild's 0.5 mm in Python — and never against the
model's own tessellation tolerance. The decision is therefore split across two engines with
opposite biases at the 5° seam: coarse bands (θ > 5°) are always cylinders, fine bands
(θ ≤ 5°) are cylinders only if they pass Python's constants. Every misclassification in
classes (a)(b)(c) is a band whose θ sits on the wrong side of a constant.

**Arms.**
- A1 *route*: θ > 5° → C++ seed + G1–G4 → `Geom_CylindricalSurface` in the STEP; θ ≤ 5°
  (≥ 72 facets) → planar strips → `canonize`/`rebuild`. Consequence: a designed prism with
  θ > 5° is decided by the C++, and the STEP no longer contains its facets — **no
  post-processor can undo it**. Class (a) must be decided on the mesh, before or inside
  the native engine.
- A2 *producer* — **REWRITTEN 2026-09-05, refuted by P3**: the claim was that the only
  producer of lost circles is the 5° seed band, so every circle `canonize` finds has ≥ 72
  segments and turn-CoV ≈ 0 by construction, making 49/49 trivial. Measured over the
  corpus: all 157 circles have 24–59 segments (θ = 6.1°–15°) and NOT ONE has ≥ 72. Those
  bands are inside the seed band [5°, 60°], so the C++ did seed them and then REJECTED
  them at G1–G4; what reaches `canonize` is the engine's rejects, not its blind spot.
  49/49 was therefore not trivial, and the domain is coarse, not fine. Which gate rejects
  them is P6 in `n5-seed-gates.spec.md`.
- A3 *fingerprint*: one tessellator → one (linear deflection d, angular deflection α) pair
  for the whole model; every tessellated band satisfies s = R(1−cos(θ/2)) ≤ d and θ ≤ α
  with near-equality on one of them; a designed polygon violates both by a large factor.
  This is the route-selector both engines lack. `--smooth-tol` (default auto) is the only
  visible slot where the engine could consume it.
- A4 *topology, not uniformity* — **REWRITTEN 2026-09-05 at wire level, after P5**: the
  first formulation asked a FACE question ("a rim bounds exactly one planar cap") and P5
  refuted it: only 107 of 157 corpus rims are contained in a single face's vertex set, 50
  in none, and coplanar-merging first does not change the ratio. The question is a WIRE
  question. A hole rim is an INNER WIRE of the wall face (an outer wire bounds the face's
  material; a hole subtracts from it), and a fillet strip's chain is not a closed wire of
  any single face at all. So the discriminator is which wire of which face a chain is,
  not how many faces contain it, and not how uniform its turn angles are. `_UNIFORMITY`
  and `MAX_AXIAL_GAP_MM` remain constants standing in for that topology.
  **Not acted on yet** — the constants stay until the wire-level test is measured on the
  corpus, because a second refuted incidence test would be worse than the constants.
- A5 *abandoned road*: `--cyl-seed-lo` (global lower seed threshold) lost the real-CAD A/B
  12.9 % vs 21.3 %. A global constant moves the seam and swaps one error class for
  another — consistent with A3, and the recorded reason does not apply to a per-model,
  self-calibrated threshold.
- A6 *must exist, not seen*: a way to feed the per-model (d, α) into the seed decision.
  Candidates: `--smooth-tol`/`--smooth-angle` if the seed band depends on them; otherwise
  a mesh pre-pass that marks designed-polygon bands, or a C++ change in the fork.

- A7 *construction is not decision* — **ADDED 2026-09-05, from an unpredicted measurement**:
  deciding that a band IS a cylinder and successfully BUILDING the analytic edges and faces
  for it are independent failures, and **both feed the same revert counter**. Measured on
  `07_all_four_types_truth`: ~80 `smooth: IntAna cyl|cyl empty/same — keeping mesh polyline`
  plus 6 `smooth: analytic MakeEdge failed`, alongside 2 reverted components; on
  `L04_cyl_bottom_chamf`: `seamed360: BRepCheck invalid on seamed face` with
  `J6: shell not closed freeEdges=51`. A revert therefore does not tell you WHICH half
  failed, and any fix aimed at one half will be scored against the other. **They must be
  measured apart before either is changed.**
  *Provenance note:* the 2026-09-03 synthesis put surface–surface intersection construction
  OFF the required path, because on the fixtures it never fired. The corpus puts it back ON.
  **Route tables are corpus-dependent** — a stage absent from the fixture path is not absent
  from the product, and "which code runs" must be re-derived whenever the input set changes.

**Five costliest facts, each from an arm:** 49/49 holes → A2. `projects-ccf` +11.07 %
silent → A1 (and P0 below). 412-arc chain, span 90°, r 0.20 mm → A4. Collinear
opposite-wall rims 41.95 mm apart / 0.5 mm → A4. `--cyl-seed-lo` killed 12.9 vs 21.3 → A5.

**Predictions** (written before any check; fill `result:` with evidence, never edit the
prediction):
- P0: the `projects-ccf` band has an OCTAGONAL cross-section — 2π/(8·sin 45°) = 1.1107,
  i.e. +11.07 % is the circumscribed circle over a regular 8-gon (a 24-gon would give
  +1.15 %). | check: count distinct facet normals around the band axis in the STL (8) |
  result: **CONFIRMED 2026-09-05** — 8 distinct facet normals around the axis, 45.0 deg/facet;
  mesh volume 22627.417 (matches the bd record), circumscribed cylinder 25132.7412, ratio
  **1.110721** against the predicted 2*pi/(8*sin45) = **1.110721**. NOTE: this also corrects
  the prose in §1, which calls projects-ccf "a genuine 24-facet prism" — it is 8-sided.
- P1: a regular 8-gon prism → native trueform → `smoothCylinders ≥ 1` and STEP volume =
  mesh volume × 1.1107; a 24-gon → `smoothCylinders ≥ 1`, × 1.0115; a 96-gon →
  `smoothCylinders = 0`. | check: three trimesh prisms through `convert_native` +
  BRepGProp | result: **CONFIRMED 2026-09-05 20:58** — 8-gon: smoothCylinders=1, vol ×1.1107; 24-gon:
  smoothCylinders=1, vol ×1.0115; 96-gon: smoothCylinders=0, vol ×1.0000 (r=10, h=20, trueform default)
- P2: `--smooth-tol 0.001` and `--smooth-angle 0.5` do NOT stop the 8-gon from being
  rebuilt (the seed band ignores the tolerance → A6 negative, fix is pre-pass or C++). |
  check: same 8-gon, two flags | result: **CONFIRMED** — `--smooth-tol 0.001` → smoothCylinders=1,
  ×1.1107; `--smooth-angle 0.5` → smoothCylinders=1, ×1.1107. The seed band ignores both knobs.
  A6 negative: no existing flag reaches the decision → class (a) needs a mesh-side pre-pass
  (detect: the mesh AND the STEP are both available after conversion) plus a fork change to
  act on it (exclude/keep a band); until the fork change lands, state 2 (warn with numbers).
- P3: on the corpus, no circle found by `canonize` has < 72 segments. | check: one pass of
  `find_circles` over the corpus outputs, histogram of `segments` | result: **REFUTED
  2026-09-05** — all 157 circles have 24–59 segments, min 24, max 59, NONE >= 72. Rewrites A2.
- P4: on the corpus, every band the ground truth calls a cylinder satisfies s ≤ d·1.5 and
  θ ≤ α·1.5 for the per-model (d, α) taken as the median over bands; every band the
  ground truth calls a prism violates one of them by ≥ 3×. | check: one script over the
  corpus STLs + ground truth | result: **HALF CONFIRMED, HALF REFUTED 2026-09-05** — cylinders
  **40/40** satisfy both (max s/d 0.499, max theta/alpha 0.483). Prisms **0/12**: the 12
  unmatched bands are not prisms but cylinders in gripper_gear / gancio_parametric that the
  radius matcher missed (s/d 0.175–0.499, inside the cylinder distribution). **The corpus
  contains no designed prisms at all** — the prism half is unmeasurable here, not disproved.
  This is what blocks the learned gate and the "strictly better on >= 1" clause in §2.
- P5: on the corpus, every rim `canonize` finds bounds exactly one planar face, and the
  412-arc chain bounds two (fillet). | check: face incidence count per chain | result:
  **REFUTED 2026-09-05** — 107 of 157 rims are contained in exactly one face, 50 in none;
  coplanar-merging first leaves the ratio unchanged. Rewrites A4 to the wire level.

- P7: if the loss is the component-level revert with `budget = max(1e-4*refVol,
  3*dVolPredAbs)`, then the reverted components are exactly those where
  `SUM over engine-rebuilt bands of V_band * (1 - (n/2pi)*sin(2pi/n)) > 1e-4 * refVol`.
  A CORRECT rebuild of an n-gon hole moves volume by 1.15 % (n=24), 0.51 % (36),
  0.29 % (48), 0.19 % (59) of that hole's volume, which on a plate with holes exceeds
  1e-4 of the part. **The prediction is that the revert discards components because the
  correct rebuild of a coarse tessellation moves the volume by exactly what it must** --
  the guard punishes the fix for doing its job. | check: compute that sum per component
  from the mesh bands and compare against `smoothRevertedComponents` on the same three
  models as P6 | result: **CONFIRMED 2026-09-05** on the 2 of 3 models where bands are
  recoverable. `L06_adapter_plate`: budget 2.856 mm3, predicted dV 79.38 mm3 = **27.8x
  over**, reverted=1. `L04_cyl_bottom_chamf`: budget 0.758, predicted dV 16.81 =
  **22.2x over**, reverted=1. `07_all_four_types_truth` reverted=2 but `find_bands`
  recovers 0 bands from its output, so its sum is not evaluable. The `3*dVolPredAbs`
  alternative is excluded by observation: the reverts fired, so that term did not cover
  the change either. The guard discards correct rebuilds for moving the volume by exactly
  what a correct rebuild must move it.
  - If P7 holds, n5's fork change is a **tessellation-aware revert budget** driven by the
    same per-model (d, alpha) the audit already fits -- one fingerprint, both decisions.
  - If P7 fails, `3*dVolPredAbs` already absorbs the predicted change and the cause is
    elsewhere; the report must say which.

- P8: `IntAna cyl|cyl same` is OVER-SEGMENTATION, not an intersection defect: the pairs are
  coaxial, equal-radius bands (one cylinder split by a seam or by a crossing feature), so no
  intersection curve exists to compute. | check: on `07_all_four_types_truth`, count coaxial
  equal-radius cylindrical face pairs sharing an edge in the output STEP, and compare emitted
  cylindrical faces against `truth.json`. Prediction: pairs ~= 80, emitted ~= truth + pairs/2.
  If it holds the fix is a **coaxial-band merge before edge construction**, not a change to
  IntAna. | result: **REFUTED AS A CHECK 2026-09-05** — the output STEP of
  `07_all_four_types_truth` holds **1** cylindrical face (truth: 1) and **1** coaxial
  equal-radius pair, not ~80. The ~80 IntAna events occur during smoothing, but both
  components were then REVERTED, so the output artifact no longer contains the
  over-segmented geometry: the check as defined cannot observe the pre-revert state, and
  the over-segmentation claim is untestable from existing artifacts. The coaxial-merge fix
  is therefore UNSUPPORTED by measurement — it needs the pre-revert dump (instrumentation),
  which is out of scope until n5a lands.
- P9: the `seamed360` failure is the MIXED analytic/faceted boundary: the chamfer is a cone,
  TrueForm has no cone primitive, so the chamfer ring stays faceted and a 360° analytic arc
  cannot close against n chords. | check: count the chamfer ring's facets in
  `L04_cyl_bottom_chamf`'s STL. Prediction: **51**, and every failed `seamed360` has
  `freeEdges` equal to its non-analytic neighbour's facet count. If it holds the options are
  a faceted-arc transition ring (those vertices already sit on the cylinder to ~2e-7 mm) or a
  cone primitive — scope them separately. | result: **MECHANISM CONFIRMED, NUMBER REFUTED
  2026-09-05.** The chamfer IS a cone: 243 slanted facets over 117 azimuths at |nz| = 0.697
  (~45 deg), which TrueForm has no primitive for, so the ring stays faceted — the mixed
  analytic/faceted boundary is real. But it is **not 51 facets**, and `freeEdges` does NOT
  equal the neighbour's facet count: the cylinder wall has 104 facets over **52** distinct
  azimuths and `freeEdges = 51 = 52 - 1`. The quantity is the ANALYTIC face's own segment
  count less the seam, i.e. the chords the 360 deg face failed to absorb — not a property of
  the neighbour. Both options (faceted-arc transition ring, cone primitive) remain open and
  are scoped separately in n5c.
- P10: classify every corpus revert by cause — budget-only, IntAna, seamed, or combinations.
  Prediction: **budget-only is the majority**, because a 22–28x overshoot (P7) fires the
  revert even where every edge succeeds. This orders the fork work. | check: the 57 models
  with the frozen binary, capturing engine stdout. **NOTE: the stated source "sweep logs
  already on disk" does not exist** — `n4_score.py` let `convert_native` swallow engine
  stdout, so the existing logs contain zero `RESULT`, `revert` or `IntAna` lines. The check
  is a re-run of the same 57 models keeping stdout; still no instrumentation. | result:
  **CONFIRMED IN ORDERING, CORRECTED IN DEGREE 2026-09-05.** 19 of 57 models revert (33 % of
  the corpus). By cause: **budget-only 9**, intana 5, intana+seamed 3, seamed 2. Budget-only
  is the largest single class at **9/19 = 47.4 %** — a PLURALITY, not the predicted majority.
  The ordering conclusion stands: n5a (budget) reaches more of the corpus than n5b or n5c,
  and is also the smallest change. Note `gripper_gear` (truth 75 cylinders),
  `L06_adapter_plate` (14) and `L06_motor_mount` (5) revert with ZERO construction warnings —
  pure budget casualties, exactly P7's mechanism.

**NEGATIVES: the decision boundary is unpopulated in real CAD** (measured 2026-09-06).
The full KiCad Packages3D library — **6822 parts** with true B-Rep — yields **1227**
evenly-spaced regular polygons, distributed **k=8: 1225, k=6: 1, k=12: 1**. Essentially
every designed polygon in real electronics hardware is a regular OCTAGON at theta = 45 deg;
most k=6 parts are not regular hexagons and fail the evenness test. **No part in 6822 has
n in the 18–32 range**, which is exactly where `REBUILD_MAX_RATIO` and
`MAX_OBSERVED_TESSELLATION_TURN_DEG` sit.

Consequences, both of which must be stated wherever those constants are cited:
1. The two constants remain **unvalidated at the boundary**. They are fitted to a
   positive-only sample (52 real cylinder bands) and the negatives that exist are 45 deg
   octagons — three times past the threshold, so they constrain nothing near it.
2. **That is also why shipping state 2 as-is is the right call, and it is a data-based
   reason rather than a concession.** Nobody designs a 24-sided prism: real hardware is
   squares, hexagons and octagons. The ambiguous 18–32 band appears to be genuinely rare
   in practice, not merely unmeasured — so a warned, undecidable row costs little and a
   silent wrong rebuild would cost a lot.
   Boundary-region negatives would have to be authored deliberately, which makes them
   synthetic; ISO fasteners do not help either (nuts are hexagons).

- P16 (recorded 2026-09-06, BEFORE n5d moves anything): once `buildFaces` actually builds
  `L06_adapter_plate`, its revert cause moves from `buildFaces-empty` to `budget` — the
  correct rebuild's change is 79.38 mm3 against a 2.86 mm3 budget. | check: re-run
  `--diag-revert-cause` on that model after n5d lands | result: pending
  **If P16 holds, the budget's two fused functions must be SEPARATED before any allowance
  is reconsidered:** (a) solid VALIDITY — closed shell, BRepCheck clean, positive volume —
  checked explicitly and never traded away; (b) the tessellation-aware ALLOWANCE for a
  legitimate Delta. n5a failed precisely because it widened (b) while (a) was riding on the
  same test: `L04_soap_bar` emitted a NEGATIVE volume (-2512.010 mm3 against a mesh of
  4102.934) the moment the allowance suppressed the revert. **P7 is queued, not
  irrelevant** — it becomes actionable only after (a) exists independently, and only under
  the validity gate below.

- P20 (recorded 2026-09-06 BEFORE measuring; **this becomes the product's headline metric,
  replacing "models reverting", which is retired**): corpus cylinder recall — surviving
  analytic cylindrical faces in the output divided by truth cylindrical faces, frozen
  binary, whole corpus and per model — is **below 30 %**, because `gripper_gear` (75) and
  `SpeedTestStructure` (246) alone hold 321 of the corpus's 474 truth cylinders and BOTH
  empty via `buildFaces-empty`. | check: count `Geom_CylindricalSurface` faces in each
  frozen-binary output against `truth.json` `cyl_faces` | result: **CONFIRMED 2026-09-06,
  and worse than predicted: 50/474 = 10.5 %.** The eight models with the most truth
  cylinders hold 403 of 474 between them and return essentially none:
  `SpeedTestStructure` 0/246, `gripper_gear` 0/75, `gancio_parametric` 0/25,
  `L06_adapter_plate` 0/14, `L04_soap_bar` 0/12, `clamp_half_a` 0/11, `L09_gear_blank` 0/8,
  `L06_motor_mount` 0/5. The models scoring 100 % are small (`output.step` 12/12,
  `L04_fillet_block` 4/4, `credit_card_holder` 4/4), consistent with P18: the successes are
  the simple parts. **This is now the headline metric; "models reverting" is retired.**
- P21 (recorded 2026-09-06, fires only AFTER n5d): in components that then build partially,
  the faces left faceted are the truth's `other_faces` (cones, tori) plus their adjacency,
  and not arbitrary regions. | check: per component, classify the still-faceted regions
  against the truth's non-planar non-cylindrical faces | result: pending — if it holds,
  n5e is the cone primitive (chamfers first, tori for fillets after). **Do not write n5e
  until P21 has a result.**

**DASHBOARD METRIC (established 2026-09-06).** `P20` corpus cylinder recall —
surviving `Geom_CylindricalSurface` faces in the output over `truth.json` `cyl_faces`,
whole corpus and per model — **is the product's number. Baseline: 50/474 = 10.5 %
(frozen binary).** It is recomputed on every fork build and reported with every change in
this series. "Models reverting" is retired as a metric: it conflated five things and, as
measured, was not even a clean count of reverts.

- P22 (recorded 2026-09-06 BEFORE instrumenting): the `buildFaces` exit taken by
  `L06_adapter_plate` is **not a literal `return false`** — it is a tail `return ok;` /
  `return !out.empty();` whose flag was cleared by a nested failure that has no return of
  its own. Most likely a `BRepBuilderAPI_MakeWire`/`MakeFace` failure inside the per-region
  loop. | check: exhaustive `DIAG_EXIT(__LINE__)` on EVERY `return` in the function's line
  range, all indentations, lambdas included; run `L06_adapter_plate` with
  `--diag-revert-cause` and read the line | result: pending

**METHOD RULE (established 2026-09-06 — the method is the finding).** Any "which path was
taken" question is answered by **instrumenting every statement of a kind in a line range,
keyed by `__LINE__`** — never by hand-placed labels. Hand-placing missed the site through
four build cycles and reported a false `exit=none`; the exhaustive `sed` over all 38
`return`s named it in one. Applies to `return`, `continue`, `break`, `throw`, `goto`.

- P23 (recorded 2026-09-06 BEFORE the build): between region acceptance and the
  `built.empty()` guard at `refit_build.cpp:4289`, regions are **skipped without writing
  `r.reject`** — which is why the histogram reads `None=20` / `None=9` with zero faces
  built. Ranked: **(i)** a `continue` in the build loop when boundary/chain construction
  returns empty — most likely, given the name `ChainUnstable` and that no face is ever
  attempted; **(ii)** the loop iterates a subset filtered by a flag set elsewhere
  (plan/`usedRefit`-style bit) that is empty on these models; **(iii)** faces are built and
  dropped before `built.push_back` without touching `r.reject`. | check: `DIAG_SKIP(__LINE__)`
  on every `continue` and `break` in [build-loop start, 4289], counted per line and per
  region, on `L06_adapter_plate` and `L08_cable_clamp`. One build. | result: pending
- P24 (recorded 2026-09-06, NOT chased now): `L04_puck`'s 103 `VertexResidual` rejections
  over 300 regions are absolute residual thresholds meeting a coarse tessellation — the
  threshold does not scale with the model's own chord error. | check: compare the rejected
  regions' residuals against their `chordSagitta` and the per-model (d, alpha) | result:
  pending — belongs to the `heal-discard` population, not `built-empty-main`.

**The two populations stay apart.** `built-empty-main` (4289) and `heal-discard` (4527) get
separate claims and separate specs. Merging them would aim one fix at the wrong half, which
is A7 restated and what n5a already demonstrated.

**PARITY-BEFORE-BELIEF GATE (permanent, established 2026-09-06).** No result from an
instrumented build is believed until that build reproduces the frozen engine **byte-for-byte
on the STEP body**. A `sed` that inserted a recorder before the keyword turned
`if (c) break;` into an unconditional break and fabricated the exact failure under
investigation; the corrupted binary would have failed this gate immediately. Applies to
every instrumented build, permanently, with no exception for "just a diagnostic".

- P25 (recorded 2026-09-06 BEFORE the build): the culprit faces at `refit_build.cpp:4571`
  are at **analytic/faceted junctions** — P9's mechanism — so the shell is invalid because
  of the mixed boundary, and the culprits are the analytic faces adjacent to regions that
  were never rebuilt. **Alternative:** they are the two ends of a through-hole (a cylinder
  meeting two planar faces that carry inner wires). | check: extend `--diag-revert-cause`
  to emit, per culprit, its face type, its neighbours' face types, and the BRepCheck defect
  (free edges / orientation / self-intersection), on `L06_adapter_plate` and
  `L08_cable_clamp`; one build, parity-gated | result: pending

- P26 (recorded 2026-09-06 BEFORE the build): the BRepCheck status of the two culprit
  plates names the fix. Ranked: **(i)** `BadOrientationOfSubshape` on the inner wire — the
  hole rim reuses the seamed cylinder's edges in the CYLINDER's orientation and the plate
  builder does not reverse them; **(ii)** `NotClosed` on the inner wire — the seamed
  cylinder's rim is one closed edge running seam-vertex to seam-vertex, while the plate's
  inner wire is built from the chord chain without that vertex, so the two are not the same
  TShape (S03's "stolen TShapes" seen from the other side); **(iii)** `NoCurveOnSurface` —
  the reused edges carry no pcurve on the plane. | check: emit `BRepCheck_Analyzer` statuses
  per culprit face AND per sub-shape (wires, edges) on `L06_adapter_plate` and
  `L08_cable_clamp`; one build, parity-gated before belief | result: pending
- P27 (recorded 2026-09-06, fires after the P26 fix): the four `other_faces = 0` models
  (`L06_adapter_plate` 14 truth cylinders, `L06_motor_mount` 5, `L08_rail_mount` 4,
  `L08_cable_clamp` 3) build and pass §2b, and recall rises from **50/474 to >= 76/474
  (16 %)**; the eleven cone-bearing models keep discarding, with DIFFERENT culprits. If any
  of the eleven also build, the plate-with-hole was their only blocker — record which. |
  check: re-run the P20 recall sweep and the cause census after the fix | result: pending

**Fix locus, fixed in advance:** the plate builder. **Never** the ladder, **never** S03,
**never** RULE 1.4. Gates unchanged: §2b validity on every component of 57 + 26 negatives,
byte parity on the 38 clean builds and on Body9/12/18/20, `MISSED = 0`, recall strictly up,
**and the fix must not change any model that already builds.**

- P28 (recorded 2026-09-06 BEFORE the census). Ranked:
  **(i) over-reversal by cap end.** In a valid closed shell every shared edge appears once
  FORWARD and once REVERSED across its two faces. The seamed cylinder uses its two cap
  circles with OPPOSITE orientations, so the plate closing the vMin cap and the plate
  closing the vMax cap must use their circle with opposite orientations. A blanket
  `iw.Reversed()` on an edge taken in its natural orientation gives both caps the SAME
  absolute orientation — correct for one end, wrong for the other. **Prediction:** every
  inner loop on the 2 culprit plates binds the same cap end of its cylinder, and the 18
  valid plates' loops bind the other end (or carry no holes). **Fix:** orient the shared
  edge in the plate's inner wire as the OPPOSITE of the orientation the cylinder face uses
  for that edge — queried from the cylinder's wire, never assumed.
  **(ii) face reversal.** `makeFaceKeep` builds the face `Reversed` when the plane's natural
  normal opposes `r.outwardNormal`, flipping the wire convention. **Prediction:** the 2
  culprits are the plates whose plane normal disagrees with `outwardNormal`.
  **(iii) shell binding** — unlikely: `BadOrientationOfSubshape` at face level is a
  face/wire relation and does not depend on the shell.
  | check: one differential census over all 20 planar faces of `L06_adapter_plate` and all 9
  of `L08_cable_clamp` — per face: BRepCheck status, sign of `outwardNormal` vs plane
  normal; per inner loop: cylinder region id, cap end (vMin/vMax), the orientation the
  cylinder face uses for that edge, the orientation the plate uses. The two columns constant
  on the 2 culprits and different on the 18 name the mechanism. Parity-gated. | result: pending

**SWEEP HYGIENE (permanent, established 2026-09-06).** Every sweep copies the engine
binary to a **run-specific path carrying its sha256** and records that hash in the report
header. A rebuild can then never touch a run in flight. Established after a gate sweep
launched at 12:02 was silently mixed with a binary replaced at 12:07 and had to be
discarded and re-run. Same family as the parity-before-belief gate: **never replace an
artifact a running measurement depends on.**

- P30 (recorded 2026-09-06 BEFORE the build): the residual culprit on `L06_adapter_plate`
  is a plate whose **OUTER** wire is a single closed circular edge — the part is round and
  its rim binds the seamed OUTER cylinder — and whose outer signed area is **negative**
  with respect to `r.outwardNormal`, while the other 19 plates' outer areas are positive.
  | check: emit per plate the outer wire's edge count and the sign of its signed area under
  `--diag-revert-cause`; one build, parity-gated | result: pending
  **If it holds, COMPLETE the rule rather than add a case:** orient the OUTER wire by
  geometry against the face normal first (signed area > 0 w.r.t. `outwardNormal`), then the
  inners against the outer — same sampled-curve area, same code path, both levels.
  P29 then expects `L06_adapter_plate` culprits 1 → 0 and cyl 0 → 14, and P27's
  >= 76/474 follows.

**MEASUREMENT STANDARDS (canonical; all three established 2026-09-06).**

1. **Parity before belief.** No result from an instrumented build is believed until that
   build reproduces the frozen engine byte-for-byte on the STEP body. A recorder inserted
   before a keyword once turned `if (c) break;` into an unconditional break and fabricated
   the failure under investigation; this gate catches that class immediately.
2. **sha-named binaries.** Every sweep copies the engine to a run-specific path carrying its
   **sha256**, and the hash goes in the report header. A rebuild can then never touch a run
   in flight. Established after a sweep was silently mixed with a binary replaced five
   minutes into it.
3. **ID-independent geometric equivalence — the canonical proof when bytes differ.**
   Comparing STEP text is NOT a valid equivalence test: entity IDs are renumbered whenever a
   wire is reordered, so identical geometry reads as a difference. My first attempt at this
   flagged 7 of 10 models as regressions on that artifact alone and would have blocked a
   correct fix. The proof is:
   - the multiset of **(surface type, face area rounded to 1e-9)** over all faces — identical;
   - **total surface area** — relative difference <= 1e-9;
   - **volume** — relative difference <= 1e-9;
   - **face count** equal and **BRepCheck valid on both**.
   Measured this way, all 10 byte-differing models in the n5d sweep were the same solid,
   re-serialised.

- P31 — **REFUTED 2026-09-06.** It expected the `j6-uncollapse` discards to fall once the
  plate-orientation defect was fixed. They did not: **7 of 12 before n5d, 7 of 12 after.**
  J6 therefore has its own trigger, independent of inner/outer wire orientation, and is the
  subject of the next chapter rather than a side effect of this one.

- P32 (recorded 2026-09-06 BEFORE any J6 instrumentation): the geometric trigger of the
  J6 uncollapse is a **collapsed analytic chain that only ONE of its two faces adopted** —
  one side binds the single collapsed edge while the other still carries the original
  polyline chain, so the shared TShape never pairs and the shell shows a free edge. That is
  why the heal's remedy is to UNCOLLAPSE the chain (ban the collapse, clear its geom) rather
  than to re-pair it: reverting both sides to the mesh polyline restores a shared TShape by
  construction. **Prediction:** on the models that reach `j6-uncollapse`, every free edge
  the heal matches lies on a chain whose two regions disagree about collapse, and the count
  of such chains equals the count of free-edge pairs matched. | check: emit, per free edge,
  the matched chain id and the collapse state each of its two regions used | result: pending
- P33 (recorded with P32): the discard after the heal is **not a failure to recover** but a
  deliberate protection of the FACETED baseline's accuracy — the source says
  *"after the heal, do not explode recover -- that dirties vertex TShapes and worsens
  R2 volDelta"*. **Prediction:** forcing a second heal pass (or an explode-recover) on
  `SpeedTestStructure` produces either a still-open shell or an R2 whose volume error is
  worse than the current discard's, i.e. the guard is load-bearing exactly as the n5a budget
  turned out to be. | result: pending

**P33 ACCEPTED without further test** (user decision 2026-09-06): the J6 discard is
load-bearing, same family as the n5a budget. **The fix for `SpeedTestStructure` is upstream,
on the 18 `FaceBuildFailed` regions — never in J6.**

- P34 (n5f, recorded BEFORE the check): `gripper_gear`'s 64 unrecovered truth cylinders are
  **tooth-tip and root arcs tessellated with <= 2 facets along the arc**. A single facet
  carries no curvature, so **no facet-based recogniser can recover them in principle** —
  this is a metric problem before it is an engine problem. | check: from `truth.json` and
  the mesh, count facets-along-arc per truth cylinder on `gripper_gear` | result: pending
  **If it holds:** split the dashboard denominator — **recoverable recall** (truth cylinders
  with >= 3 facets along the arc) reported beside raw recall, corpus-wide, and the remaining
  work re-ranked by *recoverable* cylinders unblocked.
- P35 (n5e, recorded BEFORE the build): the 18 `FaceBuildFailed` regions on
  `SpeedTestStructure` are **planar faces with many inner loops that `MakeFace` rejects for
  a NON-orientation reason** — inner wires tangent to or touching each other or the outer,
  or off-plane beyond tolerance. | check: per `FaceBuildFailed` region emit face type,
  inner-loop count, and the `BRepBuilderAPI_FaceError` / exception text under
  `--diag-revert-cause`; one build, parity-gated | result: pending
  **Expectation once fixed:** 18 -> 0 face-build failures, J6 never fires on this model,
  and up to 246 truth cylinders become recoverable.
  **Recorded, not chased here:** `ChordConsistency = 114` on the same model is a RECOGNITION
  item (n5f family), not a face-build one.

**DIAGNOSTIC INVENTORY — step one of EVERY check (established 2026-09-06).** Before
instrumenting anything, list what the engine already ships: `grep -rn getenv src/`. This was
learned the expensive way — `STL2STEP_DIAG_PLATES` already existed and already answered P35,
and I nearly rebuilt it.

| env var | file | emits |
|---|---|---|
| `STL2STEP_SEGMENT_SUMMARY` | `stl2step.cpp` | `STL2STEP_SEGMENT_SUM` per-component segmentation totals |
| `STL2STEP_DIAG_PLATES` | `refit_build.cpp` | `DIAG_PLATE rid=.. valid=.. st=..` — per-plate BRepCheck status on MakeFace failure |
| `STL2STEP_J6_DIAG` | `refit_build.cpp` | `DIAG_J6` free-edge ledger + `DIAG_FALLBACK_SUM j6-uncollapse` |
| `STL2STEP_P2_DIAG` | `refit_build.cpp` | `DIAG_CASCADE` / `DIAG_COLLAPSE` / `DIAG_FALLBACK` (P2 build stage) |
| `STL2STEP_FAIL_RID` | `refit_build.cpp` | forces a chosen region to fail — fault injection |
| `STL2STEP_COLLAPSE_DIAG` | `refit_math.cpp` | `DIAG_ARCHCHAIN` chain-collapse decisions |
| `STL2STEP_LAWBAND_DIAG` | `refit_lawband.cpp` | `DIAG_LAWBAND` / `DIAG_LAWCAL` law-band calibration |
| `STL2STEP_P1_DIAG` | `refit_fillet.cpp` | P1 fillet-stage trace |
| `STL2STEP_PRISM_DIAG` | `refit_prism.cpp` | `DIAG_PRISM` / `DIAG_PRISMLVL` |
| `STL2STEP_PRISM_ASSIST`, `STL2STEP_PRISM_ADVISORY_DIR` | `refit_profile.cpp` | `DIAG_PRISM` / `DIAG_PROFILE` |
| `STL2STEP_PRISM_INJECT_BAD` | `refit_prism_build.cpp` | `DIAG_PRISMBUILD` — fault injection |

Plus the n5 additions on the fork: `--diag-revert-cause` (per-component revert cause,
`DIAG_EXIT_T` tags, reject histogram, skip counts).

- P39 (n5e, recorded BEFORE measuring). **`UnorientableShape` is NOT
  `BadOrientationOfSubshape` one level out.** The latter means the wire runs the wrong way;
  the former means **no consistent orientation exists** — edges do not chain head-to-tail, a
  vertex is shared by >= 3 edges, or an edge appears twice. n5d's whole-wire signed-area rule
  **cannot even apply**: the area of an inconsistently directed wire is meaningless.
  Ranked:
  **(i) multi-edge inner loops** (`chainIdx.size() > 1` — a hole split into >= 2 arcs by a
  seam or a crossing feature) whose edges are added in CHAIN order and CHAIN direction
  instead of being chained by vertex connectivity. *Prediction: every `UnorientableShape`
  wire has >= 2 edges with at least one head-to-tail break, and NO single-edge wire is ever
  unorientable.*
  **(ii) branching** — a vertex of valence >= 3, i.e. rims of adjacent holes welded together
  because the weld tolerance is coarse relative to hole spacing. *Prediction: valence-3
  vertices appear only on plates with tightly spaced holes — a TOLERANCE defect (fingerprint
  family, n5g), not a builder defect.*
  **(iii) duplicate edges.**
  | check: per failing plate, per inner wire — edge count, head-to-tail breaks, max vertex
  valence, duplicates | result: pending
  **Fix follows the winning row:** (i) -> chain each inner wire's edges by vertex
  connectivity (`head(e_k) == tail(e_k+1)`) BEFORE n5d's orientation rule, plate builder
  only; (ii) -> not n5e, recorded for n5g's tolerance work.
  **Expectation stated in advance:** 18 `FaceBuildFailed` -> 0, J6 never fires on
  `SpeedTestStructure`, **+144 in-band cylinders**.

- P40 (n5e, recorded BEFORE the check). A valence->=3 vertex on an OUTER wire is a planar
  region whose boundary passes through the same point twice — a **pinched region** (two
  lobes meeting at a point, or a U whose arms touch). P39(ii)'s "welded hole rims" wording
  does not apply: these plates have **no inner wires at all**. Two mechanisms, two owners:
  **(a) weld** — the STL holds two DISTINCT vertices within `weld_tol` there and the weld
  merges them -> a tolerance defect, **n5g**;
  **(b) genuine pinch** — the STL holds ONE vertex there, shared by both boundary passes ->
  a topology defect, **plate builder, n5e**: split the region at the pinch vertex into two
  faces (or duplicate the vertex as two coincident TVertices). **Never chain-by-connectivity**
  — at valence 3 there is no unique successor.
  *Prediction: (b), for a print-benchmark structure of thin walls and struts.*
  | check: per pinch vertex, the number of distinct source vertices within `weld_tol` and the
  number of boundary passes; one source vertex -> (b), two or more -> (a) | result: pending
  **Note settled from source before measuring:** the engine welds **exactly** by default
  (`weldTol > 0` only when explicitly passed; `stl2step.cpp:327-338`), and neither the corpus
  runs nor the webapp pass it. Under exact welding only bit-identical coordinates merge, so
  (a) cannot arise unless a weld tolerance is supplied — which makes (b) the only live
  mechanism in every measurement taken so far.

- P41 (n5e, recorded BEFORE measuring): the discriminator between the **18** failing
  regions and the **235** pinched-but-fine ones is **edge-connectivity within the accepted
  region**. In the 235, the two coplanar fans at the pinch vertex belong to **two distinct
  regions** — the edge-adjacency grower never joins them, so each is a clean disk merely
  touching another at a point, which is ordinary. In the 18, both fans are the **same
  region**, edge-connected through a chain of coplanar triangles — a U whose arms meet
  outside — so that region's outer walk visits the vertex twice.
  *Prediction: exactly 18 same-region, 235 two-region.*
  | check: per pinch vertex, do both fans lie in one accepted region — reproduced from the
  STL by union-find over edge-adjacent coplanar triangles, no build | result: **REFUTED
  2026-09-06 — 0 same-region, 253 two-region.** Every one of the 253 pinch vertices has its
  two coplanar fans in DIFFERENT accepted regions, i.e. all 253 are the ordinary
  point-touching case P41 predicted for the 235, and the residual 18 does not exist on the
  mesh side at all. **Consequence: the 18 valence->=3 vertices are introduced by the WIRE
  BUILDER, not by mesh or region topology** — no mesh pinch (P40: 0), no region pinch that
  is same-region (P41: 0). The chain used to build the outer wire must be picking up an edge
  from a neighbouring region, or adding a chain twice. Three successive mesh-side hypotheses
  (P39(i) inner loops, P39(ii)/P40 weld-or-pinch, P41 same-region) are now refuted; the next
  step is to emit the 18 branch-vertex POSITIONS and the provenance of each incident edge
  from the builder, which needs a build.
  **If it holds:** n5e's fix is scoped to same-region pinches ONLY, and two forms are tried
  on one region with BRepCheck deciding: **(1)** split into two faces along the shortest
  interior edge path from the pinch vertex to the opposite boundary — two faces sharing an
  interior edge, fully valid; **(2)** one face with two coincident TVertices at the pinch —
  manifold wire, may trip `SelfIntersectingWire`. Prefer (1) unless the analyzer says
  otherwise. Record the face-count delta against truth per split region.
  **If it fails:** report both populations' full attribute table before any code.

- P43 (n5e, recorded BEFORE the source read, so the read CONFIRMS or REFUTES rather than
  suggests): valence 4 with two chains means **one chain passes through the vertex and the
  other starts and ends there**. The `regB = -1` chain at each of the 18 is a **CLOSED
  loop** — the rim of a small hole whose cylinder was rejected (`ChordConsistency`, the 114
  on this model; one per layer at the 2 mm pitch, hence the consecutive rids 616..622) — so
  its wall triangles belong to no region, and it shares **exactly ONE** vertex with the outer
  chain: a hole **tangent to the plate's edge**, the keyhole of a print benchmark. The wire
  builder concatenates that loop into the outer walk through the shared vertex, giving
  valence 4, zero inner wires and `UnorientableShape`.
  | check: closure (first vertex == last), shared vertices with the outer chain (predict
  exactly 1), and the `-1` side's triangles' rejected region id and reason | result: pending
  **Fix levels, to decide AFTER the read:** in the wire builder, a closed `-1` loop touching
  the outer walk is **never concatenated** — it becomes an inner wire with its own TVertex at
  the touch point, or the plate is declared unbuildable and stays faceted. **The interaction
  that costs the 246 is FaceBuildFailed -> J6 heal -> discard, not the plate itself.**
  Upstream, why those cylinders are `-1` is n5f (`ChordConsistency`); accepting them would
  make the loop a shared circle but would NOT remove the tangency, so the builder fix is
  needed regardless.

- P44 (n5e, recorded BEFORE the source read). The 0.0381 mm gap at all 18, under EXACT
  welding, settles where the join happens: **the mesh keeps two vertices and I8 holds on the
  mesh side; something downstream identifies them BY DISTANCE.** The wire assembly
  (`buildLoopWire` / chain collapse / a `BRep_Builder`, `MakeWire` or sewing tolerance)
  merges chain endpoints closer than a tolerance `t` into one TVertex; on
  `SpeedTestStructure` `t > 0.0381 mm`, so the 0.038 mm bridge between hole rim and plate
  edge — real geometry, a thin wall — collapses to a point and the builder manufactures a
  figure-8 the mesh never had.
  | check (1): find every distance-based vertex identification in the wire path and its
  value on this model — **name the constant** | result: pending
  | check (2), the strong one: per corpus model, count region-boundary vertices having a
  DISTINCT mesh vertex within `t`; **prediction: equals that model's `UnorientableShape`
  plate count (18 here), model by model** | result: pending
  **Fix, after P44:** chain endpoints join into one vertex only on **topological identity —
  the same mesh vertex — never distance**. Welding is exact, so distance-based merging buys
  no robustness and only manufactures degeneracies. Any already-building plate that CHANGES
  under the fix is a case where distance-merge was silently altering topology: **report it,
  never hide it.**
  **Recorded, not chased:** J6's `matchTol = max(0.5, sewTol*20, epsPlane*4)` carries a
  0.5 mm floor against 0.038 mm features — the same family as the absolute tolerances already
  replaced. It matters only if J6 still fires after the fix.

**DIAGNOSTIC STORAGE (standard, fork): `src/refit_diag.hpp`.** Every diagnostic counter and
its accessor are declared TOGETHER there, included early. Declaration order caused two build
failures in this series; the structure now makes them impossible. Nothing else in the engine
declares diagnostic storage. Same class as sha-named binaries and parity-before-belief.

- P49 (recorded BEFORE the build): on `L08_T_bracket_recon`, triangles **727 and 730** were
  assigned to a region and later removed by a refinement pass (residual pruning or boundary
  trimming for chain stability) **after the island set had already been computed** — the
  island is a snapshot taken before the last pruning, so the two land in neither.
  | check: a per-triangle ownership map at emission — each input triangle to an emitted face
  id or the island; **predict exactly two with neither** | result: pending
  **Fix if it holds:** compute the island as the FINAL complement of the emitted regions, and
  assert the invariant at emission — every triangle in exactly one face or the island; free
  edges = 0 when the input mesh is closed, else an explicit warning (the all-paths closure
  contract).
  **Scope corrected by P51:** the violator set is **ONE model**, not the seven the area audit
  suggested. Only `L08_T_bracket_recon` is topologically broken (open shell, 4 free edges);
  the other six are closed with zero free edges, and a closed shell cannot lose a patch —
  their area moves are the analytic rebuild's legitimate chord-to-arc gain against planar
  re-projection loss. **Area is not coverage.**

**Consequence for §1.** Do not build step 1's tests as written until P1–P2 have results:
if P2 holds, class (a) is not a `canonize`/`rebuild` problem at all and §1's scope must
add a mesh pre-pass (or a fork change) — the current scope cannot close `projects-ccf`.
If P4 holds, step 2 (learned gate) is not needed for class (a). If P5 holds, `_UNIFORMITY`
and `MAX_AXIAL_GAP_MM` are replaced by incidence tests, not re-tuned.


## 1. TARGET GOAL

- **Functional Objective:** make the analytic rebuild of circles and cylinders **decisive**.
  Every circle chain (`canonize.py`) and every cylinder band (`rebuild.py`) must end in exactly
  one of three states, and the state must be *earned by evidence*, never by a hand-tuned constant:

  1. **REBUILT** — the evidence proves the facets are a tessellation of an analytic surface.
  2. **KEPT FACETED, WARNED** — the evidence is ambiguous; the warning names the candidate and
     the numbers that made it ambiguous, so the user can decide.
  3. **KEPT FACETED, SILENT** — the evidence proves a designed polygon/prism. Silence is only
     allowed here.

  The failure this closes for good: a **wrong rebuild that nobody is told about**. The open case
  `projects-ccf` is the archetype — a genuine 24-facet prism rebuilt as its circumscribed
  cylinder, **+11.07 % volume, no warning**. That must become impossible, not rare. A wrong
  rebuild is strictly worse than no rebuild.

  Three failure classes to close, all three:

  - **(a) designed prism vs tessellated cylinder** (`projects-ccf`, open).
  - **(b) fillet / arc strip vs hole rim** — e.g. the 412-arc chain, median span 90°,
    r = 0.20 mm: rejected today, but by the `_UNIFORMITY = 0.35` / `MIN_SEGMENTS` gates,
    i.e. by luck of the constants.
  - **(c) one through-hole vs two coaxial holes in opposite walls** — decided today by
    `MAX_AXIAL_GAP_MM = 0.5`, a constant with no relation to the model.

- **Method — in this order, strictly. Do not start at step 2.**

  1. **Deterministic evidence first.** A tessellator applies *one* chord tolerance to a whole
     model. For a tessellated band of radius R and facet angular step θ, the sagitta
     `s = R·(1 − cos(θ/2))` is that tolerance; it must agree across **all** curved bands of the
     model to within their own fitting residual (self-calibrate it exactly as TrueForm
     self-calibrates its law parameters — median over bands, robust to outliers). A designed
     prism has an arbitrary "sagitta" inconsistent with the model's tolerance, a small facet
     count, dihedral steps of exactly 360/n, and per-facet vertices coplanar to fp precision.
     Derive the test, implement it, and **measure the separation** it gives on the corpus
     (class a). For class (c), replace the 0.5 mm constant by the model's own tessellation
     tolerance and by topology: are there interior faces between the two bands (two walls) or
     not (one bore)? For class (b): is the chain the boundary of a face (rim) or does it sit
     between two tangent-continuous faces (fillet)? Span in degrees and radius relative to the
     model tolerance are supporting evidence, not the decision.
  2. **Only for the residual ambiguity** that step 1 provably cannot separate on the corpus: a
     small learned gate on **derived features, never on coordinates or STEP text** — turn CoV,
     chord CoV, span°, radius, planarity residual, axial gap / model tolerance, facet count,
     sagitta / model tolerance, neighbour-face agreement. Logistic regression or a decision tree
     of depth ≤ 4, trained on the real-CAD corpus with B-Rep ground truth, leave-one-model-out
     cross-validation, calibrated probability. Choose the decision band so that the
     **false-rebuild rate on the corpus is exactly zero**; everything inside the uncertain band
     goes to state 2 (warned). Coefficients checked in as a plain JSON data file next to the
     code, so a human can read why a decision was made. No neural network, no LLM, no network
     call, no new heavy dependency — if scikit-learn is not already importable, write the
     logistic regression in numpy (it is thirty lines).
  3. **Warnings carry the evidence.** Not "possible cylinder kept faceted" but
     `24-facet band r=12.30 mm: sagitta 0.41 mm vs model tolerance 0.02 mm — kept faceted
     (designed prism?)`. The browser test already expects an actionable warning; this is what
     actionable means.

- **Target Files / Scope (writable):** `src/mesh2step/canonize.py`, `src/mesh2step/rebuild.py`,
  a new `src/mesh2step/intent.py` (evidence + features + gate), `src/mesh2step/result.py` only
  if a new warning code is needed, `tests/test_canonize.py`, `tests/test_rebuild.py`, a new
  `tests/test_intent.py`, `webapp/server.py` only to surface the warning text unchanged,
  `README.md` for the three-state contract. **Never touch anything under `refs/`** (read-only
  reference truth, gitignored — git gives you no protection). **Never touch the native binary
  or `native.py`**: this work is post-processing of the STEP the native engine emits.

- **Open Bindings:**
  - **Step 0, before any edit:** locate the real-CAD corpus (**57 STEP models with B-Rep ground
    truth**) and the **A/B scorer** built in the 2026-09-05 session (see
    `~/.claude/projects/-home-tommaso-projects-mesh2step/memory/` and the Forgetful checkpoint
    document #729). Record both paths in the report. If either cannot be found on disk,
    **STOP and report** — do not fabricate a corpus, do not proceed on synthetic data alone.
  - `/usr/bin/python3` is the interpreter with `OCP`; other `python3` on PATH may lack it.
  - If step 1 alone reaches zero false rebuilds on the corpus, **step 2 is not built** — say so
    in the report. A learned gate that is not needed is scope creep.

## 2. HARNESS ENVIRONMENT & GROUND TRUTH

- **Harness Interface:** the §3 command sequence is the sole oracle.

- **Fail-to-Pass (F2P):** author these FIRST and confirm each is RED before touching `src/`.
  1. `tests/test_canonize.py::test_small_holes_are_found_at_the_same_tolerance_as_large_ones`
     and `::test_fit_rejects_a_lobed_ring_that_sits_inside_tolerance` — red today; they go green
     by fixing the detector, **not by editing the tests**.
  2. `tests/test_webapp_browser.py::test_lost_circle_gets_an_actionable_warning` — green.
  3. **Designed prism (class a):** a regular 24-gon extruded with trimesh, in a model that also
     contains a genuinely tessellated cylinder at a fine chord tolerance. The prism is NOT
     rebuilt; the output volume matches the mesh volume to 1e-6 relative; a warning names the
     band, its facet count, its sagitta and the model tolerance. The cylinder IS rebuilt as one
     seamed 360° face.
  4. **Tessellated cylinder alone (class a, control):** the same radius tessellated at the
     model tolerance (≥ 96 facets) IS rebuilt — no warning.
  5. **Two holes vs one bore (class c):** a box with two coaxial holes in opposite walls whose
     inner faces are **0.3 mm** apart (the current constant merges them) stays **two**
     cylinders; a single through-bore of the same radius stays **one**. Both without warning.
  6. **Fillet vs rim (class b):** a ~90° arc strip between two tangent-continuous faces is not
     reported as a lost circle and is not rebuilt as one.
  7. **Corpus gate:** on the 57-model corpus the A/B scorer is ≥ baseline on **every** model,
     with **zero false rebuilds** — a rebuild counts as false when it moves the volume away
     from the B-Rep truth by more than the model's tessellation tolerance allows. Record the
     per-model table.

     **"strictly better on ≥ 1 model": BLOCKED-BY-DATA, not failed.** This clause was written
     assuming the 57-model corpus contained the three failure classes. It does not: P4 measured
     52 candidate bands with B-Rep ground truth and **every one is a cylinder** — no designed
     prisms, no sub-millimetre-wall coaxial holes. The clause is therefore unsatisfiable here
     **by construction**, and a change that is exactly neutral on this corpus (measured: 57/57
     identical, 0 differences on every field) is the correct outcome, not a regression. It is
     an error in this spec, not in the code.
     **Evaluated on the extended corpus** once the designed-polygon negatives are in it (see
     `n5-seed-gates.spec.md` §5). **Leave this gate visible and unticked until then.**

  **Every new test must assert something that fails without your change.** Verify each by
  stashing your `src/` change and watching it go red. A test that passes against the current
  code proves nothing.

- **Pass-to-Pass (P2P):** `/usr/bin/python3 -m pytest -q tests/ -k "not Body11 and not Body28"`.
  Measure the baseline FIRST and write it into the report. No test passing at baseline may fail
  after. `test_dxf_byte_identical` is a known 3-ulp divergence and is NOT yours.

- **Test Integrity Constraint:** modifying, mocking, skipping, xfailing or loosening any
  existing test or fixture is prohibited and invalidates the run.


## 2b. VALIDITY GATE — binding on n5d and every spec after it

Learned from `L04_soap_bar`: **revert count is not a success metric.** n5a reduced reverts
by 1 on that model and produced a solid of negative volume. A change that "fixes" reverts
while corrupting geometry passes any revert-count gate and must fail this one.

For **every non-reverted component**, on all 57 corpus models AND the 26 designed-polygon
negatives:

- [ ] the shell is CLOSED (`BRep_Tool::IsClosed`);
- [ ] `BRepCheck_Analyzer` reports valid;
- [ ] the solid's volume is **positive**;
- [ ] `|V_step - V_mesh|` <= **the LEGITIMATE rebuild delta** plus the engine's own
      predicted change:
      `SUM over rebuilt bands of V_band*(1 - (n/2pi)*sin(2pi/n)) + max(1e-4*V, 3*dVolPredAbs)`,
      with `n` measured from the MESH band. **CORRECTED 2026-09-06** — the first version
      compared a volume difference against `3*deflection/diag`, a LINEAR relative tolerance
      (3e-3 for every model): a volume judged by a length. It failed 7 models on both the
      frozen and the promoted engine; under the corrected form both `sample_0017`
      (dV 2312.08428) and `L01_rod` (dV 16.46407) match `dV_legit` to the last digit — they
      were correct rebuilds flagged for moving the volume by exactly what geometry requires,
      the same error pattern as the refuted n5a budget.
- [ ] **closure is judged RELATIVE TO THE INPUT MESH**: closed iff the mesh is closed.
      **P38 CONFIRMED**: all four closure-failing models have OPEN input meshes and their
      outputs mirror them exactly; no watertight input ever produced an open shell, so there
      is no engine defect here. On an open mesh the volume term is waived — volume is
      undefined — which is why `L07_flanged_bushing_recon` passes.

This gate would have failed n5a on its first model. No spec in this series may report a
revert-count improvement without it.

## 3. VERIFICATION COMMANDS

1. Lint: `/usr/bin/python3 -m ruff check src/mesh2step/canonize.py src/mesh2step/rebuild.py src/mesh2step/intent.py tests/test_canonize.py tests/test_rebuild.py tests/test_intent.py`
   — the new files must be clean; the touched files may not gain a single new `(file, code)`.
2. F2P: `/usr/bin/python3 -m pytest -q tests/test_canonize.py tests/test_rebuild.py tests/test_intent.py tests/test_webapp_browser.py -k "lost_circle or intent or canonize or rebuild"`
3. Corpus: the A/B scorer over the 57 models, redirected to a file under the session scratchpad
   and read from the file — never streamed into context.
4. P2P: as in §2, redirected to a file the same way (~12 min).

In that order. `/usr/bin/python3`, never `python`.

## 4. CONVERGENCE LOOP

Ceiling **8** iterations: EDIT (§1 scope) → EXECUTE (§3 in order) → PARSE failures → PATCH from
the diagnostics. Step 0 (locate corpus + scorer, measure baselines) and F2P authoring come
before iteration 1. On the ceiling without convergence: STOP, report the diff, the per-model
table and the unresolved cases. Partial convergence with an honest table beats a green claim.

## 5. TERMINATION CRITERIA (BOOLEAN GATES)

- [ ] Corpus and scorer located; paths and baselines in the report.
- [ ] All §2 F2P tests were red before and are green after, none edited after first commit.
- [ ] Corpus gate: ≥ baseline everywhere, > on ≥ 1, false rebuilds = 0.
- [ ] Every rebuild decision in `intent.py` is traceable to a number printed in the warning
      or logged in the RESULT payload.
- [ ] If a learned gate exists: coefficients in JSON, LOMO-CV accuracy and the decision band
      in the report; training reproducible from a checked-in script with a fixed seed.
- [ ] P2P: no regression against the recorded baseline. Lint: no new codes.
- [ ] `refs/`, `native.py` and the binary untouched (`git status` shows nothing there).

## 6. GUARDRAILS

- **Zero-Assumption Rule:** no completion claim without stdout and exit codes.
- **Never edit anything under `refs/`.**
- **No LLM, no network, no new heavy dependency** in the conversion path. Deterministic
  output: same input → same STEP, same warnings, byte for byte.
- **No silent fallback anywhere.** An exception in `intent.py` is a bug, not a reason to fall
  back to the old constants.
- **Blast radius:** minimal diffs inside §1. Do not refactor the STEP walker or the seamed-face
  constructor beyond what the evidence computation needs.
- **No git operations.** No commit, push, stash (except the red-check stash, restored
  immediately), checkout or branch. Leave the tree dirty for review.

## 7. REPORT BACK

Write `/tmp/n4-report.md` and print its path as your last line. Contents: corpus + scorer
paths; P2P and corpus baselines; the deterministic separation achieved by step 1 alone on the
corpus (how many of the ambiguous candidates it settles, and which remain); whether step 2 was
built, and if so its features, coefficients, LOMO-CV numbers and decision band; the per-model
A/B table before/after; the list of every warning text the new code can emit; the unresolved
cases, honestly. The user reviews the dirty tree and decides what to commit.

### P49 — REFUTED (measured 2026-09-06, binary sha 92c0a2, parity-gated vs v1.1.0-n5d)

Prediction: on L08_T_bracket_recon, triangles 727 and 730 were assigned to a region and later
removed by a refinement pass, leaving them owned by neither an emitted face nor the island —
"predict exactly two with neither".

Measured, per-triangle ownership map at emission:

| model | tris | face | island | orphaned | face+island |
|---|---|---|---|---|---|
| L08_T_bracket_recon | 884 | 2678 | 858 | 0 | 3536 = 884 x 4 |
| L07_flanged_bushing_recon | 738 | 1404 | 72 | 0 | 1476 = 738 x 2 |
| L06_adapter_plate | 1620 | 1620 | 0 | 0 | 1620 = 1620 x 1 |

The counters are process-global atomics that accumulate across buildFaces invocations, so the
multiplier is the cascade pass count. Within every pass, face + island = nTri exactly.

Consequence: ownership is already total and exclusive; no triangle is dropped. The proposed fix
(compute the island as the final complement of emitted regions) would assert an invariant that
already holds, so it is NOT written. L08's topological break must lie in the edge half of the
all-paths closure contract (free edges != 0 despite full face coverage), not the face half.
That is the next thing to measure, and it is a different prediction.

### P52 — the edge half of the closure contract (written before measurement)

P49 showed face coverage on L08_T_bracket_recon is total (face + island = nTri, 0 orphans), yet
P51 found it is the one topologically broken model in the corpus. Therefore the break is in the
edges, and the prediction is:

(i)  L08_T_bracket_recon's emitted shell has free edges (edge with exactly 1 adjacent face) > 0.
(ii) Those free edges lie on the interface between emitted analytic faces and the faceted island,
     not in the interior of either: the two sides are built by different code paths and are sewn
     by distance, so a chord/arc mismatch wider than sewTol leaves them unpaired.
(iii) The corpus control: every other model returns free edges = 0, i.e. this is not endemic.

Falsified if free edges = 0 (the break is then non-manifold rather than open), or if the free
edges are interior to one side (a builder emitting a torn face, a different defect).

### P49 — CONFIRMED after correcting my own instrument; mechanism relocated (n5h)

The first ownership map reported orphaned=0 and I recorded P49 refuted. That reading was an
artifact of two assumption bugs in the counter: `iid >= 0 || exp` credited exploded-region
triangles to the island without measuring re-emission, and ownership was read from `rg.tris`
(intent) rather than from what the emitted face consumed.

Measured from the STEP instead: 4 free edges forming a closed quadrilateral loop, which matches
input triangles 727 and 730 exactly (area 0.028058). The user's two triangles were right.

The mechanism is not in the region builder. The component's analytic rebuild is reverted
(smoothRevertedTrue=1) so buildFaces contributes nothing, and facesBeforeUnify = 884 = nTri.
The hole is opened by the second unify pass (smooth-flat), gated on the nTri 500-1200 band:

  --no-unify        884 faces  0 free edges
  first unify only  821 faces  0 free edges
  + smooth-flat     440 faces  4 free edges

Fix (n5h, fork branch n5h-unify-closure, commit 06af2ef): smooth-flat is transactional --
snapshot shape/parts/facesAfter, run, count free edges, restore and warn if the count rose.
Gate: 206 models, 203 byte-identical, 3 DIFF all closure repairs (20->0, 3->0, 4->0), 0
regressions, cylinders 325 -> 325. F2P test tests/test_n5h_unify_preserves_closure.py, red
against the installed v1.1.0-n5d, flips at promotion.

### P44 check (2) — CONFIRMED, after the counter was made real

Previous reading (0 across 84 models) was an artifact: the counters were never incremented.
Now counted inside meshTolCap at the derivation site, proven reachable first.
105 models: radius term binds in 68 (65%), 16566 applications, 100% wider than sewTol,
median widest 0.7498 mm, widest 15.8321 mm. n5e part (b) is justified by measurement.

### STANDARD — a zero is not a measurement until its increment site is proven reachable

Established 2026-09-06 after the third assumed-zero counter of the campaign (cap counters read
0 across 84 models, then 0 across 205, while nothing incremented them at all; before that the
cap probe serialised only inside revertCauses; before that the P49 ownership map answered from
its own assumptions). A counter reading zero and a counter that cannot fire are indistinguishable
from the outside, and the second is far more common than the first.

Rule: before reporting any zero, run the instrument on a case that MUST read non-zero and show
the non-zero. Only then is a zero elsewhere evidence of absence.

Stands beside the other two permanent gates of this campaign:
- parity-before-belief: an instrumented binary is compared byte-for-byte against the promoted
  one on known models before any of its numbers are believed;
- sha-named binary: every sweep copies the engine to a run-specific path with its sha256 in the
  name, so a mid-sweep rebuild cannot silently change what is being measured.
