# DELEGATION SPECIFICATION: build the vetoed fillet patches as TORI, not cylinders

Self-contained. You do not see the conversation that produced this. Work in
`/home/tommaso/projects/mesh2step`. **No commits, no pushes, no deploys, no service restarts.**

## 1. TARGET GOAL

**Objective.** `tools/feature_recon/radial_fillets.py` vetoes a set of patches because their
cylinder refit disagrees with `quads.classify`. A previous investigation proved those patches
are **torus fillets, not cylinders** — they lie on a torus far better than on any cylinder.
Build them as tori.

**Writable scope:** `tools/feature_recon/radial_fillets.py` only. Everything else read-only.
Do NOT touch: `refs/`, `tests/`, `webapp/`, `src/`, corpus data, any `truth.json`,
`tools/feature_recon/auto2d.py`, `tools/feature_recon/auto25g.py`, `tools/feature_recon/quads.py`.

## 2. MEASURED FACTS — do not re-theorise; re-measure if you doubt them

The veto, in `_candidates()`:
```python
if r < 0.5 or res > 0.01 * r or abs(r - float(o[2])) > 0.15 * float(o[2]):
    continue
```
It rejects 9 candidates on mechparts/12 and 12 on mechparts/23. **The veto is CORRECT for
cylinders** — do not remove it. A prior attempt removed it, found it would add cylinders the
mesh does not support, and reverted.

Torus fits of those same vetoed patches (minor radius r, major R), against the cylinder refit:
```
part | cyl refit | classify | cyl err | torus fit              | torus err
  12 |   0.789   |  2.033   | 0.0044  | r=2.000  R=23.398      | 0.0004
  12 |   0.915   |  2.007   | 0.0036  | r=2.000                | 0.0020
  12 |   1.058   |  2.009   | 0.0029  | r=2.000                | 0.0002
  12 |   0.877   |  1.981   | 0.0071  | r=2.000                | 0.0035
  12 |   0.778x2 |  2.05    | 0.0093  | r=2.000                | 0.0001
  23 |   3.000   | 21.432   | 0.0004  | r=3.100                | 0.0291
  23 | 2.378-2.499|  3.03   | 0.0039  | r=3.100                | 0.0307
```
On part 12 every vetoed patch lies on a torus of minor r=2.000 to 0.0001-0.0035 mm. Note that
`classify`'s radius (~2.0) is the TORUS MINOR RADIUS — which is why the cylinder refit disagrees
with it by more than 15%. The veto is detecting "this is not a cylinder", correctly.

**Beware a trap that already caught one investigation:** do NOT adjudicate competing fits using
`mean |distance - radius|` about the fitted axis. `_patch_fit` minimises exactly that, so the
cylinder refit always "wins" by construction. Compare each model by the residual of the patch
vertices to the MODEL SURFACE (point-to-torus vs point-to-cylinder distance).

Current verified state (rebuild to confirm before changing anything):
```
part 12: valid, 1 solid, 0 free, dv 0.0049%, p95 0.0815, 21 cyl faces, coverage 17/30, support 21/21
part 23: valid, 1 solid, 0 free, dv -0.1506%, p95 0.0886, 58 cyl faces, coverage 36/80
```
Part 12 already carries 20 torus faces and part 23 carries 38, so tori are a normal output of
this pipeline.

## 3. WHAT TO CHANGE

In `_candidates()` (or a sibling generator), when the cylinder veto fires, fit a **torus** to the
patch: axis direction from the patch normals, minor radius r, major radius R, centre on the axis.
If the torus residual is materially better than the cylinder residual AND below a tight absolute
bound, yield the patch as a torus candidate instead of discarding it.

Build it with `BRepPrimAPI_MakeTorus` (OCP) restricted to the patch's angular sweep and span, and
apply it through the SAME machinery the cylinder path already uses: `_corner_and_cylinder`'s
wedge-swap analogue, `_accepted` (valid, 1 solid, 0 free edges) per patch, `_same_feature`
identity by axis line + overlapping span, then the final `_passes_gate`.

