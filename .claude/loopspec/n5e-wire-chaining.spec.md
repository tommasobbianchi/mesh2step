# n5e — chain joins by identity, vertex tolerance by measurement

## What the code already does (read before predicting, 2026-09-06)

- Chain terminals are already **mesh vertex ids**: `ia = ch.meshVerts.front()`,
  `ib = ch.meshVerts.back()`, seam vertex for closed loops (`refit_build.cpp:4124`).
  So part (a) is not "replace a distance test with an identity test" at this site; the
  identity is already there, and any distance-based joining must live downstream, in
  sewing or in the TVertex tolerances that let OCCT identify two distinct points.
- TVertex tolerance is already the **measured** deviation: `bumpVertexTol` sets
  `d * 1.001 + Confusion` where `d = curveResidual(...)`, and `snapVertexToCurve` refuses
  outright when `d > cap`. `ensureFaceValid` clamps with `min(d*1.001+Confusion, cap)`.
  So part (b) is not "measure instead of assume" -- it is "bound the measurement by the
  measured sagitta instead of by `0.2929*R`".
- `meshTolCap` takes `max(sewTol, chordSagitta, radius*(1-cos(pi/4)))`. The radius term is
  a FLOOR sitting above the measured sagitta: removing it leaves `max(sewTol, chordSagitta)`,
  which is exactly what (b) asks for. `partialFaceTolCap` already prefers the measured chord
  sag "when nSides was counted", so the precedent for the narrower cap exists in the tree.

## P54 — the faithful check (2), written before instrumenting

For each boundary endpoint pair on SpeedTestStructure, report: the distance between the two
mesh points, the cap applied at that site, and whether they ended up as one TVertex.

Prediction: **18 of 18** pairs merge, and in every one of them `distance <= cap` while
`distance > sewTol` -- i.e. the merge is bought entirely by the radius term of `meshTolCap`,
not by the sewing tolerance and not by the measured sagitta. Precedent: the one pair measured
by hand under P44 had a 0.0381 mm gap against a 0.11434 mm cap.

Falsified if any pair merges with `distance > cap` (something other than the cap is joining
them), or if fewer than 18 merge (the population is not what P41 identified).

## P53 in force

Faces that turn red under the honest cap are FIXED, not re-covered. A recall drop after (b)
is discovery, not regression -- and still a block on promotion.

## Gates (as for n5h)

MISSED_silent_wrong_rebuild = 0 on the 26 negatives; corrected 2b (v2) on 57 + 26 with no new
failure; parity or ID-independent geometric equivalence everywhere the output changes; every
already-building plate that changes reported by name.

### P54 — REFUTED twice, the second time with a correct instrument

Binary c122e66139d2 / the coordinate-emitting successor, both parity-gated against
v1.1.0-n5h before any number was read (L06, L08, L01 byte-identical).

**First measurement, wrong instrument.** I emitted `ia`/`ib` per chain and called them the
boundary endpoint pair. They are the two ENDS OF ONE CHAIN, not two endpoints that should
join: 2388 pairs, 0 within cap, distances up to 280.03 mm. The instrument answered a
different question than the check asked.

**Second measurement, correct instrument.** Terminal coordinates emitted, then every pair of
DISTINCT terminals compared:

| quantity | value |
|---|---|
| chains reporting terminals | 2388 |
| distinct terminal mesh vertices | 1067 |
| applied cap | 0.003479 .. 2.931862 mm |
| **distinct terminal pairs within the applied cap** | **0** |
| chains whose two terminals are the same vertex (`ia == ib`) | 0 |

**Consequence, and it redirects n5e.** On SpeedTestStructure no boundary endpoint pair is
joined by distance at all: every terminal is already a distinct mesh vertex and no two are
close enough for any cap to identify them. Part (a) -- "chain endpoints join on mesh-vertex
identity only" -- is therefore already true at this site, and has no work to do on the model
it was designed for. The 902 UnorientableShape failures (P35) are not caused by
distance-based endpoint joining.

The pinch population P41 found is not two vertices merged by distance; it is ONE mesh vertex
visited twice by a region's outer walk. That is an identity phenomenon, not a tolerance one,
and no change to the vertex cap can affect it.

**What this does NOT settle:** part (b). The cap still reaches 2.93 mm on this model and
16 566 applications corpus-wide are 100% wider than sewTol (§29). It is simply not what joins
these terminals. (b) must be justified -- or refuted -- on faces, not on endpoint merges:
the next measurement is per-face, `BRepCheck` verdict under the current cap versus under
`max(sewTol, chordSagitta)`, which is exactly what P53 predicts will turn some faces red.

