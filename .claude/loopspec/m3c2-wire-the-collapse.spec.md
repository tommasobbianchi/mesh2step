# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

M3c-2 — wire the analytic curves into the chain collapse, and give `_build_cylindrical_face`
the pcurve/orientation handling that analytic edges on a cylinder need.

Second half of `.claude/loopspec/m3c-analytic-intersection-curves.spec.md`; M3c-1
(`m3c1-analytic-curve-constructors.spec.md`, commit `3b1f4ae`) is already in.

## 0. WHAT M3c-1 LEFT YOU, AND THE ONE TRAP

`build.py` already has, tested and dead:

- `_Curve` with `NONE, LIN, CIRC, ELIPS`
- `_cylinder_iso_circle`, `_plane_perp_cylinder`, `_plane_v_on_cylinder`
- `_constructed_plane_cyl_cap` (plane perpendicular to cylinder -> CIRCLE)
- `_constructed_generator` (plane containing the axis -> LIN)
- `_curve_residual` and `_make_edge_from_curve` extended to the new kinds

Their unit tests are `tests/test_refit_curves.py` — **read-only for you, and they must
stay green.**

**One deviation from the reference you must know about.** `_constructed_generator` carries
a `|n·a| > sin(3°) -> decline` guard that `refit_build.cpp:767` does not have. The
reference omits it because its only caller, `planeCylSideContact` (`refit_build.cpp:982`),
establishes the precondition first. When you wire the dispatch you are becoming that
caller: if you replicate the reference's caller-side check, the guard is redundant but
harmless; if you do not, the guard is what keeps an oblique plane from receiving a
confidently wrong generator line. Do not remove it without replacing it.

**The trap that killed the first attempt at full M3c:** it changed the collapse while
`_build_cylindrical_face` could still only bind polyline edges, so analytic edges on a
cylinder had no pcurves, faces failed, and it regressed `S09.trueform` from green to
failing before running out of time. Build the pcurve path FIRST, then flip the collapse.

## 1. TARGET GOAL

- **Functional Objective:** make `handle-lock.trueform` reproduce stl2step exactly.

  Golden RESULT, every field gated:

      facesBeforeUnify 40    facesAfterUnify 35     facesAfterSmooth 35
      smoothPlanes 23        smoothCylinders 17     smoothDistinctRadii 11
      smoothRejected 0       smoothFacetFaces 0
      smoothBuiltPlanes 23   smoothBuiltCylinders 15
      smoothBuiltComponents 1  smoothRevertedComponents 0
      meshVolumeMM3 15868.884516   stepVolumeMM3 15868.831779   exit code 0

  Where we stand at `3b1f4ae`, measured — unchanged by M3c-1, as intended:

      {'facesBeforeUnify': (40, 908), 'facesAfterUnify': (35, 194),
       'smoothPlanes': (23, 15), 'smoothCylinders': (17, 14),
       'smoothDistinctRadii': (11, 10), 'smoothBuiltPlanes': (23, 0),
       'smoothBuiltCylinders': (15, 0), 'smoothBuiltComponents': (1, 0),
       'smoothRevertedComponents': (0, 1)}

  **The defect is located; do not re-diagnose it.** Instrumented on handle-lock:

      _build_cylindrical_face   28 ok,  0 fail
      _build_planar_face        22 ok,  4 FAIL   (regions of 4, 4, 6, 6 triangles)
      build_faces -> ok=True, 908 faces, built_as = {EXPLODED_TO_FACETS: 29}

  Four region failures exceed the two-round explode cap, `explode_all` runs, the whole
  component falls back to one face per triangle, and every `smoothBuilt*` counter reads 0
  as a consequence. Those four small planes border the stage-L law bands, and the boundary
  chain between a plane and a cylinder is still emitted as a mesh polyline — a chord chain
  that does not lie on the cylinder — so the small plane cannot close a valid face
  against it.

- **Target Files / Scope (writable):**
  - `src/mesh2step/refit/build.py`
  - `src/mesh2step/refit/segment.py` (only if a `Region` field is genuinely missing)
  - `src/mesh2step/refit/__init__.py`, `src/mesh2step/refit/stats.py`

  Read-only: `tests/**` (including `tests/test_refit_curves.py`), `tools/**`, `refs/**`,
  `pyproject.toml`, `webapp/**`, `src/mesh2step/convert.py`, `src/mesh2step/brep_build.py`,
  `src/mesh2step/refit/lawband.py`, `src/mesh2step/refit/mesh_view.py`.

- **Open Bindings:** none.

## 2. HARNESS ENVIRONMENT AND GROUND TRUTH

- **Harness Interface:** the ordered §3 sequence and its exit codes are the sole oracle.
- **Fail-to-Pass (F2P):** `tests/test_parity.py -k "handle-lock and trueform"` — 3 tests,
  all 3 failing now. All 3 must pass.
