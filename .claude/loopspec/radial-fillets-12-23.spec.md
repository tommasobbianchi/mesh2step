# DELEGATION SPECIFICATION: reconstruct the radial partial cylinders / fillets of mechparts 12 and 23

Self-contained. You do not see the conversation that produced this. Work in
`/home/tommaso/projects/mesh2step`. **No commits, no pushes, no deploys, no service restarts.**

## 1. TARGET GOAL

**Objective.** The feature path serves mechparts/12 and /23 as valid solids, but reconstructs
only a third of the cylinders the mesh contains. Every missing one is a *radial partial
cylinder / fillet*. Raise cylinder coverage on both parts without losing validity.

**Writable scope:** `tools/feature_recon/auto2d.py`, `tools/feature_recon/auto25g.py`, and ONE
new file `tools/feature_recon/radial_fillets.py` if you need it. Everything else read-only.
Do NOT touch: `refs/`, `tests/`, `webapp/`, `src/`, corpus data, any `truth.json`,
`tools/feature_recon/edgebuild.py`.

## 2. MEASURED FACTS — do not re-theorise; re-measure if you doubt them

Coverage = of the cylinder radii the MESH shows, how many appear in the built STEP.

```
part 12 (164,996 tris): mesh 30 cylinders, built 43, covered 10  -> 33.3%
part 23 (148,822 tris): mesh 80 cylinders, built 25, covered 21  -> 26.2%
```

Census of the misses, by angular sweep:

```
part 12: full-bore built=True 6 | partial/fillet built=False 20 | partial/fillet built=True 4
part 23: full-bore built=True 2 | half built=True 1 | partial/fillet built=False 57 | partial/fillet built=True 20
```

**Every full bore is already built. Every miss is a partial arc:** sweep 16–62 degrees, axial
span 0.5–2.0 mm, radii clustered at R≈2.0 (part 12) and R≈3.03 (part 23), and the axis is
**radial** — perpendicular to the build axis Z (|az| ≈ 0.00).

Why they are lost: the winning builders are 2D-profile extruders. `auto2d.py` fits arcs in the
extrusion plane (see the `("arc", i, j, c, r)` primitives around auto2d.py:76–119), so an arc
whose axis is perpendicular to the extrusion axis cannot be represented. The `GeomAbs_Torus`
references at auto2d.py:254 and auto25g.py:187 are face-census labels, NOT constructions.

Recogniser status — the features ARE detected, they are simply not built:
- `tools/feature_recon/quads.py` `classify(tri)` returns all 30 / 80 cylinders, including every
  missing radius, each with axis, radius and triangle list.
- `tools/feature_recon/features.py` `patches()` (used by autoblock2) does NOT work here: its
  20-degree normal-agreement union-find collapses part 12 into ~7 components of ~19,296
  triangles, all failing the circle fit. autoblock2 covers only 2/30. Do not build on it.

**Dead end, already measured — do not attempt:** `edgebuild.py` recognises these features (388
cylinders on part 12) but TIMES OUT: 5400 s, 1.15 GB, no RESULT. It is not the route.

Which builder currently wins each part (this is what you are extending):
- part 12 -> `stepped` (auto25g.py, AXIS=2)
- part 23 -> `extrude-z` (auto2d.py, AXIS=2)

## 3. VERIFICATION COMMANDS

1. Build both parts:
   ```bash
   cd /home/tommaso/projects/mesh2step
   python3 -m mesh2step.feature /home/tommaso/corpora/mechparts/12.stl -o /tmp/f12.step --no-fallback
   python3 -m mesh2step.feature /home/tommaso/corpora/mechparts/23.stl -o /tmp/f23.step --no-fallback
   ```
   Each takes ~85–180 s. Anything over ~10 min goes under
   `~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- '<cmd> > <log> 2>&1'`,
   checked with `~/.claude/scripts/job status <name>`. Never `pgrep`/`ps`, never `nohup`/`&`.