## P56 — who raised the invalidating tolerances (written before the measurement)

P55 showed four edges of one SpeedTestStructure plate wire are invalid because they are short
relative to their endpoint tolerances (ratio 2.83 .. 13.10 invalid, 47.36 .. 1080 valid), and
that those tolerances (0.031 .. 0.072 mm) are 9-21x the plate's own cap (sewTol 0.003475).
They are `bumpVertexTol` values: MEASURED deviations between a mesh vertex and some region's
fitted surface. A large one means a fit that sits far from the mesh at a shared vertex.

Prediction: the regions that raised the four bumped vertices are **planar regions absorbing
near-flat curvature**, with absorbed-normal spread near the 2.0 deg gate, and with residual at
that vertex equal to the bump. Arithmetic that motivates it: a plane fitted across facets
spreading ~2 deg over 1-2 mm sides has vertex residuals of order 0.03-0.07 mm, which is the
observed range.

Check: one more column in the P55 dump -- per bumped vertex, the raising region's type, its
absorbed-normal spread, and the residual at that vertex.

Falsified if the raising regions are cylinders or fillets, if the spread is far from 2 deg, or
if the residual at that vertex does not match the bump.

If it holds:
- the successor is **n5g constant 2** (near-flat, self-calibrated from alpha), and
  SpeedTestStructure attaches to it: the same absolute 2.0 deg that moves L07's volume
  invalidates SpeedTestStructure's fine neighbours through shared vertices;
- **constant 2 precedes constant 1**: 246 cylinders (144 in band) outrank the 170 below band,
  102 of which sit inside SpeedTestStructure and stay blocked until it builds.

## The per-vertex bound is an ACCEPTANCE rule, not a clamp

If a region's fit needs a vertex bump that any incident edge cannot carry -- length/(tol1+tol2)
below the measured validity threshold -- then the FIT is the defect. Reject or refine that
region (`Reject::VertexResidual` exists; its threshold becomes relative to local edge length,
like every other constant). Never clamp the bump: clamping only moves the invalidity onto the
raising face, where it would be harder to see and would ship.

## P57 — which curve raises the bumps (written before the build)

P56 refuted the surface-residual story: no containing region's residual matches the bumps
(0.000173 .. 0.016437 against bumps of 0.058 / 0.072). The remaining raising site is
`snapVertexToCurve` -- deviation from an analytic CURVE fitted along the chain between the
near-flat micro-regions (508/513 at 2.0016 deg, 392/394 at 2.1394 deg).

Predictions, per bumped vertex:

1. the fitted curve is a **Line** (`AnalyticCurve::Lin`);
2. the residual at the terminal **equals the bump** to 1e-6, under the recorded transform
   `d * 1.001 + Precision::Confusion()`;
3. the chain's own **polyline sagitta** -- its true curvature computed from its own points --
   is of the same order as the residual: the chain WAS a curve, flattened to a line because
   the 2 deg gate made the regions on both sides planar.

Missing column, required: **the cap in force at the snap site**, and why it admitted 0.058 on
a vertex whose plate cap is 0.003475. The honest cap changed no byte on this corpus, so it was
NOT the radius term -- something else supplies the larger cap at this call.

**Coverage gate: the dump is not read until it is 3 of 3.** Three vertices qualify
(369 = 0.0720, 373 = 0.0570, 368 = 0.0581) and the last run reported two. Working hypothesis
for the gap, to be confirmed or discarded by the run itself: vertex 373's TVertex was RECREATED
(the uncollapse path recreates vertices because `UpdateVertex` cannot lower a tolerance), so its
TShape is no longer in `verts[]` and identity lookup returns -1. The instrument must report such
a vertex anyway, resolved positionally and LABELLED as such, never silently dropped.

## Region 242 — recorded correctly

A 170 deg normal spread on a cylinder is its ANGULAR EXTENT, not an anomaly: 10 facets at
~17 deg per facet, in band, a small hole. My reading of it as "not a cylinder by any measure"
was wrong -- spread is the wrong statistic for a cylinder. It is recorded as a candidate to be
judged by RESIDUAL (0.012 .. 0.016 on r ~ 0.4), not by spread.

## The acceptance rule (after P57, at the site P57 names)

