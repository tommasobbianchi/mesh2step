# DELEGATION SPECIFICATION — n11: RANSAC cylinder fallback when the seed band finds nothing

Worker: opencode / `deepseek/deepseek-v4-pro`. Worktree: `scratchpad/wt-n11`, branch
`n11-ransac-fallback`, base `0bac065` (clean, 0 modified files at dispatch).

## 0. WHY (read this; it determines what "correct" means)

The Phase B cylinder seed band asks whether a facet turns between 5° and 60° from its
neighbour. That question contains a tessellation term, so the same part re-exported at a finer
resolution stops being recognised. Measured on one user file, `test01.stl`:

| mesh | triangles | cylinder regions | cylinders in STEP |
|---|---|---|---|
| OCCT diag/1000 | 348 | 4 (= truth) | 4 |
| OCCT diag/2000 | 484 | 3 | 3 |
| **user's own export** | **1308** | **0** | **0** |

Recall collapses as the mesh gets *finer*. Lowering the floor to 2° was measured and
**refuted** — it recovers this file but loses 55 truth cylinders on the TO-252 family
(`n5-seed-gates.spec.md`, P94).

A RANSAC fit asks instead "do these facets lie on a common cylinder", which has no
tessellation term. A numpy prototype recovers all four of `test01`'s cylinders at **0.03 %**
radius accuracy. Corpus-wide it is far worse than the current segmenter (75 matched vs 220)
because it only proposes cylinders and therefore paves spheres and cones with tubes — so it
must **never** run where the existing segmenter already works.

Hence: fallback only, on components where Phase B claimed **zero** cylinder regions. There the
engine currently ships nothing, so the fallback cannot regress anything.

## 1. TARGET GOAL

**Functional objective.** When, for a component, the segmenter finishes `claimCylindersB1`
having claimed zero cylinder regions, and `STL2STEP_N11_RANSAC_FALLBACK` is set in the
environment, detect cylinders by RANSAC over that component's facets and commit them as
cylinder regions through the SAME region-construction path Phase B1 uses. With the variable
unset, behaviour must be bit-identical to `0bac065`.

**Writable files:**
- `src/refit_ransac.cpp` (new)
- `src/refit_ransac.hpp` (new)
- `src/refit_segment.cpp` (call site only)
- `src/refit_internal.hpp` (declaration only, if that is where stage helpers are declared)
- `CMakeLists.txt` (add the new source)

Everything else is READ-ONLY. Do not touch `src/refit_build.cpp`, `src/refit_grow.cpp`,
`src/refit.hpp`, `refs/`, or any test.

**Open bindings (defaults assumed, change only with a measurement):**
- Fallback runs per COMPONENT, at the same granularity `claimCylindersB1` works on.
- If RANSAC finds nothing, the component proceeds exactly as today.

## 2. THE ALGORITHM — already validated, port it, do not redesign it

Reference implementation, **read it first**:
`/tmp/claude-1000/-home-tommaso-projects-mesh2step/55ed36d6-4f09-4e83-a602-2227174fbd8a/scratchpad/ransac/ransac_cyl.py`

It is ~170 lines of numpy and it works. Port its logic, not its style:

1. Point set = triangle centroids + unit facet normals + areas, for the component's facets.
2. Sample two oriented points (second drawn from the first's kd-tree neighbourhood, ranked
   25 %-100 % of k=64, never the nearest — nearly parallel normals give an ill-posed axis).
3. Axis `d = n1 x n2`, rejected when `|n1 x n2| < sin(3°)`. Centre = intersection of the two
   normal lines projected into the plane perpendicular to `d`. Radius = mean distance.
4. Score inliers: `|dist_to_axis - r| <= eps` AND `|radial_dir . n| >= cos(alpha)`.
5. Refit: axis = smallest singular vector of the inlier normals; then a 2-D algebraic circle
   fit in the plane perpendicular to it. Re-select inliers. Three passes.
6. Accept a candidate only if angular coverage around the axis `>= 45°` and `r <= 0.5 * diag`.
7. Remove its inliers; repeat until no candidate reaches `max(8, 0.005 * nFacets)` inliers.

**Tuned constants, measured — use exactly these:** `eps = 0.0015 * bboxDiag`, `alpha = 10°`,
`min_spread = 45°`, `min_frac = 0.005`, `k = 64`, 3000 seed iterations per extraction round.
A facet-size-adaptive `eps` was tried and made every case worse; do not reintroduce it.

**Determinism is mandatory.** Fixed seed, `std::mt19937` with a literal seed, no
`std::random_device`, no time, no unordered-container iteration order in any path that affects
output. This project gates on byte-identical STEP DATA sections; a nondeterministic fallback is
an automatic reject.

**No new dependency.** No Eigen, no CGAL. `refit_segment.cpp`'s include ban (see the comment
above `segment()` in `src/refit.hpp:~214`) applies to the new files too: `gp_` value types and
`math_` solvers only — no `TopoDS_*`, `BRep*`, `Geom*`, `Poly_*`, `ShapeFix_*`. The 3x3 SVD and
the circle fit must be written in-TU, as the existing PCA/Jacobi code in this module is.

