# FINDINGS2 — the absorb works; the remaining failure is pre-existing edge/face construction

Author: opencode (deepseek-v4-pro), worktree `absorb` (branch `feat/absorb`), 2026-09-18.
Live tree `/home/tommaso/projects/mesh2step` read-only, untouched. Diagnostic copy `diag/eb_diag.py`
(instrumented; `EB_ABSORB_FACETS=1` to exercise the absorb, `EB_DEBUG=1` for detail). All runs
were bare `edgebuild` on `mechparts/16.stl`, ~240 s each, under watchjob. Reproduce in §6.

---

## 0. Verdict in three lines

The absorb is **correct and necessary**: it solves the corner (28/28 at 4.2e-05) and the 296→13
"collapse" it produces is the *intended* same-surface merge, not the bug. `dist_p95 6.86` is **not**
caused by that collapse — the fitted surfaces stay within `2e-4` mm of the mesh through every
stage. The 6.86 comes from a **pre-existing edge/face bug** the absorb merely exposes: the oblique
intersection of the two diagonal R10 bores with the four tori. My §3 proposal (absorb) was the right
lever for the corner; the remaining failure is a different part of the pipeline and needs a
different fix (which I began and measured, §4).

---

## 1. Q1 — why 296 surfaces become 13 (MEASURED; the hypothesis is REFUTED)

`diag/eb_diag.py` logs a `MINDIST` (p95/max distance of mesh vertices to the nearest fitted
surface) at three checkpoints, and `EB_MERGE_LOG=1` logs every merge in the merge loop:

```
facet absorb: 7023 of 7055 planes absorbed into 296 curved surfaces
[MINDIST after-absorb] p95=0.0000 max=0.0002  surfaces Counter({torus:252, plane:46, cylinder:23, cone:11, sphere:10})
  [merge-same-TOLM] S44+S59 (torus)  ...  (hundreds of torus+torus merges)
  [merge-same-joint] S142+S152 (torus) -> res 2.31e-04
  [merge-absorb] S105(sphere) -> S44(torus) res 2.31e-04
[MINDIST after-merge] p95=0.0002 max=0.0002  surfaces Counter({cylinder:23, torus:6, sphere:5, plane:5})
3595 triangles of mixed curved regions moved ...
[MINDIST after-mixed] p95=0.0002 max=0.0002  surfaces Counter({cylinder:6, plane:5, torus:4, sphere:1})
```

- The collapse 296→16 is the merge loop (`edgebuild.py:891-1036`) plus the mixed pass
  (`:1050-1074`). It merges the ~250 near-identical torus fragments (each `major≈44` or `≈137`,
  `minor=10`) of the **four** real fillets back into four tori, via `merge-same-TOLM`
  (`:1029-1033`), `merge-same-joint` (`:1043-1048`), `merge-union-axis` (`:997-999`) and
  `merge-absorb` (`:953-955`). Every merge residual is `2.3e-4 … 2.9e-4` mm.
- **The geometry is never lost.** `MINDIST` max is `0.0002 mm` at after-absorb, after-merge AND
  after-mixed. The prompt's hypothesis — "absorbing thousands of facets makes regions large and
  mutually adjacent, so the pairwise absorb at `:851+` now finds almost every pair acceptable" —
  is **refuted**: the pairwise merges that fire are the *correct* same-surface joins (torus+torus
  fragments of one fillet, residual 2e-4), not spurious cross-surface unions.

So Q1's answer: the stage is the merge loop + mixed pass; the predicate is the same-kind joint
refit (`surface_ok` on the union, `:1046`) and same-TOLM merge (`:1030-1031`); and the test that
passes **should** pass — it is joining fragments of one surface.

---

## 2. Q2 — `dist_p95 6.86` is NOT the collapse; it is the torus face, and it was never the surfaces

Two measurements separate the surface fit from the solid:

**(a) Surfaces are exact through every stage.** `MINDIST` (nearest *surface*) is `2e-4 mm` at
after-absorb, after-merge, after-mixed (§1). The fitted surfaces are correct; nothing is lost in
the collapse.