A chain collapse whose terminal residual exceeds what any incident edge can carry keeps the
POLYLINE: no snap, no bump. `Reject::VertexResidual` becomes relative to local edge length,
like every other constant. Never clamp the bump -- that moves the invalidity onto the raising
face. Constant 2 upstream (near-flat, self-calibrated from alpha) remains the successor.

## P58 — the 0.07 mm is the CHOICE of line, not the geometry (written before the fix)

P57 showed the two bumping chains are perfectly straight (polyline sagitta 0.000000000) yet the
fitted plane|plane intersection line misses their terminals by 0.058 / 0.072 mm.

(i) A least-squares line through the chain's OWN points has terminal residual <= 0.005 -- the
    planes' own fit residual at those vertices from P56 -- against 0.058 / 0.072 for the
    plane-plane intersection.
(ii) Each bump ~= delta_plane / sin(dihedral) within 3x, with dihedrals 2.0016 and 2.1394 deg.

Both checkable from the existing dump plus P56's residuals. No new mechanism, no build.

## The fix (refit_build.cpp:4378, plane|plane branch)

Delete the rubber stamp `acceptCap = max(sewTol*50, 1.0)`, which raises the cap to the residual
and so admits anything under 1 mm. Replace with a choice made by residual against a MEASURED
budget:

1. use the intersection line only when it is WELL-CONDITIONED: terminal residual within the
   local budget = min incident edge length / K, K taken from the measured validity ratio
   (valid >= 47, invalid <= 13; K is the conservative end, and the boundary is recorded as
   measured, not invented);
2. otherwise use the line FITTED TO THE CHAIN'S OWN POINTS, with edge tolerance = the measured
   plane deviation along the chain;
3. if neither meets the budget, KEEP THE POLYLINE -- no snap, no bump.

No threshold is invented: the budget is measured from local edge length, and the line is chosen
by residual.

## Gate standard, from now on

Any tolerance change is gated on the FULL set (57 + variants + 26 = the 206), never the 84.
(b)'s "83/83 byte-identical" was true of the wrong set: SpeedTestStructure_coarse is outside it
and (b) did change that model. Per differing model: geometric equivalence, P53 in force (red
faces fixed, never re-covered), MISSED = 0, 2b v2, recall strictly up. Expectation for
SpeedTestStructure: 0 -> >= 144 in band.

## P55's claim — REFUTED by the P58 experiment (arm rewritten, claim not edited)

P55 concluded: "an edge is invalid when it is SHORT RELATIVE TO ITS ENDPOINT TOLERANCES"
(invalid ratios 2.83 .. 13.10, valid 47.36 .. 1080). The P58 rule lowered the two bumps to
0.002142 and 0.000173 and the SAME four edges stayed invalid, now at ratios 38.9, 35.2, 7841
and 949. Edge 6 carries 0.000173 of tolerance across 1.36 mm and still fails. Length-to-
tolerance was a CORRELATION.

Arm rewritten from the same table: invalid if and only if the chain was snapped to an ELLIPSE.

| edge | chain | kind | other region | valid |
|---|---|---|---|---|
| 2 | 181 | Elips | 394 (2.1394 deg) | no |
| 3 | 183 | Elips | 392 (2.1394 deg) | no |
| 6 | 182 | Elips | 513 (2.0016 deg) | no |
| 7 | 180 | Elips | 508 (2.0016 deg) | no |
| 0,1,4,5,8 | 177,178,186,185,179 | none (polyline) | 169 / island | yes |

Edges 6 and 7 had their snaps REFUSED (admitted=0) and carry no bump at all, yet are invalid:
refusing the bump does not undo the curve choice. The vertex tolerance and the bad ellipse are
two effects of one cause -- the near-flat micro-regions -- not cause and effect of each other.

## P59 — pending. The ellipse at the plane-cylinder site

Claim: the analytic curve is chosen without asking whether it FITS the chain it replaces, for
every kind, and Elips is where that hurts on SpeedTestStructure. P58 fixed one kind (Lin at
plane|plane); the rule belongs to all kinds.

Arms and predictions (status: pending; a refuted prediction rewrites its arm, never edited):

- **P59a** the ellipse from plane-cylinder is ill-conditioned: region 242 is r ~ 0.4 over 10
  facets, cut at a shallow angle, so the ellipse has a high aspect ratio, and ITS RESIDUAL AT
  THE CHAIN'S OWN POINTS exceeds the local budget (min incident edge length / 2K, K = 47).
  Predicted: residual at chain points > budget for all four chains 180-183.
