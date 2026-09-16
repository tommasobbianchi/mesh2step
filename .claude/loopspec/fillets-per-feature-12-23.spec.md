# DELEGATION SPECIFICATION: build EVERY radial fillet, not one per radius

Self-contained. You do not see the conversation that produced this. Work in
`/home/tommaso/projects/mesh2step`. **No commits, no pushes, no deploys, no service restarts.**

## 1. TARGET GOAL

**Objective.** `tools/feature_recon/radial_fillets.py` currently reconstructs at most ONE fillet
per distinct radius. A part with eleven R=2.0 fillets on eleven different edges gets one
cylindrical face and ten missing features. Reconstruct **every** detected radial fillet as its
own face.

**Writable scope:** `tools/feature_recon/radial_fillets.py` only. Everything else read-only.
Do NOT touch: `refs/`, `tests/`, `webapp/`, `src/`, corpus data, any `truth.json`,
`tools/feature_recon/auto2d.py`, `tools/feature_recon/auto25g.py`, `tools/feature_recon/edgebuild.py`.

## 2. MEASURED FACTS — do not re-theorise; re-measure if you doubt them

Current state (verified by rebuilding both parts):
```
part 12: valid 1 solid, 0 free edges, dv +0.0219%, p95 0.2544, 44 cyl faces, coverage 17/30
part 23: valid 1 solid, 0 free edges, dv -0.0548%, p95 0.0886, 26 cyl faces, coverage 36/80
```

**The defect.** In `augment()`:
```python
if any(abs(r - b) <= RADIUS_MATCH * max(r, 1e-9) for b in _built_radii(shape)):
    continue
```
This skips a candidate whenever ANY face in the shape already has that radius. Census of
candidates that pass every geometric filter:
```
part 12: 11 candidates pass, 11 skipped by the radius rule.  Their radii: 2.0 x11
part 23: 42 candidates pass, 40 skipped by the radius rule.  Their radii: 2.879..3.0
```
So eleven distinct physical fillets collapse to one face. **Two fillets of equal radius on
different edges are different features and both must exist.**

A previous attempt rejected this change with "adds no coverage, fragments faces (86->229)".
That reasoning is wrong for this goal: the coverage metric matches mesh radii to built radii, so
duplicates do not move it, but the REQUIREMENT is that every physical partial cylinder exists as
a face. A rising face count is the correct outcome of reconstructing 11 features instead of 1.

Other rejection causes, for information (NOT your target, do not chase them):
```
part 12: axial-skipped 10, "r disagrees with classify" 7, fit residual >1% 2
part 23: axial-skipped 23, "r disagrees with classify" 11, sweep<10deg 3, r<0.5 1
```

## 3. WHAT TO CHANGE

Replace the radius-based skip with a **per-feature identity**: two candidates are the same
feature only if they share the same axis LINE (direction and position, not just direction) and
overlap in axial span. Suggested test, to evaluate by measurement not assumption:
- axis directions parallel within ~1e-3, AND
- perpendicular distance between the two axis points < ~RADIUS_MATCH * r, AND
- their [b0, b1] spans overlap.

Everything else in the pass stays as it is: per-patch application, the validity check after each
patch, the final `ShapeUpgrade_UnifySameDomain`, and `_passes_gate`.

## 4. VERIFICATION COMMANDS

```bash
cd /home/tommaso/projects/mesh2step
python3 -m mesh2step.feature /home/tommaso/corpora/mechparts/12.stl -o /tmp/g12.step --no-fallback
python3 -m mesh2step.feature /home/tommaso/corpora/mechparts/23.stl -o /tmp/g23.step --no-fallback
```
Each takes 2-6 minutes; run in the FOREGROUND and wait. If a command exceeds your shell timeout,
re-run it under `~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- '<cmd> > <log> 2>&1'`
and poll `~/.claude/scripts/job status <name>`. Never `pgrep`/`ps`, never `nohup`/`setsid`/`&`.

Measure (scratch script outside the repo):
```python
import sys; sys.path.insert(0,'/home/tommaso/projects/mesh2step')
from mesh2step.feature import _mesh, measure, _read, cylinder_radii, mesh_cylinder_radii
for p,o in (('12','/tmp/g12.step'),('23','/tmp/g23.step')):
    tri=_mesh(f'/home/tommaso/corpora/mechparts/{p}.stl')
    m=measure(o,tri); br=sorted(cylinder_radii(_read(o))); mr=sorted(mesh_cylinder_radii(tri))
    cov=sum(1 for r in mr if any(abs(r-b)<=0.01*max(r,1e-9) for b in br))
    print(p,'valid',m['valid'],'solids',m['solids'],'free',m['free_edges'],
          'dv%',round(m['dv_pct'],4),'p95',round(m['dist_p95'],4),
          'cyl_faces',len(br),'coverage',f'{cov}/{len(mr)}')
```

Lint: `ruff check tools/feature_recon/radial_fillets.py` — it currently passes cleanly, keep it so.

## 5. TERMINATION CRITERIA — all must hold, each backed by captured stdout

- [ ] **part 12 has at least 10 cylindrical faces of radius ~2.0** (today: 1). Count them
      explicitly and print the list of radii.
- [ ] **part 23 has at least 30 cylindrical faces of radius in 2.87..3.05** (today: ~2).
- [ ] both parts: `valid=True`, `solids=1`, `free_edges=0`
- [ ] `abs(dv_pct) <= 1.0`; `dist_p95 <= 0.005 * diag` (diag: part 12 = 196.57, part 23 = 216.0)
- [ ] coverage does not DROP (part 12 >= 17/30, part 23 >= 36/80)
- [ ] no previously built radius disappears
- [ ] `ruff check tools/feature_recon/radial_fillets.py` still passes
- [ ] the diff touches only `tools/feature_recon/radial_fillets.py`

## 6. GUARDRAILS

- **The features are the product.** Face count going UP is expected and fine here. Validity is
  not negotiable: if applying a patch breaks the solid, skip that patch and keep going, exactly
  as the current code does.
- **Never widen a gate to pass.** dV, p95, validity and solid count stay as they are.
- If applying all patches breaks the solid, apply as many as keep it valid, report how many were
  applied and how many were skipped and why. A partial improvement with honest numbers is a
  success; a broken solid is not.
- Minimal diff, no refactors, no new dependencies.
- If after 3 iterations the counts have not risen, STOP and report the measurements.
- Completion is never declared without stdout and exit codes.