**(b) The vertices that are 7 mm away are *on* a fitted surface.** `diag/worst.py` samples 2000
mesh vertices against the final STEP and finds the worst all at `z=2.627` / `z=17.373` in the
strip `x 2625–2718, y 2228–2237` (the diagonal-bore region), distance `7.249` mm. Computing those
same vertices against the *fitted* surfaces directly (13 dicts from the `EB_DEBUG` dump):

```
[2755.873, 2230.242, 2.627]  nearest: S151 torus 0.0 mm, S6 cyl 0.295, S368 plane 2.627
[2561.611, 2256.216, 2.627]  nearest: S142 torus 0.0 mm, S368 2.627, S449 6.425
[2784.868, 2286.36, 17.373]   nearest: S151 torus 0.0 mm, S7 0.867, S539 2.627
```

Every "missing" vertex sits **exactly on a torus surface (S142/S151) at 0.0 mm**, but 7.25 mm
from the *solid*. The geometry is not lost at the merge — it is lost at the **face**: the torus
face is trimmed to a boundary that does not cover the region the diagonal bore cuts through.

The 4 free edges are the fingerprint of the same defect. All four are owned by tori
(`free edges by OWNING face: {'Torus minor 10.0000': 4}`), all `BSplineCurve` at the
torus↔diagonal-cylinder junction (S151–S6, S7–S54, S7–S142). In the OFF baseline (no absorb,
`EB_CORNER_TOL=1e-5`) the same region gives **32** free edges and `dist_p95 12.18` — the absorb +
correct corner *reduces* the damage (32→4, 12.18→6.86) but does not create it.

So Q2's answer: the 6.86 is **not** the collapse. It was never a surface problem; it is a
face-boundary problem around the oblique bore↔torus intersections, pre-existing and merely exposed
once the corner was solved.

---

## 3. Q3 — the actual root cause of the 4 free edges, and a measured (partial) fix

### 3.1 The B-spline densify loop does not converge on oblique torus↔cylinder intersections

Instrumenting the B-spline fallback (`edgebuild.py:1960-1972`) shows the `dev` **plateau**, not
converge, for exactly the chains that end up free:

```
bspline chain 26 S151-S6 iter 0: dev 1.22e-02 … iter 5: dev 4.69e-03 npts 353 (limit 2.59e-04)
bspline chain 29 S151-S6 iter 0: dev 1.24e-02 … iter 5: dev 5.98e-03 npts 1057
bspline chain 35 S54-S7 iter 0: dev 5.05e-02 … iter 5: dev 1.25e-02 npts 481
bspline chain 37 S54-S7 iter 0: dev 1.22e-02 … iter 5: dev 1.21e-02 npts 257
```

`dev` (the B-spline's max distance to either surface) stays at `4.7e-3 … 1.2e-2` mm even with
hundreds of points — hundreds of times over the `1e-6*diag = 2.59e-4` acceptance. The point-
projection + `GeomAPI_Interpolate` path cannot represent this space curve. The B-spline is then
used anyway, `4e-3 … 1e-2` mm off the surfaces, and the faces built from it do not meet.

### 3.2 The intersection is multi-branch; OCCT's exact IntSS gives it

`GeomAPI_IntSS(torus, cylinder)` returns **4** intersection curves for S151×S6 (2 large loops +
2 small); the chains are the separate branches. The projection in `densify` bounces between them,
which is why `dev` oscillates instead of converging (chain 40: `5.5e-2 → 4.4e-1 → 1.2e-1 → … →
8.5e-3`).

### 3.3 The fix I ran: exact surface-surface intersection as a fallback

In `diag/eb_diag.py` I added `intss_edge()`: when the densify loop finishes with `dev >= 1e-5*diag`
and the chain is open, build both `Geom_Surface`s, `GeomAPI_IntSS`, pick the curve nearest the
chain's two corner points (A,B), trim to the nearest parameters, and make the edge (raising vertex
tolerances to the curve ends like `mk_edge`). Result, end-to-end on part 16:

| metric | baseline ON (absorb only) | + IntSS fallback |
|---|---|---|
| free-edge lengths | 52.69, 13.54, 12.47, 11.70 mm | **0.036, 0.028, 0.118, 0.138 mm** |
| `WIRE DROPPED` on cylinders | S0, S6, S7 | none |
| `valid` | False | **True** |
| `faces` | 18 | 16 |
| `dv_pct` | -0.343 | +0.254 |
| `dist_p95` | 6.861 | 6.861 |

The IntSS fallback is a real, measured improvement — it turns 4 long free edges (52 mm) into 4
tiny ones (≤0.14 mm), eliminates the dropped wires, and makes the shell `valid`. **It does not yet
reach `acceptable(m)`**: `free_edges` is still 4 (now tiny slivers at the tangent contacts, 8
tangent corners) and `dist_p95` is still 6.86 because the torus *face* is still trimmed short
around the bore (§2b). So this is a necessary step, not the whole fix.

---

## 4. Q4 — is the absorb at the right place?

**Yes.** The absorb belongs exactly where it is (immediately after the axis-refit rung, before the
merge loop): that is the only point where the torus identity exists (`major 43.97`, recovered by
the axis-refit from the large surviving patches) AND the facet planes are still intact. Moving it
earlier is impossible (no torus yet — measured in the first session); moving it later (into/after
the merge) is pointless (the merge has already welded the facets into flat patches, which is the
old `:851+` absorb that demonstrably cannot reach them).

The remaining blockers on part 16 are **not** the absorb's fault and are not fixed by repositioning
it:
1. the oblique bore↔torus intersection edges (free edges) — fixed by the IntSS fallback, §3.3;
2. the torus face boundary around those bores (the residual `dist_p95 6.86`) — still open, §5.

---

## 5. What remains for `acceptable(m)` on part 16

`dist_p95 6.86` persists in both the absorb-only and the absorb+IntSS builds because the torus
face is trimmed short. Concretely: S142 and S151 are `axis refit: sphere -> torus, 72/126 tris`
*at refit time* (they are the fillet rings around the R22.225 bosses S0/S1), and the two diagonal
R10 bores S6/S7 (`a=[±0.943, 0.332, 0]`) cut obliquely through them. The torus face's boundary
does not correctly incorporate those two bore holes, so the face excludes the bore-adjacent region
whose vertices then sit 7 mm from the solid. The next concrete step is to make the torus face
build its boundary from the four IntSS branch curves as holes (and orient them as holes), rather
than the current 2-loop "fillet ring" special case (`edgebuild.py:2097+`) which assumes a torus
has exactly two whole-circle loops. That is where I would go next; I have not yet run it
end-to-end.

---

## 6. Reproduce

```bash
cd /home/tommaso/projects/mesh2step/.worktrees/absorb/tools/feature_recon
# baseline: absorb only
EB_ABSORB_FACETS=1 /usr/bin/python3 edgebuild.py /home/tommaso/corpora/mechparts/16.stl /tmp/a16.step
# instrumented copy with the IntSS fallback (diag/eb_diag.py): absorb + exact intersections
EB_ABSORB_FACETS=1 EB_DEBUG=1 /usr/bin/python3 /home/tommaso/projects/mesh2step/.worktrees/absorb/diag/eb_diag.py \
    /home/tommaso/corpora/mechparts/16.stl /tmp/a16i.step
# worst-vertex probe against a written STEP
/usr/bin/python3 /home/tommaso/projects/mesh2step/.worktrees/absorb/diag/worst.py /tmp/a16i.step /home/tommaso/corpora/mechparts/16.stl
```

`diag/eb_diag.py` differs from the absorb `edgebuild.py` only by: the `MINDIST` checkpoints, the
`EB_MERGE_LOG` merge logging, the `bspline` iteration logging, and the `intss_edge` fallback
(`_surf_geom` / `_near_param` / `intss_edge` inserted before `TOLC = 1e-7*diag`, and the
`if dev >= 1e-5*diag` hook after the densify loop). Nothing in the live tree is modified.