- **P59b** region 242 is itself a bad fit: residual 0.012 .. 0.016 on r ~ 0.4 is 3-4 % of the
  radius, and a VertexResidual threshold RELATIVE TO LOCAL SCALE would reject it, turning
  chains 180-183 into plane|island polylines.
  Predicted: max vertex residual of region 242 / r >= 0.03.
- **P59c** parametrisation: the MakeEdge curve for those chains does not cover the chain's
  span (first/last parameter vs the chain terminals), which is the direct reason BRepCheck
  rejects the edge while every vertex is valid.
  Predicted: at least one of the four edges has a curve whose parameter range excludes a
  terminal, or whose 3D point at the terminal parameter is further from the mesh terminal than
  the edge tolerance.

One-command check (worker task W1): extend the env-gated wire dump with, per chain of the
dumped wire: curve kind, residual at EVERY chain point (max and median), the curve's parameter
range and the distance from its endpoint evaluations to the chain terminals, and for the
cylinder region of the pair, radius and max vertex residual / radius. Parity-gate the binary
against the current production baseline first; report a table; take no design decision.

## The rule this leads to (written before the measurement, so the fix is not shaped by it)

ONE curve-choice rule for every kind. An analytic surface-surface curve is used only if its
residual at the CHAIN'S OWN POINTS fits the measured local budget; else the curve FITTED
through the chain's points; else the polyline is kept -- no snap, no bump. P58's plane|plane
rule becomes the special case of it. No invented threshold: budget from local edge length,
choice by residual.

### P59 — RESULTS (W1, binary 95e986b35b72, parity SAME on L06 and L01, coverage 9/9)

| chain | kind | regA | regB | nPts | residMax | residMed | budget | endGapA | endGapB |
|---|---|---|---|---|---|---|---|---|---|
| 177 | none | 242 | 169 | 2 | -- | -- | 0.016772 | -- | -- |
| 178 | none | -1 | 242 | 2 | -- | -- | 0.012359 | -- | -- |
| 181 | Elips | 242 | 394 | 3 | 0.147121 | 0.124542 | 0.003475 | 0.033254 | 0.147121 |
| 183 | Elips | 242 | 392 | 3 | 0.159188 | 0.043691 | 0.003475 | 0.159188 | 0.030540 |
| 186 | none | 242 | -1 | 2 | -- | -- | 0.011057 | -- | -- |
| 185 | none | -1 | 242 | 2 | -- | -- | 0.011943 | -- | -- |
| 182 | Elips | 513 | 242 | 3 | 0.102762 | 0.056947 | 0.003475 | 0.102762 | 1.338346 |
| 180 | Elips | 508 | 242 | 2 | 0.160004 | 0.132122 | 0.003475 | 0.160004 | 0.620958 |
| 179 | none | -1 | 242 | 2 | -- | -- | 0.003475 | -- | -- |

Region 242 throughout: radius 0.201164, max vertex residual 0.020753.

**P59a CONFIRMED 4/4.** Every ellipse's residual at the chain's OWN points exceeds the local
budget by 30x to 46x (0.102762 .. 0.160004 against 0.003475).

**P59b CONFIRMED, worse than predicted.** 0.020753 / 0.201164 = **10.3 %** of the radius, not
the 3-4 % predicted -- the prediction was made from r ~ 0.4 read off P56's residuals; the
measured radius is 0.201164. The arm stands and its magnitude doubles.

**P59c CONFIRMED.** Curve endpoints miss the chain terminals by up to **1.338346 mm** (chain
182, on an edge 1.358833 mm long -- the curve end lands at the far terminal) and 0.620958 mm
(chain 180, on an edge 0.164444 mm long -- 3.8x the edge). Against an edge tolerance of 1e-7.

The four ellipse chains are exactly the four invalid edges; the five polyline chains are
exactly the five valid ones. The rule written before this measurement is unchanged by it.

**Split out as a SEPARATE defect (one defect per commit):** region 242 is accepted as a
cylinder at 10.3 % radius residual. A `Reject::VertexResidual` threshold relative to local
scale would reject it and the four chains would never be plane|cylinder pairs at all. That is
an upstream fix and belongs with the n5g relative-threshold work, not with the curve rule.

### The general curve-choice rule — W2 result (binary 75f1c4f1d7ca, parity SAME on 4 models
### under BOTH default and --smooth)

The rule replaces P58's plane|plane block and applies to every kind: analytic curve accepted
only if its residual over ALL the chain's own points fits the local budget; else the fitted
line if that fits; else the polyline is kept. No new constant.

