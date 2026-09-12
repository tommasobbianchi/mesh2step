# Lane N27 — real-mesh shell closure: sew tolerance, targeted explode, t4 floor, face fix

Fixtures: `~/corpora/mechparts/{9,11,22}.stl` (real machined parts, 46k/47k/23k tris,
88/98/77% curved). Corpus gate: cadbench normal/fine sweep, A/B vs frozen baseline
binary (`stl2step-baseline`, pre-N27 tree). All changes env-gated; off-path STEP +
RESULT verified byte-identical (timestamp header excepted) on L03_tri_prism_normal.

## Measured root causes (mechparts/9 unless noted)

1. **Intersection misses are dominated by cyl|cyl `IntAna_NoGeometricSolution`.**
   DIAG_P2 on part 9: 111 cyl|cyl (all ty=9) + 9 plane|cyl (ty=4, residual-rejected)
   of 120 misses; part 11: 186 + 27 of 213. Independently fitted cylinder pairs on
   real meshes have skew/inconsistent axes; the tangent/parallel constructed
   fallbacks (refit_build.cpp `intersectSurfaces`) do not apply (tanContact=0,
   parOff=0). Chains stay mesh polylines — legal, but their chord edges then border
   analytic faces.
2. **Partial-cylinder face builds fail on UV self-intersection, not tolerance.**
   rid=257 evidence: `maxCylDev=0.0703 < cap=0.0733` yet BRepCheck
   UnorientableShape (st=27) across all 12 strategy/orientation combos.
   `bindCylPCurves` (refit_build.cpp ~2471) writes straight UV lines for verbatim
   chord edges; on coarse real-mesh boundaries the chords are long (sagitta
   ~0.5 mm at R=9, 6 mm chord), UV diagonals cross the inner wire, wire
   imbrication fails. → R1 explode of the cylinder region
   (refit_build.cpp:5323), neighbouring chains become `mix`, and the shell
   accumulates free edges.
3. **The J6 open-shell verdict is inflated by duplicated TShapes and degenerate
   edges.** 46k-tri parts skip the J6 heal (`mv.nTri < 10000` at refit_build.cpp:
   ~5811), so the only moves left are the explode arms. DIAG_J6 on part 9: 1062
   free-edge dumps, 384 degenerate (len<0.001), 375 segment pairs owned twice.
   N13_SEW_FREE existed for exactly the duplicate class but sewed at
   `Precision::Confusion()*100` = **1e-5 mm** — six orders below the post-snap
   duplicate distance (region fit residual 0.05–0.07 mm), so it merged nothing
   (measured `N13_SEW faces=26533->26533 closed=0` on part 9).
4. **The N13_TARGETED_EXPLODE arm was unreachable** (user refuted-attempt #2
   confirmed at refit_build.cpp): `if (!did && n13Targeted)` while the
   chainEdgeFail arm above sets `did=true` whenever any plane|plane/plane|cyl
   intersection missed (128 chains on part 9). Decoupled under the same env gate.
5. **t4 volume budget rejects good closed+valid rebuilds on curved parts
   (mechparts/22).** DIAG_REVERT: `builtCyl=3 builtPl=18450 t2=1 t3=1 t4=0`,
   dV=779.43 mm³ vs budget=90.29 (1e-4×meshVol); fit residuals predicted only
   dVolAbs=24.4, so term B cannot see it either. Cause: `snapVertexToCurve`
   moves scale with surface area × fit residual, not 1e-4×volume; the mesh
   volume is not the truth for 77%-curved tessellations. → verbatim, 0 cylinders.
6. **After the shell finally closes (sew + targeted), site B kills it for a
   handful of bad faces.** N13_SEW_WHY on part 11 sewn shell: 11 of 32387 faces
   invalid, ALL UnorientableShape (st=27). ShapeFix_Shell (face reversal) cannot
   repair wire imbrication → cascade explodes → site-B discard
   (refit_build.cpp return-false at the `plan.hostR2 || u2Done || !shValid`
   disjunct) → component reverts with 0 cylinders.

## Fix (all env-gated; default off ⇒ byte-identical)

| Env flag | Change | Where |
|---|---|---|
| `STL2STEP_N27_SEW_TOL_MM=<mm>` | N13_SEW_FREE sewing tolerance override (default was 1e-5 mm) | refit_build.cpp n13Sew arm |
| `STL2STEP_N13_TARGETED_EXPLODE` (reused) | arm decoupled from `did` so it actually runs | refit_build.cpp explode arms |
| `STL2STEP_N27_T4_REL=<frac>` | t4 budget floor `max(budget, frac×meshVol)` | stl2step.cpp t4 budget |
| `STL2STEP_N27_SEW_FIXFACE=1` | ShapeFix_Face per invalid sewn face (one-face guard, closure+validity re-check, old→new map for built[] remap) | refit_build.cpp n13Sew arm |

## Proof (engine flag set + N27 flags)

| Part | Before (cylinders shipped) | After |
|---|---|---|
| mechparts/22 | 0 (t4 revert) | **3**, watertight, volDelta 0.0 |
| mechparts/11 | 0 (heal-discard) | (pending) |
| mechparts/9  | 0 (R2 wipeout, adopted-no-cyl) | (pending) |

cadbench A/B: `sweep_base.tsv` (flags only) vs `sweep_n27.tsv` (+N27) — see
Regression section below.

## Regression

(pending sweep completion)