Keep every existing behaviour for cylinder candidates unchanged.

## 4. VERIFICATION COMMANDS

```bash
cd /home/tommaso/projects/mesh2step
python3 -m mesh2step.feature /home/tommaso/corpora/mechparts/12.stl -o /tmp/t12.step --no-fallback
python3 -m mesh2step.feature /home/tommaso/corpora/mechparts/23.stl -o /tmp/t23.step --no-fallback
```
2-6 minutes each; FOREGROUND, wait. If one exceeds your shell timeout, use
`~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- '<cmd> > <log> 2>&1'` and poll
`~/.claude/scripts/job status <name>`. Never `pgrep`/`ps`, never `nohup`/`setsid`/`&`.

Measure (scratch script outside the repo) — count faces BY TYPE, and report support:
```python
import sys, collections; sys.path.insert(0,'/home/tommaso/projects/mesh2step')
from mesh2step.feature import _mesh, measure, _read, cylinder_radii, mesh_cylinder_radii
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS
for p,o in (('12','/tmp/t12.step'),('23','/tmp/t23.step')):
    tri=_mesh(f'/home/tommaso/corpora/mechparts/{p}.stl')
    m=measure(o,tri); shp=_read(o)
    br=sorted(cylinder_radii(shp)); mr=sorted(mesh_cylinder_radii(tri))
    cov=sum(1 for r in mr if any(abs(r-b)<=0.01*max(r,1e-9) for b in br))
    sup=sum(1 for b in br if any(abs(b-r)<=0.01*max(b,1e-9) for r in mr))
    fm=TopTools_IndexedMapOfShape(); TopExp.MapShapes_s(shp,TopAbs_FACE,fm)
    fc=collections.Counter(str(BRepAdaptor_Surface(TopoDS.Face_s(fm.FindKey(i))).GetType()).split('.')[-1]
                           for i in range(1,fm.Extent()+1))
    print(p,'valid',m['valid'],'solids',m['solids'],'free',m['free_edges'],
          'dv%',round(m['dv_pct'],4),'p95',round(m['dist_p95'],4),
          'coverage',f'{cov}/{len(mr)}','cyl_support',f'{sup}/{len(br)}')
    print('   faces',dict(fc))
```

Lint: `ruff check tools/feature_recon/radial_fillets.py` — currently clean, keep it clean.
(`ruff` may not be on PATH; `python3 -m ruff check ...` works.)

## 5. TERMINATION CRITERIA — all must hold, each backed by captured stdout

- [ ] **part 12 torus face count rises above 20**, and part 23's above 38 — report both before
      and after, and say how many previously vetoed patches are now built
- [ ] both parts: `valid=True`, `solids=1`, `free_edges=0`
- [ ] `abs(dv_pct) <= 1.0`; `dist_p95 <= 0.005*diag` (12 = 196.57, 23 = 216.0)
- [ ] coverage does not drop (12 >= 17/30, 23 >= 36/80)
- [ ] **cylinder support must not fall** — part 12 is 21/21 today. Report before and after.
- [ ] no previously built radius disappears
- [ ] `ruff check tools/feature_recon/radial_fillets.py` passes
- [ ] the diff touches only `tools/feature_recon/radial_fillets.py`

## 6. GUARDRAILS

- **Do not remove or loosen the cylinder veto.** It is correct. Add a torus path beside it.
- **Never add a face the mesh does not support.** Adding invented geometry is worse than adding
  nothing, and is an automatic failure.
- Never widen dv, p95, validity or solid-count gates.
- If a patch cannot be built validly as a torus, skip it and continue.
- Minimal diff, no refactors, no new dependencies.
- If after 3 iterations torus counts have not risen with every gate intact, STOP and report the
  measurements. An honest negative with numbers beats a guess.
- Completion is never declared without stdout and exit codes.