| model | binary | builtPlanes | builtCyl | revertedComponents | facesAfterUnify | watertight | bytes |
|---|---|---|---|---|---|---|---|
| SpeedTest coarse | W2 | 0 | 0 | 1 | 3091 | true | DIFF |
| SpeedTest coarse | n5h | 0 | 0 | 1 | 3624 | true | -- |
| SpeedTest normal | W2 | 0 | 0 | 1 | 5064 | true | SAME |
| SpeedTest normal | n5h | 0 | 0 | 1 | 5064 | true | -- |

**What the rule achieved (local, real):** on SpeedTestStructure_coarse NO wire fails its own
BRepCheck any more -- the wire dump emits nothing where the baseline emitted a 9-edge failing
wire. The revert cause changed with it:

  baseline: buildFaces-false exit=j6-uncollapse regions=744
            rejects[ChordConsistency*=6, FaceBuildFailed=76, GaussPlanarity*=1,
                    None=668, VertexResidual*=28]
  W2:       counted-not-reverted usedRefit=true cyls=0 planCyl=151 planPl=593
            smoothRevertedTrue=0  smoothAdoptedNoCyl=1

So the component no longer reverts through J6 at all. The four bad ellipses are gone and the
plate's wire is valid.

**What it did NOT achieve:** recall is still 0. The blocker MOVED rather than lifted -- from
"a wire fails BRepCheck, J6 uncollapses, the component reverts" to "the refit is ADOPTED, the
plan holds 151 cylinders and 593 planes, and 0 of either is built". The F2P
(`test_the_component_stops_reverting`, built > 0) is still red.

Per the handover's own instruction, the next object to dump is therefore NOT another mesh
prediction: it is the plan-to-build gap itself.

### Instrument defect in MY specification (orchestrator error, recorded as such)

I specified `g_bfSkips[-60]` and `[-61]` for the two rejection paths. Those keys are ALREADY IN
USE at refit_build.cpp:2708-2709 by an inner-wire census. W2 implemented exactly as specified
and flagged the collision rather than silently choosing other keys -- correct behaviour. The
collision is inert on the models measured (the baseline shows no -60/-61 key at all, so the
census contributes 0 there) but it makes the counts ambiguous on any model with inner wires,
and it must be fixed before anything is committed. Reachability was still proven: -60 = 396 and
-61 = 291 on SpeedTestStructure_normal, -60 = 60 and -61 = 198 on clamp_half_a_normal.

## P60 — pending. The plan-to-build gap

Claim: on SpeedTestStructure the cascade PLANS 151 cylinders and 593 planes and BUILDS none of
them, while the component is adopted rather than reverted. Something between plan and emission
discards every planned region, and it is not J6 and not wire validity.

Predictions (pending):
- **P60a** the 151 planned cylinders are rejected individually before emission, and the
  rejection reasons are already counted: the reject histogram on the ADOPTED path (which the
  current diagnostic does not print, because it prints only on the revert path) is non-empty
  and dominated by one reason.
- **P60b** that dominant reason is NOT FaceBuildFailed (the baseline's 76 came with the
  now-fixed wire defect) but one of ChordConsistency / VertexResidual / GaussPlanarity --
  i.e. a GATE, not a build failure.
- **P60c** region 242's 10.3 % radius residual is representative, not exceptional: the median
  planned-cylinder radius residual on this model exceeds the VertexResidual gate's own
  threshold, so a relative-scale threshold changes which regions are planned at all.

One-command check (worker W3): print the reject histogram and the per-region outcome on the
ADOPTED path too, not only on revert; for the 151 planned cylinders report id, radius, max
vertex residual, residual/radius, reject reason, and whether a face was emitted.

### P60 — RESULTS (W3, binary 3c7a329784a7, parity SAME vs W2 on L06 and L01 under --smooth)

The two SpeedTestStructure variants turn out to be TWO DIFFERENT DEFECTS. Keeping them apart is
the finding.

**coarse — every planned cylinder is a bad fit and none builds**

| pool | total | emitted | not emitted |
|---|---|---|---|
| Plane | 593 | 482 | 111 |
| Cylinder | 186 (151 planned + 35 pre-rejected) | **0** | 186 |

reject histogram: None 482, **FaceBuildFailed 262**, VertexResidual 28, ChordConsistency 6,
GaussPlanarity 1. Note 262 = 111 planes + 151 cylinders exactly: every planned cylinder fails.
Cylinder residual/radius over the 151 fitted: min 0.000001, **median 0.129167**, max 0.129270,
**148 of 151 above 0.03**. The top rows are 4-triangle cylinders of radius 0.153228 with
residual 0.019808.

