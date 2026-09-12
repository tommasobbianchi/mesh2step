# n14 — External prior art: every adoptable contribution to mesh2step, ranked

Compiled 2026-09-12 from three code studies (upstream `BlinkingSun/stl2step` @ `6b52ba9`,
`CNCKitchen/ScanRuler` @ v0.4.1, `nico-schluter/ReverseReloaded` @ `be3c9ea`) plus the
literature they cite. Every entry names the mechanism, the source, **which of our MEASURED
defects it addresses**, and the gate that would prove it. Nothing here is adopted yet.

Baseline to beat: **CADScore 71.95** (recall 60.42%, precision 88.92%, matched 313/518,
built 352), valid closed solids 200/203 normal, 74/78 fine.

## 0. Our measured defects, so impact claims stay anchored

| D | Defect, as measured | Where |
|---|---|---|
| D1 | The cascade destroys more cylinders than fitting fails to find: across 203 models, 50 regions genuinely fail to fit, 160 are exploded, **110 never failed a build**, 46 of those match truth by radius | n13 trace |
| D2 | A component's shell is reported open because an edge is **duplicated**, not missing; merging it closes the shell but leaves `BRepCheck_UnorientableShape` | §13-§16 |
| D3 | `valve_body` fabricates ~113 blend slivers: 123 cylinders on 121 axis-lines all at R=2.0, L3/L1=0.2045 isotropic, 51 directions, median member area 1.40 vs max 113.1, one negative area | §8 |
| D4 | Detection gap on small bores: `gancio_parametric` finds 5 regions against 25 truth faces, R=0.8-1.5 at 0.036 mm deflection | arm D |
| D5 | t4 is load-bearing: removing it costs -7.59 (precision 88.92 -> 62.73), so recall cannot be bought by loosening adoption | §7 |
| D6 | `BRepGProp::VolumeProperties` can be 4.2% wrong on a closed, manifold, BRepCheck-valid shell | §4 |
| D7 | `L09_clamp_normal` writes a STEP it cannot re-read (`stepVolumeMM3 = 0`) | filed |

## 1. FIRST, AND LARGEST: our reference spec is 10 days stale

`refs/stl2step` is a **depth-1 clone pinned at `7cf77a2` (2026-08-30)**; upstream HEAD is
`6b52ba9` (2026-09-09). Verified independently: `src/refit_build.cpp` **4 605 -> 17 079 lines**,
387 function symbols upstream that do not exist in `refs`, and they are concentrated in
**pcurve birth/binding on shared edges, UV wire orientation, and free-edge attribution** — D2
and D1 exactly.

`refs/` is protected by standing rule (never edited or deleted), so this needs Tommaso's
decision. Two options, and the second needs no permission:
 1. unshallow and move the pin (changes `refs/`, needs approval);
 2. keep `refs/` frozen and read upstream from a scratchpad clone, treating it as the newer
    spec — already done for this document.

### 1a. `collectNonRegionNeighbourhood` — the single highest-value port (addresses D1)

Upstream `src/refit_build.cpp:12793`, called at `:16982`. **Absent from `refs/` (0 hits).**

An invalid face belonging to NO region — an island facet or `E'` fill triangle, `builtRid < 0`
— is skipped by both `collectFaceCulprits` and `collectShellCulprits`, so the culprit set comes
back **empty**; an invalid shell with an empty culprit set falls through U0 and U1 in one decide
and lands on the U2 blanket, which explodes every non-closed360 analytic region. The author's
own measurement, in the comment: *"on the plate one unorientable facet took out 9 partial
cylinders (the R10 cross bore, R30 x2, R17 x2, R5 x4) that had each built VALID."*

Fix: such a face contributes only its **neighbourhood** — the regions whose built faces share
an edge with it — and nothing else. RULE 1.5's 50% saturation test still runs on that set.

This is D1 diagnosed and solved by the author of the reference. It is self-contained (~60 lines,
one call site) and needs no new concepts. **Do this first.**

### 1b. Verify our cascade ladder is actually the reference's (addresses D1, D5)

