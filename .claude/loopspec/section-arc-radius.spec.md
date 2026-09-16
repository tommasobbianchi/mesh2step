# DELEGATION SPECIFICATION: auto2d's section arcs are fitted undersized

Self-contained. You do not see the conversation that produced this. Work in
`/home/tommaso/projects/mesh2step`. **No commits, no pushes, no deploys, no service restarts.**

## 1. TARGET GOAL

**Objective.** `tools/feature_recon/auto2d.py` fits the arcs of its 2D section systematically
SMALLER than the geometry the mesh shows. On mechparts/23 that puts six axial half-cylinders at
the wrong radius, so they read as "missing" against the mesh. Make the section arc radii match
the mesh.

**Writable scope:** `tools/feature_recon/auto2d.py` only. Everything else read-only.
Do NOT touch: `refs/`, `tests/`, `webapp/`, `src/`, corpus data, any `truth.json`,
`tools/feature_recon/radial_fillets.py`, `tools/feature_recon/auto25g.py`,
`tools/feature_recon/quads.py`, `tools/feature_recon/slice.py`.

## 2. MEASURED FACTS — do not re-theorise; re-measure if you doubt them

mechparts/23: 148,822 triangles, bbox z 0..20, diag 216.0.

Six axial cylinders the mesh shows are absent from the built STEP at their true radius. All six
are half-cylinders on one common band: `|az| = 1.000`, span exactly `z 3.00..17.00`, sweeps
181-184 degrees, 8-22 triangles each.
```
mesh patch radii : 11.263, 11.294, 11.525, 11.946, 21.077, 21.345
```
The 2D section DOES contain arcs there, at every slice height (z = 5, 10, 15 each give 19 arcs):
```
section arc radii: 11.099, 11.100, 11.124, 11.125, 11.145, 20.636
```
So the profile arcs are undersized by ~0.15-0.8 mm.

**Which radius is right: the mesh patch, decisively.** Mean |distance - radius| of each patch's
own vertices, patch-refit vs nearest section arc — patch wins 6/6:
```
patch 11.263 err 0.0001  vs section 11.145 err 0.0188
patch 11.525 err 0.0001  vs section 11.145 err 0.1146
patch 11.294 err 0.0000  vs section 11.145 err 0.1422
patch 11.946 err 0.0001  vs section 11.145 err 0.0943
patch 21.345 err 0.0000  vs section 20.636 err 1.5439
patch 21.077 err 0.0001  vs section 20.636 err 1.5947
```

**Where to look.** `segment_loop(L)` in auto2d.py (note: it returns `(L, prims)`, NOT `prims` —
unpacking it wrongly silently yields zero arcs). Arc runs are grown while `dev <= ARC_TOL`, then
`fit_circle(L[i:j+1])` sets the radius. Afterwards, consecutive arcs are MERGED when
`norm(centre diff) < 0.05 and abs(dR) < 0.05` (around auto2d.py:87).

**UNVERIFIED HYPOTHESIS — measure it, do not assume it:** `ARC_TOL = 0.02` plus that greedy
merge may join adjacent arc runs of slightly different radius and drag the fitted radius toward
a neighbour. A 0.7 mm error on R=21 is far too large to be chord height at this tessellation.
Other candidates worth measuring: `fit_circle` bias on a short arc span; `dedupe()` dropping
points; the section polyline itself being inset.

**First deliverable: say WHY the radii come out small, with a measurement.** Only then change code.

Current verified state of the two parts this file builds (rebuild to confirm before changing):
```
part 12: valid, 1 solid, 0 free, dv 0.0049%, p95 0.0815, 21 cyl faces, coverage 17/30, support 21/21
part 23: valid, 1 solid, 0 free, dv -0.1506%, p95 0.0886, 58 cyl faces, coverage 36/80
```

## 3. VERIFICATION COMMANDS

```bash
cd /home/tommaso/projects/mesh2step
python3 -m mesh2step.feature /home/tommaso/corpora/mechparts/23.stl -o /tmp/s23.step --no-fallback
python3 -m mesh2step.feature /home/tommaso/corpora/mechparts/12.stl -o /tmp/s12.step --no-fallback
```
2-6 minutes each; FOREGROUND, wait for them. If one exceeds your shell timeout, use
`~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- '<cmd> > <log> 2>&1'` and poll
`~/.claude/scripts/job status <name>`. Never `pgrep`/`ps`, never `nohup`/`setsid`/`&`.

Measure (scratch script outside the repo):
```python
import sys; sys.path.insert(0,'/home/tommaso/projects/mesh2step')
from mesh2step.feature import _mesh, measure, _read, cylinder_radii, mesh_cylinder_radii
for p,o in (('23','/tmp/s23.step'),('12','/tmp/s12.step')):
    tri=_mesh(f'/home/tommaso/corpora/mechparts/{p}.stl')
    m=measure(o,tri); br=sorted(cylinder_radii(_read(o))); mr=sorted(mesh_cylinder_radii(tri))
    cov=sum(1 for r in mr if any(abs(r-b)<=0.01*max(r,1e-9) for b in br))
    sup=sum(1 for b in br if any(abs(b-r)<=0.01*max(b,1e-9) for r in mr))
    print(p,'valid',m['valid'],'solids',m['solids'],'free',m['free_edges'],
          'dv%',round(m['dv_pct'],4),'p95',round(m['dist_p95'],4),
          'cyl',len(br),'coverage',f'{cov}/{len(mr)}','support',f'{sup}/{len(br)}')
    print('   radii 10..22:',[round(x,3) for x in br if 10<x<22])
```

Lint: `ruff check tools/feature_recon/auto2d.py` — baseline is NON-ZERO. The gate is no NEW
diagnostic code and no rising count, never absolute zero.

## 4. TERMINATION CRITERIA — all must hold, each backed by captured stdout

- [ ] **part 23 builds cylinders matching the mesh radii 11.263, 11.294, 11.525, 11.946, 21.077,
      21.345 within 1%** — print the built radii in 10..22 and say which of the six are now hit
      (today: none)
- [ ] part 23 coverage > 36/80; part 12 coverage >= 17/30
- [ ] both parts: `valid=True`, `solids=1`, `free_edges=0`
- [ ] `abs(dv_pct) <= 1.0`; `dist_p95 <= 0.005*diag` (23 = 216.0, 12 = 196.57)
- [ ] **support must not fall** — part 12 is at 21/21 today; report the ratio before and after
      for both parts. A cylinder the mesh does not show must never be added.
- [ ] `ruff check tools/feature_recon/auto2d.py` introduces no new diagnostic
- [ ] the diff touches only `tools/feature_recon/auto2d.py`

## 5. GUARDRAILS

- **Diagnosis before patch.** Report the measured cause of the undersizing first.
- **Never widen a gate to pass.** dv, p95, validity and solid count stay as they are. If you
  change `ARC_TOL` or the merge thresholds, show the measurement that justifies the new value
  and confirm part 12 does not regress — that part shares this builder.
- **Support is the hard constraint.** Fitting arcs LARGER to chase six radii, at the cost of
  adding cylinders the mesh does not show, is a FAILURE.
- Minimal diff, no refactors, no new dependencies.
- If after 3 iterations the six radii are still not matched with support intact, STOP and report
  the measurements and the cause you found. An honest negative with numbers beats a guess.
- Completion is never declared without stdout and exit codes.