**normal — the cylinders BUILD, and the component throws them away**

| pool | total | emitted | not emitted |
|---|---|---|---|
| Plane | 542 | 521 | 21 |
| Cylinder | 303 (183 planned + 120 pre-rejected) | **178** | 125 |

reject histogram: None 699, **ChordConsistency 114**, FaceBuildFailed 26, VertexResidual 5,
GaussPlanarity 1. Cylinder residual/radius over the 183 fitted: min 0.000000,
**median 0.000022**, max 0.153829, 78 above 0.03.

**P60a CONFIRMED on coarse** — one reason dominates and it rejects every planned cylinder.
**P60b REFUTED** — the dominant reason IS FaceBuildFailed, not a gate. The prediction assumed
the baseline's 76 FaceBuildFailed came with the wire defect; on coarse it is 262 and it is the
whole story.
**P60c CONFIRMED on coarse, REFUTED on normal** — region 242's 10.3 % is representative of
COARSE (median 12.9 %, 148/151 over 3 %) and utterly unrepresentative of NORMAL (median
0.0022 %). The two variants do not share a population and must never again be quoted together.

**The recall blocker on _normal is now named and it is not what any prediction so far said:**
buildFaces EMITS 178 cylinder faces, and RESULT still reports smoothBuiltCylinders = 0 with
smoothRevertedComponents = 1. The component-level revert discards 178 successfully built
cylinder faces. That is the object to dump next -- the revert decision itself, on _normal --
and it is worth more than everything upstream of it: 178 faces already built and thrown away,
against a target of 144 in band.

## P61 — pending. The component-level revert on SpeedTestStructure_normal

Claim: on _normal the analytic rebuild succeeds at face level (178 cylinders + 521 planes
emitted) and is then discarded wholesale by the component-level accept/revert decision.

- **P61a** the revert is decided by a single comparison whose inputs can be printed (a volume
  or deviation test against a budget), not by a build failure.
- **P61b** the discarded rebuild is BETTER than the faceted fallback by the measure the gate
  itself claims to protect (volume error against the mesh), i.e. the gate is rejecting a
  correct result.
- **P61c** the 114 ChordConsistency pre-rejections on _normal are a separate population from
  the revert and would not be fixed by fixing it (n5f).

Check (worker W4): print, on both paths, every input to the accept/revert decision for
SpeedTestStructure_normal -- the measured quantity, the budget it is compared against, where
each comes from -- plus the volume error of the analytic result versus the faceted fallback
versus the mesh. No fix in the same task.

### P61 — RESULTS (W4 finished by the orchestrator, binary a7953c0bf050, parity OK vs W3)

    comp=3303 decision=REVERT hasPlan=1
    builtFaces=0 builtCyl=0 builtPl=0 regions=725
    bfReturned=0 bfExit=j6-uncollapse firstFail=t1_bfReturnedAndNonEmpty
    t2_shellIsClosed=-1 t3_brepCheckIsValid=-1 t4_volumeBudget=-1
    volMesh=3185754.54 volAnalytic=-1 volFaceted=3185754.54

Controls: coarse decision=KEEP (builtFaces=3367, builtCyl=0, all four tests pass),
L06_adapter_plate decision=KEEP (builtFaces=20, builtCyl=14). The KEEP path is reachable and
was observed, so REVERT is a measurement and not an artifact of a dead branch.

**P61a REFUTED.** The discard is not a component-level comparison against a budget. buildFaces
RETURNS FALSE at exit `j6-uncollapse` and clears its own output; the caller sees zero faces and
tests 2, 3 and 4 are never evaluated. The 178 cylinder faces W3 saw with emitted=1 are built
INSIDE buildFaces and then thrown away by their own producer.

**P61b UNTESTABLE as written**, and recorded as such rather than as a refutation: volAnalytic is
-1 because no shell survives to be measured. The comparison "is the discarded rebuild better
than the faceted fallback" cannot be made at this point in the code; asking it requires
capturing the shell before J6 discards it.

**P61c** untouched (the 114 ChordConsistency pre-rejections remain a separate n5f population).

### Instrument defect found and fixed in the same run (mine to own)

W4's line was built into `char l[1024]` with the UNBOUNDED causeTag (it embeds the plate census
and the whole skip histogram) printed FIRST. On SpeedTestStructure_normal the causeTag alone
overflowed the buffer, so every numeric field after it was silently truncated -- the line still
looked well formed and the entire measurement was absent. First reading of it reported all
fields "(absent)" and would have been unusable. Fixed by moving the unbounded field LAST and
sizing the buffer at 65536. Rule reaffirmed: an instrument that can drop fields silently is not
a measurement, and a truncated line is indistinguishable from a phenomenon that did not occur.