2. Measure validity + coverage (write this as a scratch script outside the repo):
   ```python
   import sys; sys.path.insert(0,'/home/tommaso/projects/mesh2step')
   sys.path.insert(0,'/home/tommaso/projects/mesh2step/tools/feature_recon')
   from mesh2step.feature import _mesh, measure, cylinder_radii, _read, mesh_cylinder_radii
   for p,o in (('12','/tmp/f12.step'),('23','/tmp/f23.step')):
       tri=_mesh(f'/home/tommaso/corpora/mechparts/{p}.stl')
       m=measure(o,tri); mr=sorted(mesh_cylinder_radii(tri)); br=sorted(cylinder_radii(_read(o)))
       cov=sum(1 for r in mr if any(abs(r-b)<=0.01*max(r,1e-9) for b in br))
       print(p, 'valid',m['valid'],'solids',m['solids'],'free',m['free_edges'],
             'dv%%',round(m['dv_pct'],4),'p95',round(m['dist_p95'],4),
             'coverage',f'{cov}/{len(mr)}')
   ```

3. Lint only what you touched: `ruff check <the files you changed>`. Repo baseline is NON-ZERO;
   the gate is no NEW diagnostic code and no rising count, never absolute zero.

## 4. TERMINATION CRITERIA — all must hold, each backed by captured stdout

- [ ] part 12 coverage strictly greater than 10/30, part 23 strictly greater than 21/80
- [ ] both parts keep `valid=True`, `solids=1`, `free_edges=0`
- [ ] `abs(dv_pct) <= 1.0` and `dist_p95 <= 0.005 * diag` on both (the service's own gate)
- [ ] **no cylinder already built today is lost.** Record the built radii BEFORE your change
      (part 12: 43 cylinders, part 23: 25) and after; every radius present before must still be
      present. This repo has a hard-won rule, already written into `_retry_broken_trueform`:
      *a retry is kept only if it lands closer AND recognises the same number of cylinders —
      it must not trade shape for volume.* The same applies here in reverse: do not trade
      existing cylinders for new ones. Net coverage going up while known radii disappear is a
      FAILURE, not a win.
- [ ] no NEW ruff diagnostic in the files you changed
- [ ] the diff stays inside the §1 scope

## 4b. ACCEPTANCE SHAPE — follow the architecture this repo already uses

Every successful stage in this pipeline is an **upgrade pass**: build a candidate, measure it,
keep it ONLY if it passes the gate, otherwise leave the previous result untouched. The service
chains them exactly this way (engine -> force-sew retry -> no-unify retry -> trueform retry ->
edgebuild upgrade -> feature upgrade).

Do the same here. Do NOT rewrite the extrusion builders to be fillet-aware. Instead:

1. let the existing winning builder produce the bulk solid exactly as it does today
   (part 12 -> `stepped`, part 23 -> `extrude-z`);
2. then, as a SEPARATE post-pass, add the radial features from `quads.classify`;
3. measure; keep the augmented solid only if every §4 gate holds, else return the original.

This matters for a measured reason: `edgebuild.py` recognises these fillets (388 cylinders on
part 12) but TIMES OUT at 5400 s — and it does so in its merge loop over ~20k facet-plane
regions, never reaching the fillets at all. A post-pass that touches only the ~20-60 recognised
arcs skips that cost entirely. `quads.classify` costs 8.4 s and 0.37 GB on a 165k-triangle mesh.

## 5. GUARDRAILS

- **The cylinders are the product.** A change that reaches validity by dropping faces, or that
  raises coverage while breaking the solid, is a FAILURE.
- **Never widen a tolerance to pass a gate.** If you believe a tolerance is genuinely wrong,
  report the measurement, do not change it silently.
- Diagnosis before patch: first report how many of the missing radii your change actually
  builds, and for which part.
- Minimal diff. No refactors, no new dependencies, no reformatting untouched lines.
- Suggested approach (evaluate, do not assume): take the radial cylinder patches straight from
  `quads.classify`, and after the extrusion solid is built, cut/fuse each as its own partial
  cylindrical face — a `BRepPrimAPI_MakeCylinder` on the patch's own axis, trimmed to the
  patch's angular sweep and axial span, fused or cut according to whether material lies inside
  or outside the arc. Verify that inside/outside test against the mesh, do not guess it.
- If after 3 iterations coverage has not improved on either part, STOP and report what you
  measured and why it failed. An honest negative with numbers beats a guess.
- Completion is never declared without stdout and exit codes.
