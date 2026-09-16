# DELEGATION SPECIFICATION: stop rejecting fillets whose refit disagrees with quads.classify

Self-contained. You do not see the conversation that produced this. Work in
`/home/tommaso/projects/mesh2step`. **No commits, no pushes, no deploys, no service restarts.**

## 1. TARGET GOAL

**Objective.** `tools/feature_recon/radial_fillets.py` discards a candidate when its own
least-squares refit disagrees with `quads.classify`'s radius by more than 15%. Measurement shows
the refit is the correct one in **21 of 21** cases, so the filter is backwards and throws away
real fillets. Recover them.

**Writable scope:** `tools/feature_recon/radial_fillets.py` only. Everything else read-only.
Do NOT touch: `refs/`, `tests/`, `webapp/`, `src/`, corpus data, any `truth.json`,
`tools/feature_recon/auto2d.py`, `tools/feature_recon/auto25g.py`, `tools/feature_recon/quads.py`.

## 2. MEASURED FACTS — do not re-theorise; re-measure if you doubt them

The filter, in `_candidates()`:
```python
if r < 0.5 or res > 0.01 * r or abs(r - float(o[2])) > 0.15 * float(o[2]):
    continue
```
`r` is the refit radius, `o[2]` is `quads.classify`'s. The third clause rejects
**9 candidates on mechparts/12 and 12 on mechparts/23**.

Adjudication: for every rejected patch, the mean |distance - radius| of that patch's OWN
vertices about each candidate radius. The refit wins **21/21**:
```
part 12: classify 2.033 err 1.2444  vs refit 0.789 err 0.0044
         classify 1.981 err 1.1046  vs refit 0.877 err 0.0071
         classify 2.053 err 1.2748  vs refit 0.778 err 0.0093
part 23: classify 21.432 err 18.4315 vs refit 3.000 err 0.0004
         classify  3.057 err  0.6798 vs refit 2.378 err 0.0045
         classify  3.035 err  1.5188 vs refit 1.517 err 0.0050
```
So `quads.classify`'s radius is unreliable for small partial patches and must not be used to
veto the refit.

**The existing quality guard is `res > 0.01 * r`** — the refit's own residual, which is the
trustworthy signal (rejected patches show refit residuals of 0.0004-0.0093 against radii of
0.7-3.0, i.e. well under 1%). Keep it.

Current verified state (rebuild both parts to confirm before changing anything):
```
part 12: valid, 1 solid, 0 free, dv 0.0049%, p95 0.0815, 21 cyl faces, 11 at R~2.0, coverage 17/30
part 23: valid, 1 solid, 0 free, dv -0.1506%, p95 0.0886, 58 cyl faces, 39 at R~3.0, coverage 36/80
```

## 3. WHAT TO CHANGE

Remove the `abs(r - float(o[2])) > 0.15 * float(o[2])` veto, OR invert it so that `classify`'s
radius is used only as a weak sanity bound (e.g. reject only if the two disagree by more than a
factor of ~10, which would indicate a genuinely mis-grouped patch). Decide by measurement and
say which you chose and why.

Everything else stays: the `res > 0.01 * r` residual test, `r < 0.5`, the sweep and span limits,
per-patch acceptance (`_accepted`: valid, 1 solid, 0 free edges), `_same_feature` identity by
axis line + overlapping span, `_snap_axes` retry, and the final `_passes_gate`.

## 4. VERIFICATION COMMANDS

```bash
cd /home/tommaso/projects/mesh2step
python3 -m mesh2step.feature /home/tommaso/corpora/mechparts/12.stl -o /tmp/h12.step --no-fallback
python3 -m mesh2step.feature /home/tommaso/corpora/mechparts/23.stl -o /tmp/h23.step --no-fallback
```
2-6 minutes each; run in the FOREGROUND and wait. If a command exceeds your shell timeout, use
`~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- '<cmd> > <log> 2>&1'` and poll
`~/.claude/scripts/job status <name>`. Never `pgrep`/`ps`, never `nohup`/`setsid`/`&`.

Measure (scratch script outside the repo) — report cylinder faces, per-radius counts, coverage,
validity, dv, p95:
```python
import sys, collections; sys.path.insert(0,'/home/tommaso/projects/mesh2step')
from mesh2step.feature import _mesh, measure, _read, cylinder_radii, mesh_cylinder_radii
for p,o in (('12','/tmp/h12.step'),('23','/tmp/h23.step')):
    tri=_mesh(f'/home/tommaso/corpora/mechparts/{p}.stl')
    m=measure(o,tri); br=sorted(cylinder_radii(_read(o))); mr=sorted(mesh_cylinder_radii(tri))
    cov=sum(1 for r in mr if any(abs(r-b)<=0.01*max(r,1e-9) for b in br))
    print(p,'valid',m['valid'],'solids',m['solids'],'free',m['free_edges'],
          'dv%',round(m['dv_pct'],4),'p95',round(m['dist_p95'],4),
          'cyl_faces',len(br),'coverage',f'{cov}/{len(mr)}')
    print('   radii',[round(x,3) for x in br])
```

Lint: `ruff check tools/feature_recon/radial_fillets.py` — currently clean, keep it clean.

## 5. TERMINATION CRITERIA — all must hold, each backed by captured stdout

- [ ] part 12: MORE cylindrical faces than 21, and coverage >= 17/30
- [ ] part 23: MORE cylindrical faces than 58, and coverage >= 36/80
- [ ] both: `valid=True`, `solids=1`, `free_edges=0`
- [ ] `abs(dv_pct) <= 1.0`; `dist_p95 <= 0.005*diag` (diag: 12 = 196.57, 23 = 216.0)
- [ ] **support must not fall**: every cylinder in the output must have a radius the MESH shows
      (`mesh_cylinder_radii`) within 1%. Part 12 is at 21/21 today — report the ratio before and
      after. Adding unsupported cylinders is INVENTING geometry and is a FAILURE, worse than
      adding nothing.
- [ ] `ruff check tools/feature_recon/radial_fillets.py` passes
- [ ] the diff touches only `tools/feature_recon/radial_fillets.py`

## 6. GUARDRAILS

- **Support is the hard constraint.** This codebase's rule: a build must not trade real geometry
  for a better count. A cylinder the mesh does not show must never be added.
- Never widen dv, p95, validity or solid-count gates.
- If a patch cannot be built validly, skip it and continue — never force it.
- Report how many previously rejected candidates are now built, per part.
- Minimal diff, no refactors, no new dependencies.
- If after 3 iterations face counts have not risen with support intact, STOP and report the
  measurements. An honest negative beats a guess.
- Completion is never declared without stdout and exit codes.