## P62 — pending. J6's uncollapse: what the discard protects

Named site: buildFaces' `j6-uncollapse` exit (refit_build.cpp, the J6 block that runs when
`wasClosed && !shClosed`). Per the method, the next step is to read that site whole and dump
its own object -- NOT to predict from the mesh again.

- **P62a** J6 fires because the analytic shell is not closed after sewing, and the uncollapse
  pass is a repair attempt that fails; the discard is its failure path, not a quality gate.
- **P62b** the free edges J6 is reacting to are a small, nameable set (as on L08, where the
  whole defect was 4 edges), not a diffuse property of 725 regions.
- **P62c** what the discard protects is the closure contract: shipping the analytic shell as-is
  would produce an open solid. If so the fix is to close those specific edges, never to bypass
  J6 -- and the n5h precedent applies exactly (a consolidation that breaks closure is reverted
  transactionally rather than shipped).

Check: dump J6's own object at that exit -- free edge count, which faces/regions they bound,
whether they are analytic|analytic, analytic|facet or facet|facet, and what the uncollapse pass
attempted and why it did not close them.

### P62 — RESULTS (binary a7953c0bf050, parity OK)

Two J6 visits on SpeedTestStructure_normal (5964 triangles, 2984 vertices, 1 component --
under the nTri < 10000 guard, so the heal DOES run):

| visit | freeEdges | faces | recover |
|---|---|---|---|
| 1 | **444** | 2325 | 0 |
| 2 | **4** | 2540 | 2 |

**P62a CONFIRMED** by reading the site whole: the discard is the FAILURE PATH of a repair, not a
quality gate. `if (j6UncollapsePass > 0) { warn; restoreShared(); out.clear(); return false; }`.
**P62b CONFIRMED**: the residue is 4 free edges -- the same order as L08's 4 -- not a diffuse
property of 725 regions.
**P62c** stands: what the discard protects is the closure contract, and that is legitimate. The
fix must close those 4 edges, never bypass J6.

The heal reduces free edges by 99.1 % (444 -> 4) and its result is then thrown away in full:
2540 faces, including the 178 built cylinders, discarded over 4 edges.

## P63 — pending. The uncollapse pass limit is an absolute constant

`j6UncollapsePass < 1` permits exactly ONE heal pass. Measured: one pass takes 444 -> 4. The
limit is an absolute threshold of the same class as the 5 deg seed floor and the 2 deg near-flat
gate, and it is the reason a 99.1 % successful repair is discarded.

- **P63a** a second heal pass reduces the residue further; predicted freeEdges after pass 2
  strictly below 4, and plausibly 0.
- **P63b** if it reaches 0, buildFaces returns true, the component is KEPT, and
  smoothBuiltCylinders on SpeedTestStructure_normal goes from 0 to a number of order 178 --
  covering the 144 in-band target.