## 3. INTEGRATION

Call site is `runStages` in `src/refit_segment.cpp:40`, immediately after
`claimCylindersB1(mv, p, tol, work)` and before `claimFilletsC1`:

```cpp
if (!claimCylindersB1(mv, p, tol, work)) return false;
// n11: the Phase B seed band is dihedral-angle based, so a finely tessellated cylinder
// turns by less than thetaCylLo per facet and is never seeded. Where B claimed NOTHING,
// fall back to a tessellation-independent fit. Env-gated; off => bit-identical.
if (!claimCylindersRansacN11(mv, p, tol, work)) return false;
```

`claimCylindersRansacN11` MUST return immediately, having changed nothing, when either:
- `std::getenv("STL2STEP_N11_RANSAC_FALLBACK") == nullptr`, or
- the component already has one or more cylinder regions claimed.

**Reuse, do not reimplement, the region construction.** Find how `claimCylindersB1` in
`src/refit_grow.cpp` turns an accepted set of facets into a cylinder `Region` — the fields
`ax`, `radius`, `uMin/uMax`, `vMin/vMax`, `closed360`, `outwardNormal` all have exact
definitions in `src/refit.hpp:113-145` (the seam must land on a real mesh-vertex azimuth;
`outwardNormal` is the sign of `sum area*(n . rho_hat)`). Call that same code with RANSAC's
facet sets. If it is not currently reachable, extract it into a helper **without changing its
behaviour** — but prefer a call over a refactor.

Downstream is deliberately untouched: the existing fit/accept stage is the quality gate. On
`test01` it already took RANSAC's 4 cylinders and passed 2. That is the intended behaviour, not
a bug to fix.

## 4. BUILD (exact — this is not the default recipe and guessing will fail)

```bash
cd <worktree>
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DCASROOT=/snap/freecad/current/usr \
  -DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF \
  -DSTL2STEP_BUILD_TESTS=OFF \
  -DCMAKE_EXE_LINKER_FLAGS='-L/home/tommaso/.local/share/mesh2step-native/lib -l:libfreeimage.so.3'
cmake --build build -j8
```

**Never pass `-DOpenCASCADE_DIR`** — it selects OCCT's package config instead of the project's
own `FindOpenCASCADE.cmake` and the build fails. At runtime:
`export LD_LIBRARY_PATH=$HOME/.local/share/mesh2step-native/lib`.

## 5. ACCEPTANCE — all four, each backed by captured stdout

Let `E = build/stl2step`, `U = <scratchpad>/user`, `C = $HOME/corpora/cadbench`.
Cylinders are counted **from the written STEP**, never from a log counter — this engine has
shipped three lying counters (`watertight`, `smoothRevertedComponents`, `smoothCylinders`):

```bash
python3 -c "
import sys; sys.path.insert(0,'$HOME/projects/mesh2step/scripts')
from ab_corpus import cyl_faces_in_step; from pathlib import Path
print(cyl_faces_in_step(Path(sys.argv[1])))" <file.step>
```

- [ ] **A1 — builds clean.** `cmake --build build -j8` exits 0, no new warnings.
- [ ] **A2 — OFF is bit-identical.** For 20 models from `C` (`*_normal.stl`, alphabetical
      first 20), the STEP written with the variable unset is **byte-identical in its DATA
      section** to the one written by a binary built from unmodified `0bac065`. Any difference
      fails the gate. Build the baseline binary in a second build dir; do not skip this.
- [ ] **A3 — the reproducer recovers.** `STL2STEP_N11_RANSAC_FALLBACK=1 $E $U/test01.stl -o
      /tmp/n11_test01.step --engine trueform` → cylinder faces in the STEP **> 0**.
      Expected 2 (RANSAC proposes 4, the existing fit/accept passes 2). Report the actual
      radii; truth is `11.5882 / 13.7518 / 16.6858 / 39.8345`.
- [ ] **A4 — no crash, no hang, ON, across the corpus.** All 203 `*_normal.stl` in `C` with the
      variable set: zero non-zero exit codes other than the engine's documented `2`
      (ok-with-warnings), zero timeouts at 300 s each. Report the count of models whose
      cylinder count CHANGED versus the OFF run, and name them.

If A2 fails, stop and report — it means the fallback is running when it must not, and no other
result matters.

## 6. GUARDRAILS

- **Long jobs run under watchjob.** Any sweep over the corpus outlives its shell:
  `~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- '<cmd>'`, and redirect the child's
  stdout to a file (watchjob loses it otherwise, and a trailing pipe fakes exit 0). Never
  answer "is it running" with `pgrep`/`ps` — use `~/.claude/scripts/job status <name>`.
- No commits, no pushes, no branch deletion, no `git` beyond reading. The diff stays in the
  worktree for review.
- Minimal diff. No drive-by refactors, no reformatting, no renaming.
- Do not edit, weaken or delete any test, and do not widen a tolerance to pass a gate.
- Report honestly: if a gate fails, say which and show the output. A partial diff with an
  accurate failure report is worth more than a green claim.