- **Pass-to-Pass (P2P):** `tests/` minus `test_parity.py` — **50 green now** (45 plus
  M3c-1's five). Plus the §3.4 regression subset — **22 green now, including all three
  S09.trueform cases.** S09 is the fixture the first attempt broke; treat it as the
  canary and run §3.4 often.
- **Test Integrity Constraint:** modifying, mocking, skipping or xfailing any test, or
  regenerating any golden under `tests/data/`, is prohibited and invalidates the run.

## 3. VERIFICATION COMMANDS

1. Lint: `/usr/bin/python3 -m ruff check --output-format=json src/mesh2step`
2. P2P: `/usr/bin/python3 -m pytest -q tests --ignore=tests/test_parity.py`
3. F2P: `/usr/bin/python3 -m pytest -q "tests/test_parity.py" -k "handle-lock and trueform"`
4. Regression: `/usr/bin/python3 -m pytest -q "tests/test_parity.py" -k "verbatim or (trueform and (cube or S09))"`

**Never run the whole parity file.** The four `Body*` trueform cases take about ten
minutes each and belong to M5.

## 4. WHERE THE ANSWER IS

| What | Where |
|---|---|
| `pickIntAna` — choosing a solution by chain residual | `refs/stl2step/src/refit_build.cpp:584-758` |
| `constructedCylCylGenerator`, `meshAnchoredCylGenerator`, `bestCylCylConstructed` | `refit_build.cpp:785-858` |
| `constructedLinOnBothCylinders` | `refit_build.cpp:859-949` |
| `intersectSurfaces` — the dispatch on the two region types | `refit_build.cpp:950-1000` |
| `planeCylSideContact` — the caller whose precondition the M3c-1 guard stands in for | `refit_build.cpp:982` |
| building a face on a cylinder: pcurves, seam, orientation | `refit_build.cpp:2085-2230, 2300-2340` |
| `BRepCheck_BadOrientationOfSubshape` handling already in our port | `build.py` `_build_cylindrical_face` |

## 5. CONVERGENCE LOOP

Iterate to the §6 gates, ceiling **6** iterations. EDIT, EXECUTE §3 in order, PARSE, PATCH.

Suggested order — it is the order the first attempt got wrong:

1. **First** give analytic edges their pcurves on a cylindrical face. Until an edge built
   from a `_Curve` can carry a pcurve on `Geom_CylindricalSurface`, flipping the collapse
   can only make things worse. Keep the collapse plane|plane while you do this; §3.4 must
   stay 22/22 throughout, because nothing you have changed yet should alter output.
2. **Then** extend `_intersect_surfaces` to dispatch plane|cylinder and cylinder|cylinder,
   and let `_pick_int_ana` choose among the constructed candidates by chain residual.
3. **Then** watch `_build_planar_face FAIL` go to 0.

The instrument that produced the numbers in §1 — use it after every edit:

```python
import importlib; B = importlib.import_module("mesh2step.refit.build")
import mesh2step.convert as C
from collections import Counter
res = Counter()
for name in ("_build_planar_face", "_build_cylindrical_face"):
    orig = getattr(B, name)
    def mk(orig=orig, name=name):
        def spy(region, *a):
            r = orig(region, *a)
            res[f"{name} {'ok' if r is not None else 'FAIL'}"] += 1
            return r
        return spy
    setattr(B, name, mk())
C.convert_trueform("tests/data/corpus/handle-lock.stl", "/tmp/hl.step", unify_angle=5.0)
print(dict(res))
```

Drive `_build_planar_face FAIL` to 0. Once no region fails, the explode ladder stops
firing and the `smoothBuilt*` counters leave zero by themselves. **Do not chase
`facesBeforeUnify` directly** — 908 is a consequence of the fallback and becomes 40 when
the build succeeds.

The reference will tell you what it did on this exact fixture:
`STL2STEP_LAWBAND_DIAG=1 ./refs/stl2step/RUN.sh tests/data/corpus/handle-lock.stl -o /tmp/ref.step --smooth --unify-angle 5.0 --quiet`
Other useful vars: `STL2STEP_SEGMENT_SUMMARY`, `STL2STEP_J6_DIAG`, `STL2STEP_FAIL_RID`,
`STL2STEP_COLLAPSE_DIAG`.

On ceiling without convergence: **stop, do not claim success**, return the diff and the
unresolved failure set. A partial run that leaves a green fixture red is worse than no run
at all — if you are out of budget, say so with the tree still passing §3.4.

## 6. TERMINATION CRITERIA (BOOLEAN GATES)

- [ ] `f2p == ALL_PASSED` — §3.3 reports **3 passed**.
- [ ] `p2p_regressions == 0` — §3.2 reports **50 passed**.
- [ ] `regression_subset == 22 passed` — §3.4, all three S09.trueform cases green.
- [ ] `new_linter_diagnostics == 0` — post-edit `(file, code)` multiset over the §1
      writable files adds no code absent from baseline and raises no count. Baseline:
      `{'I001': 1, 'TRY003': 17, 'BLE001': 1, 'E501': 8, 'F401': 1, 'TRY004': 1}` — 29.

## 7. GUARDRAILS

- **No fixture fitting.** No fixture name, triangle count or golden constant in a
  conditional. `40`, `35`, `23`, `17`, `11`, `908` must not appear as targets in the diff.
- **Declare what you stub**, at the point of definition, with the upgrade path named.
  Never return a plausible-looking value from an unimplemented path.
- **Oracle supremacy.** The harness verdict is final; report disagreement, do not edit tests.
- **Blast radius.** Minimal diffs inside §1. No new dependencies — stdlib, numpy, OCP only.
- **Zero-assumption rule.** No completion claim without the four captured stdouts.