- **P63c** the risk named in the source comment ("Body11, 15300 tris: mixed uncollapse +
  abort-recover zeroes the 127-cyl floor") is guarded by the EXISTING nTri < 10000 condition,
  which Body11 fails; so raising the pass limit cannot reach Body11 by construction. Predicted:
  Body9/12/18/20 and Body11 unchanged.

Falsified if pass 2 does not reduce below 4 (the residue is not of the kind the heal addresses),
or if any Body* model changes.

The change under test is the LIMIT ONLY -- no new mechanism, no widened tolerance, no bypass of
the closure contract. If the shell still is not closed after the last permitted pass, the
discard stands exactly as now.

## P64 — pending. Endpoint coverage, not interior residual (from the Rule 8 second opinion)

Two measurements of the bad ellipse were taken in P59 and only one was used:
  (a) interior residual 0.10 .. 0.16 mm against a 0.0035 mm budget  -- a RATIO argument, the
      same correlational shape as the refuted P55 ratio and the arbitrary K = 47;
  (b) the curve's parameter range ends 1.338346 mm from the chain terminal on an edge
      1.358833 mm long -- i.e. the edge cannot reach its own endpoint vertices.

(b) is not a tolerance claim at all: no vertex tolerance can make a curve pass through a point
it does not approach. BRepCheck rejects exactly that shape. The rule was built on (a), the
weaker of the two, and it has now failed twice.

Claim: endpoint coverage separates the populations that interior residual conflates. The small
lead-fillet cylinders on the fine meshes need curves that DEVIATE in the interior (their
surfaces are fitted to the same mesh, so the interior residual can exceed any mesh-derived
budget) but that DO pass through both terminals.

- **P64a** on NEG_SC-59_fine, NEG_SOT-143_fine and NEG_TSOT-23_fine the chains carrying the
  true lead-fillet cylinders have max(endGapA, endGapB) small -- within
  max(sewTol, chain chordSagitta) -- while their interior residual exceeds the K=47 budget.
  That is why the interior-residual rule kills them.
- **P64b** on SpeedTestStructure the four bad ellipse chains have max(endGapA, endGapB) far
  outside that gate (measured: 1.338346 and 0.620958 mm).
- **P64c** therefore a gate on endpoint coverage alone rejects the four bad ellipses and keeps
  the fine-mesh fillet curves.

Falsified if the fine-mesh fillet chains also show large endGap (then endpoint coverage does not
separate them either, and the whole pre-emptive-veto approach is wrong -- in which case the
fallback is the oracle route: build the face, let BRepCheck judge it, and ban the culprit chain
per-chain via the existing fallbackBanned/collapseBanned ledger).

Check with the EXISTING DIAG_CHAIN instrument (it already emits residMax, budget, endGapA,
endGapB per chain). No new mechanism, no build.

### P64 — REFUTED (n5m, binary 29dd3fa342ee). Endpoint coverage does not separate either.

| population | n | residEnds med / max | residInterior med / max | ends outside max(sew,sag) |
|---|---|---|---|---|
| NEG_SC-59_fine rejected | 61 | 0.014787 / 0.511402 | 0.000000 / 0.256597 | 61 (100 %) |
| NEG_SC-59_fine accepted | 99 | 0.000000 / 0.000000 | 0.000000 / 0.000000 | 0 |
| SpeedTest_normal rejected | 3466 | 0.018665 / 1.341694 | 0.000000 / 0.155408 | 2966 (86 %) |
| SpeedTest_normal accepted | 1241 | 0.000001 / 0.002308 | 0.000000 / 0.001163 | 0 |

**P64a refuted**: 100 % of the fine-mesh chains the rule kills ALSO miss their terminals.
**P64c refuted**: a gate on ends alone rejects exactly the same curves.
Note residInterior is 0.000000 median in the rejected population -- the interior-residual rule
was ALREADY an ends rule in effect, which is why the second opinion's proposal would have
reproduced the regression.

**What the data actually says.** The engine INTENDS to accept curves that miss their terminals:
that is what snapVertexToCurve / bumpVertexTol are for -- the TVertex tolerance is widened to
cover the gap. v1.1.0-n5h builds those 12 true lead-fillet cylinders using curves that miss by
0.014787 mm median. The rule vetoes what the design absorbs by construction. And the
distributions overlap (fine-mesh max 0.511402 against the bad ellipse's 1.341694), so NO
pre-emptive magnitude threshold separates the populations. Every budget tried failed at one end
or the other because a pre-emptive veto is the wrong instrument, not because its constant was
wrong.

## The route this closes on (per P64's own falsification clause, and independently the
## second opinion's conclusion)

STOP PREDICTING THE ORACLE. The codebase's validity oracle is BRepCheck on built shapes, and it
already runs downstream (finishPartial -> faceIsValid -> pcurves -> ShapeFix_Face ->
ensureFaceValid). The pre-emptive rule tries to predict that verdict one stage early, where the
face does not exist, and it has now failed with three different budgets.

Instead, extend the pattern the dual-face incidence guard already uses at
refit_build.cpp:4959-4992: when a built face is BRepCheck-invalid, ban the COLLAPSED CHAIN whose
edge carries the failing status -- `fallbackBanned[ci] = 1; collapseBanned[ci] = 1;
collapsed[ci] = 0; geom[ci] = {}; restoreShared(); goto try_rebuild;` -- per chain, never per
region. Per-region explosion is what the comment at 4564-4566 warns eats Body11's 127 cylinders;
per-chain banning is the targeted form and the machinery exists.

Underlying asymmetry, named by the second opinion and consistent with every measurement here:
accepting an analytic curve routes failure to CLOSED-BUT-INVALID (the cascade handles it);
keeping a polyline routes failure to OPEN SHELL, and the J6 heal is structurally blind to the
chains that caused it. That asymmetry is why the two ends could never be balanced by a constant.