The U0/U1/U2 ladder **is already in our pinned `refs`** (`CascadeRung` at
refs/.../refit_build.cpp:3051, `selectU0Explode` :3415, `cascadeLadderPlan` :3495,
`collectResidualCulprits` :3280). Our `docs/PORT-MAP.md` records the firewall rule as "when
construction fails, revert **wholesale** (R2)" — but in the reference wholesale R2 is the
**last rung after the ladder saturates**, not the policy. If our port reverts wholesale, that is
a **port gap, not fidelity**. Check before building anything new: `isHubPlane` (a plane sharing
a chain with more than half the component's cylinders must not be exploded as collateral), the
one-hop rule that never takes a `closed360` cylinder, and the 50% saturation brake with greedy
trimming.

### 1c. Per-region volume attribution instead of a component verdict (addresses D5, D6)

Upstream `collectResidualCulprits` (`:13285-13357`): per region, `vface` summed over that
region's built faces minus `vchord` from `regionChordVol`, compared against the region's **own**
predicted defect — `max(1e-4*|meshVol|/nAnalytic, 3*|dVolPredicted|, 1.05*|resid|)` — with two
de-fusing rules (a plane with `|dVolPredicted| < 1e-6` is skipped; `|vface| < 1e-3` while
`|vchord| > 1` is "a measurement miss, not a landmine") and the actuator firing only on the
landmine class `|dVol| > 100`.

This converts "the volume is wrong, reject the component" into "region 11 is wrong, revert
region 11" — which is the acceptance criterion D5 says we need, and it sidesteps D6 by comparing
a region against its own closed-form prediction rather than trusting one global GProp number.
Needs `dVolPredicted` per region per family: `dVolCylinderSector` (refit_grow.cpp:1070,
refit_fillet.cpp:1580, refit_ngon.cpp:768), prism slab `0.5*R^2*(theta - sin theta)*h`
(refit_prism_build.cpp:577), cone (refit_cone_math.hpp:274-295), torus (refit_torus.cpp:800).

### 1d. The five boundary-curve fallbacks, made explicit (addresses recall + precision)

`intersectSurfaces`, upstream `:2395`. Most are already in our `refs` spec (`:559`, `:759`,
`:785`) — **check before implementing**. The set: loosened-residual retry on <=3-vertex chains;
`constructedGenerator` on a side-grazing plane|cyl (re-measuring the geometry instead of
trusting the `tangent` flag, which misses when `|dist-R|` sits between the fit residual and the
`epsPlane` floor); `constructedPlaneCylCap` when IntAna misses a cap; **preferring the fitted
iso-circle over an IntAna ellipse on a perpendicular cap plane**; `constructedCylCylGenerator`
on near-tangent cyl|cyl (the fillet|bore case where the analytic intersection is legitimately
empty); `bestCylCylConstructed` on parallel offset. Plus: a constructed off-surface curve is
**logged, not discarded** — orphan rejection is deferred to the free-edge ledger.
And the pair-aware acceptance residual `intAnaAcceptResidual` (`:1475`): cyl|cyl gets 4x the fit
residual, 5x on coarse chains — the curve tolerance derives from how well the two surfaces
themselves fitted.

### 1e. Topology by construction: the shared-edge pool (addresses D2 at the root)

The reference never creates two coincident edges. One `TopoDS_Vertex` per mesh vertex and one
`TopoDS_Edge` per mesh edge are built **before any face** (`:14513-14542`); a region's wire is
*addressed* by `(chainIdx, reversed)` and resolved through `loopChainHandedEdge` (`:3027`),
which hands the second region `TopoDS::Edge(g.edges[n-1-k].Reversed())` — **the same TShape,
reversed**. The chain owns the edge; there is nothing to pair. In the clean case the shell is
assembled with a bare `BRep_Builder` and **no sewing at all** (`src/stl2step.cpp:823-829`);
`BRepBuilderAPI_Sewing` + `ShapeFix_Shell` are the dirty-mesh repair path only.
Upstream adds `birthMeshEdgePlanePCurves` (`:8209`) so pcurves are born on the shared edge
before the faces exist, with deviation measured (`pcurveDev`, `maxDevPcurveVs3d`) and a hard
rule never to inflate a shared TShape past the mesh budget (`:1029`).

**This is the real answer to D2.** Our sew-after-the-fact (§15) was treating a symptom: if our
port builds edges per-face anywhere, that is the bug, and no amount of sewing fixes it properly.

### 1f. A component that cannot close is exported as an OPEN SHELL with a warning, never dropped

`src/stl2step.cpp:812-818`. The only drop is when sewing returns null. If our port discards such
components, every cylinder in them is lost for nothing — D1 again, from a different direction.

## 2. ScanRuler (AGPL-3.0-only — restate mechanisms, never copy lines)

Caveat that scopes all of it: **ScanRuler is user-seeded, one element per click**
(`store.ts:1370`, `selection.ts:2-8`). Its gates only ever had to reject a mis-click, so they
are permissive for an unsupervised enumerator; its *growing* and *peeling* port cleanly because
they answer "where does this surface end".

### 2a. Arc coverage = 360 deg - widest angular gap (addresses D3 AND D4) — best single idea

`fit/extents.ts:14-48`. Project to the plane normal to the axis, take every point's `atan2`,
sort, find the **widest angular gap**, coverage is the complement. Gate: **>= 29 deg**, with the
rationale "under ~30 deg of arc the circle through the points is barely curved, so the radius
and the axis position are guesses". The stated reason for this *definition*: unlike counting
occupied bins, **it does not shrink because the mesh is coarse** — a 12-facet bore scores ~360.

Why it is our best candidate: it is one metric that cuts both ways on two different defects. It
admits D4's small bores (coarse but fully wrapped) and rejects D3's slivers (fine but barely
curved), without touching t4 — so it does not risk D5's -7.59.

### 2b. The normal-covariance axis with a refusal clause (addresses D3, D4)

Axis = eigenvector of the smallest eigenvalue of the **unit-normal** scatter matrix, because
every normal of a cylinder is perpendicular to its axis — "a far better starting guess than
anything derived from the point positions alone". It **refuses** when the second-smallest
eigenvalue is not `> 1e-6*n`: "the axis would be a coin toss". That refusal is itself a sliver
detector, and it is the same `sum(n n^T)` tensor we already compute for the blend test (§8) —
so the cost is low and the overlap is known.

### 2c. Rim peeling (addresses D3 partially — read the caveat)

`fit/regionGrow.ts:92-153`. Per-vertex statistic: `|cos|` between the mesh normal and the
**model's** normal there. `noiseTilt = acos(median over every region vertex)`; limit
`cos(max(2*noiseTilt, noiseTilt + 0.5 deg))` — **self-calibrating on the surface's own noise**,
medians on both sides. Ring 0 = region vertices with >=1 neighbour outside; each next ring
recomputed from freshly-reduced membership. Peel a ring iff the **ring's median** tilt exceeds
the limit. Caps: <=6 rings, never below `max(60, n/2)`, stop at the first interior-looking ring.
Runs **once, after growing converges**, and only if the region did not hit the growth cap (a
capped region's rim is the BFS frontier, not an edge). Author's reason for keeping it outside the
loop: the band that decides where a surface ends stays the one calibrated against GOM's
selections and is not tightened by its own trimming.
Measured by the author: Ø6.76 bore cylindricity 0.203 -> 0.135 mm, bias on synthetic
rounded-edge parts under 1.5 um.
**Caveat: this prevents a good face being contaminated by a blend. It does NOT classify a
standalone sliver as not-a-cylinder, so on its own it will not delete D3's 123 patches.**

### 2d. Region growing: dual membership test, refit every round, retractable BFS (addresses D3, D4)

Neighbour admitted iff `|residual| <= band` **AND** `align >= cosMax` (NaN residuals fail
deliberately). Angles: cylinder/cone 32 deg, sphere 38 deg, plane 25 deg. Band
`max(3.5 sigma, 0.004*r)` for revolved families, `max(3.5 sigma, 2e-4*bboxDiag)` for planes
("a plane has no size of its own"). Refit every round with k=3 clipping.
**The BFS restarts from the seed each round** with the improved model, capped at
`max(6000, 3*prev)`: stated in code as "so a bad early model cannot flood the whole mesh before
the fit corrects it", and the deeper consequence is that growth becomes **retractable** — a
vertex admitted under a bad early model is not permanently in, which a continuing BFS can never
undo. Converges after >=3 rounds when growth `<= max(3, 0.002*prev)`; <=30 rounds.

### 2e. Robust noise and clipped refit (addresses D3)

`sigma_hat = 1.4826 * median|res|`; inliers within `max(3*sigma_hat, diag*1e-5)` — the floor
exists so a clean patch does not gate on zero. Final fit: fit -> drop beyond `k*sigma` -> refit,
<=12 rounds, k=3, reporting sigma (RMS) and span (form error). Each cylinder round re-fits the
circle **on the previous round's axis** rather than restarting.

### 2f. Seeding, for D4 specifically

LMedS: 256 candidates, each scored by **median** |residual| over a strided subset of <=512
points — no threshold to tune. Candidate axes: the deterministic normal-covariance axis scored
first, then 256 two-points-with-normals candidates (`axis = n0 x n1`, rejected if
`|n0 x n1| <= 0.08`, position from intersecting the two projected normal lines). Multi-scale
patch retry **1500 -> 6000 -> 24000**, and the patch collector is a plain connectivity BFS with
**no** membership test — the seed finder is given the raw contaminated neighbourhood on purpose.
There is a commit "centre the circle kernel on its points so short arcs far from the origin
still fit" — directly relevant to small bores away from the origin.

### 2g. Axial-window re-fit (addresses D3's flared-mouth class)

Drop region vertices outside an axial `[lo, hi]` window measured off the fit already in hand,
re-fit on the remainder; the excluded band is dropped **from the fit only**, not reclassified,
and the reported length still spans the original region. Documented purpose is verbatim our
case: "the rounded-off mouth of a bore, a chamfer that got swept into the cylinder". In
ScanRuler the window is two numbers the user types — **for us it would have to be derived**,
which is the work.

### 2h. STEP emission invariants (addresses D2, D7)

The orientation invariant, quoted: "walking a face's boundary with the face normal up, the face
lies to the left... every edge ends up used exactly twice, once each way, which is what makes
the shell manifold." A full circle is **one** `CIRCLE` + **one** `VERTEX_POINT` +
`EDGE_CURVE(v,v,circle,.T.)`, because splitting it "invents an edge that is not on the part".
Cylinder solid: wall as one `ADVANCED_FACE` with `FACE_OUTER_BOUND(bottomRim,.T.)` and
`FACE_BOUND(topRim,.F.)`, lids on planes placed with `-axis` / `+axis`. Sphere split at the
**equator, not a meridian**, so both poles stay in a face interior — "those degenerate edges are
the classic way a sphere fails to import". Cone apex clamped to `MIN` to ship a microscopic
frustum rather than a degenerate vertex.
The first invariant is a **runnable assertion for D2**: count each edge's directed uses and fail
the build when any edge is not used exactly twice, once each way. That is a cheap standing check
we do not have.

### 2i. `CNCKitchen/meshStep` — an independent validator (addresses D7)

Zero-dependency STEP -> mesh importer (AP203/214/242, on npm as `meshstep`), whose own test
criterion is "0 open edges / 0 non-manifold edges", and whose watertightness mechanism is shared
B-rep edges **sampled once and welded**. Use it as an **external oracle on our STEP output** —
D7 is precisely a STEP we write and cannot re-read, and right now our only reader is the same
OCCT that wrote it. It cites *Better STEP* (arXiv 2506.05417) measuring OCCT's mesher leaving
faces unmeshed in ~1.5% of ABC models, ~9% of their assembly set.

## 3. ReverseReloaded (Unlicense — usable verbatim)

Pure Python Fusion add-in, manual point painting, one over-extended surface body per click, no
topology stage, no segmentation. Two ideas worth taking, both cheap:

### 3a. The degeneracy guard, with the sharpest rationale in the whole study (addresses D3)

Reject a cylinder whose radius exceeds `5 * rms_distance_from_centroid`. The stated reason:
**"Without a radius check, auto-fit always picks Cylinder. A cylinder with a very large radius
degenerates to a plane... Since cylinder has more degrees of freedom than a plane, it never does
*worse* on RMSE."** It also warns that the linear circle residual `sum((d^2 - r^2)^2)` "is NOT a
physical distance and NOT comparable to plane RMSE" — worth auditing our own comparisons for.

### 3b. Minimum-improvement margin on type selection (addresses precision)

Evaluate types in a fixed order encoding a prior for simpler ones (plane -> cylinder -> cone ->
sphere); a later type displaces the incumbent only if it beats it by `>= 0.01 mm` RMSE. The
named degenerate case: an algebraically exact sphere beating a Nelder-Mead cylinder on two edge
rings that happen to be equidistant from a sphere centre.

### 3c. The intersection-based closure philosophy (relevant to D2)

It deliberately over-extends every surface past the data and tells the user to "use Boundary Fill
to turn the enclosed volume into a solid". That is the same idea as Point2CAD's, below: do not
construct boundaries, extend surfaces and let a boolean find them.

## 4. Literature (unverified in-session — treat as leads, not facts)

- **Point2CAD** (arXiv 2312.04962, `prs-eth/point2cad`): fit **unclipped**, compute pairwise
  surface intersections, then clip/trim — its published artifacts are literally
  `unclipped -> intersection -> clipped`. The principled route to D2: topology from
  intersections instead of from mesh-derived boundaries.
- **ComplexGen** (SIGGRAPH 2022): global B-Rep chain inference, the alternative if local
  stitching keeps failing on the same parts.
- **Better STEP** (arXiv 2506.05417): cited by meshStep for OCCT mesher failure rates.
- Not verified: two arXiv IDs the agent tried resolved to unrelated papers and a ScienceDirect
  page 403'd. **"What the literature does" is formally unanswered** — the only prior art we
  actually read is the three codebases.

## 5. Backflip: the strategic observation

Backflip is the one product in the set claiming engineer-editable output, and it is
**feature-based**: it "breaks down a bulk geometry, then rebuilds it feature by feature,
operation by operation", chaining extrude/revolve/pattern, with an agent loop that checks its own
work and iterates. By emitting *features*, it gets watertightness free from the host kernel's
booleans — it deleted D2 and the whole boundary-construction problem by construction. No patent,
paper or technical blog exists; every number is marketing.

Our own `docs/PORT-MAP.md` already identifies the in-engine analogue: **Route P**, the prismatic
sidestep (`tryStageP`, upstream `:14485` -> `refit_prism_build.cpp` -> `refit_profile.cpp`) —
slice at cap levels, fit each level's closed 2D profile as lines and arcs where closure *and*
enclosed-area-vs-measured-cap-area are both checkable in 2D, extrude, union. The reference's own
words: "Every curved wall now comes into existence as a true cylindrical face with correct shared
edges *by construction* — there is nothing to repair afterward." For the prismatic class it
bypasses D1, D2 and the cascade entirely. It is also the largest piece of work on this list.

## 6. Ranked programme

| # | Item | Defect | Cost | Gate |
|---|---|---|---|---|
| 1 | `collectNonRegionNeighbourhood` port (1a) | D1 | ~60 lines, 1 call site | normal >= 71.95, valid solids >= 200, fine 74 |
| 2 | Audit the ladder against `refs` for port gaps (1b) | D1, D5 | read-only | a written diff, no score claim |
| 3 | Arc-coverage gate, 360 - widest gap, >= 29 deg (2a) | D3, D4 | small, self-contained | both variants, sentinels 12/16/12/12 |
| 4 | Normal-covariance axis refusal, 2nd eigenvalue > 1e-6*n (2b) | D3, D4 | small; tensor already computed | as above |
| 5 | Degeneracy guard r <= 5*rms_from_centroid (3a) | D3 | ~5 lines | as above |
| 6 | Directed-edge-use assertion, each edge twice once each way (2h) | D2, D7 | a standing check | must hold on the 200 valid solids first |
| 7 | Per-region volume attribution (1c) | D5, D6 | medium; needs dVolPredicted per family | normal, and t4 removal must stop costing -7.59 |
| 8 | Boundary-curve fallback set, after checking what we already have (1d) | recall+precision | medium | both variants |
| 9 | Retractable region growing, BFS restart + per-round refit (2d) | D3, D4 | medium, touches segmentation | full corpus, expect churn |
| 10 | Rim peeling (2c) | D3 partial | medium | must not move the 313 matched down |
| 11 | meshStep as an external STEP oracle (2i) | D7 | tooling only, no engine risk | re-read every emitted STEP |
| 12 | Shared-edge pool audit: do we ever build per-face edges? (1e) | D2 root | read-only first | if yes, this outranks everything above |
| 13 | Route P for the prismatic class (5) | D1, D2, D4 | largest | its own spec |

Item 12 is read-only and could reorder the whole table — if our port builds edges per-face
anywhere, D2 is a port gap and §13-§16's three parked rounds were all treating a symptom.
**Do 12 and 2 before committing to anything below them.**

## 7. Item 12 answered immediately (measured, read-only) — and it relocates D2

Our port **has** the reference's shared-edge discipline, on both kinds of chain:
`meshE[eid]` / `TopoDS::Edge(meshE[eid].Reversed())` for polyline chains
(`wt-p84/src/refit_build.cpp:1397`, `:1436`) and `TopoDS::Edge(g.edges[i].Reversed())` for
analytic ones (`:1447`). Edges are not built per face. So D2 is **not** the port gap item 12
was looking for, and the table above does not reorder.

**Where D2 actually lives.** The J6 dump on `L09_clamp` reports `ci=-1` on **all four** free
edges (§13) — no `BoundaryChain` matched any of them. The sharing discipline can only apply to a
boundary a chain OWNS; a boundary that exists geometrically but was never registered as a chain
has no owner, so each incident face mints its own edge and the two can never pair. That is why
sewing closed the shell (§15) and why exploding could not (§14): both were acting on the
symptom.

So D2 restates as: **`buildTopologyD` does not emit a chain for every real boundary between two
built faces.** The next measurement is to find which boundaries it misses and why — not to fix
the shell afterwards. Upstream's new `matchFreeEdgeChain` (`:6807`) and `freeEdgeRegionKind`
(`:6894`) exist to answer exactly this question and are absent from `refs/`.

Revised priority: this makes item 1 (`collectNonRegionNeighbourhood`, D1) still first, but the
**free-edge attribution trio** from the upstream delta — `countShellFreeEdges`,
`matchFreeEdgeChain`, `freeEdgeRegionKind` — moves up beside it, because it is the instrument
that turns "ci=-1" into a named missing chain.

## 8. Item 1 DONE and MEASURED NEUTRAL — with the reason, which reorders the table

`refs/stl2step` unshallowed (123 commits; `origin/main` = `6b52ba9` now present locally, working
tree still pinned at `7cf77a2`, **no file under `refs/` modified**). `collectNonRegionNeighbourhood`
ported into `wt-p84/src/refit_build.cpp` beside `collectShellCulprits`, called at the site-B
culprit collection behind `STL2STEP_N14_NONREGION`. Every primitive it needs already existed in
our port (`CascadeHit`, `addCascadeHit`, `regionExploded`, `brepStatusBad`, `collapseDiagEnabled`)
and the signatures matched upstream exactly, so the port is mechanical.

### Reachability first, then the score

```
203 models, STL2STEP_N14_NONREGION=1 STL2STEP_COLLAPSE_DIAG=1
  models emitting DIAG_CASCADE nonregion: 1   (gancio_parametric_normal)
  events: 1   -> "face=1233 nNbr=1 nbrs=[67]"   (zero empty-neighbour events)

A/B both variants
  normal  A 71.95 / B 71.95    fine  A 37.67 / B 37.67    all counters identical
  valid closed solids 200/203 and 74/78 in both arms
```

The counter is proven reachable and the effect is **exactly zero**. The one model it touches is
`gancio_parametric` — our D4 model, whose cylinders are never detected in the first place, so
containing its cascade changes nothing that CADScore can see.

### Why the domain is so small: our cascade damage is at the OTHER site

From the 203 traced logs (`n13logs`, `STL2STEP_DIAG_FBF=1`):

```
DIAG_EXPLODE events corpus-wide            517
models with >= 1 explode                    41
DIAG_FBF (regions that genuinely failed)    50
models reporting "J6: shell not closed"     26   (21 of them also explode)
explode events inside J6-open models       430   = 83 % of all explode damage
```

**83 % of the cascade damage happens in components whose shell is reported OPEN.**
`collectNonRegionNeighbourhood` guards site B — closed-but-invalid — which in our corpus is where
almost nothing is lost, because 200 of 203 components are already valid closed solids. Upstream's
fix is correct and faithful; it is simply aimed at the site that hurts *their* corpus, not ours.

Shipping decision: **env-gated, default OFF**, same treatment as P109 — a correct guard with a
measured-zero effect does not change the default, and an arm with no measured benefit is not
turned on just because it is principled.

### Revised ranking

The J6 open-shell path is the whole game: 430 of 517 explode events, against 50 real build
failures. And §7 already relocated its root cause — those boundaries have **no `BoundaryChain`**
(`ci=-1` on every free edge), so the shared-edge discipline never applies to them.

New order:
 1. **Port the upstream free-edge attribution trio** — `countShellFreeEdges` (`:6739`),
    `matchFreeEdgeChain` (`:6807`), `freeEdgeRegionKind` (`:6894`). Absent from `refs/`. These turn
    `ci=-1` into a named missing chain, which is the measurement every J6 fix needs and none of
    §13-§16 had.
 2. Then ask why `buildTopologyD` emits no chain for those boundaries — D2 at its root, and the
    cause of 83 % of the cascade damage.
 3. Items 3-5 of §6 (arc coverage, normal-covariance refusal, degeneracy guard) remain the
    cheapest independent recall/precision candidates and do not depend on 1-2.

Items 1-2 of §6 are now CLOSED: item 1 measured neutral here; item 2's audit found the ladder
present and the shared-edge pool present (§7), so there is no wholesale-revert port gap.
