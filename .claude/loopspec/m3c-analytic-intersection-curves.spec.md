# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

M3c — plane|cylinder and cylinder|cylinder analytic intersection curves. Final piece of
`.claude/loopspec/m3b-lawbands-and-cylinder-faces.spec.md`.

## 1. TARGET GOAL

- **Functional Objective:** make `handle-lock.trueform` reproduce stl2step exactly.

  Golden RESULT, every field gated:

      facesBeforeUnify 40    facesAfterUnify 35     facesAfterSmooth 35
      smoothPlanes 23        smoothCylinders 17     smoothDistinctRadii 11
      smoothRejected 0       smoothFacetFaces 0
      smoothBuiltPlanes 23   smoothBuiltCylinders 15
      smoothBuiltComponents 1  smoothRevertedComponents 0
      meshVolumeMM3 15868.884516   stepVolumeMM3 15868.831779   exit code 0

  Where we stand at commit `4ee36e1`, measured:

      {'facesBeforeUnify': (40, 908), 'facesAfterUnify': (35, 194),
       'smoothPlanes': (23, 15), 'smoothCylinders': (17, 14),
       'smoothDistinctRadii': (11, 10), 'smoothBuiltPlanes': (23, 0),
       'smoothBuiltCylinders': (15, 0), 'smoothBuiltComponents': (1, 0),
       'smoothRevertedComponents': (0, 1)}

  **The remaining defect is already located. Do not re-diagnose it.** Instrumented on
  handle-lock at `4ee36e1`:

      _build_cylindrical_face   28 ok,  0 fail
      _build_planar_face        22 ok,  4 FAIL   (regions of 4, 4, 6, 6 triangles)
      build_faces -> ok=True, 908 faces, built_as = {EXPLODED_TO_FACETS: 29}

  Four region failures exceed the two-round explode cap, `explodeAll` runs, and the whole
  component falls back to one face per triangle — which is why `facesBeforeUnify` reads
  908 and every `smoothBuilt*` counter reads 0.

  Those four small planes border the law bands claimed by stage L. A boundary chain
  between a plane and a cylinder is still emitted as a **mesh polyline**, because the
  chain-collapse machinery in `build.py` only knows plane|plane: `_Curve` has exactly two
  kinds, `NONE` and `LIN`, and `_pick_int_ana` only ever reads `iq.Line(i)`. A polyline
  boundary is a chord chain that does not lie on the cylinder, so the adjacent small
  plane cannot close a valid face against it.

  **The job: port the missing analytic curves so those chains collapse onto real
  geometry.** A plane cutting a cylinder perpendicular to its axis gives a CIRCLE; a
  plane containing the axis direction gives a generator LINE; two coaxial-ish cylinders
  give a generator line. Those are the cases the reference constructs.

- **Target Files / Scope (writable):**
  - `src/mesh2step/refit/build.py`   (the curve machinery and the chain collapse)
  - `src/mesh2step/refit/segment.py` (only if a Region field is genuinely missing)
  - `src/mesh2step/refit/__init__.py`, `src/mesh2step/refit/stats.py`

  Read-only: `tests/**`, `tools/**`, `refs/**`, `pyproject.toml`, `webapp/**`,
  `src/mesh2step/brep_build.py`, `src/mesh2step/convert.py`,
  `src/mesh2step/refit/lawband.py`, `src/mesh2step/refit/mesh_view.py`.

- **Open Bindings:** none.

## 2. HARNESS ENVIRONMENT AND GROUND TRUTH

- **Harness Interface:** the ordered §3 sequence and its exit codes are the sole oracle.
- **Fail-to-Pass (F2P):** `tests/test_parity.py -k "handle-lock and trueform"` — 3 tests,
  all 3 failing now. All 3 must pass.
- **Pass-to-Pass (P2P):** `tests/` minus `test_parity.py` — 45 tests, green now. Plus the
  §3.4 regression subset — 22 tests, green now.
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

Read these spans, not the whole reference. A previous executor burned its entire budget
reading `refit_grow.cpp` and `refit_build.cpp` end to end and delivered nothing.

| What | Where |
|---|---|
| `struct AnalyticCurve` — the multi-kind curve our `_Curve` has to become | `refs/stl2step/src/refit_build.cpp:470-516` |
| `cylinderIsoCircle` | `refit_build.cpp:517-521` |
| `planePerpCylinder`, `planeVOnCylinder` | `refit_build.cpp:522-535` |
| `pickIntAna` — how a solution is chosen by chain residual | `refit_build.cpp:584-758` |
| `constructedPlaneCylCap` (plane ⟂ cylinder → circle) | `refit_build.cpp:759-766` |
| `constructedGenerator` (plane ∥ axis → line) | `refit_build.cpp:767-784` |
| `constructedCylCylGenerator`, `meshAnchoredCylGenerator`, `bestCylCylConstructed` | `refit_build.cpp:785-858` |
| `constructedLinOnBothCylinders` | `refit_build.cpp:859-949` |
| `intersectSurfaces` — the dispatch on the two region types | `refit_build.cpp:950-1000` |

In our port the pieces to grow are `_Curve` (`build.py:210`, currently `NONE, LIN` only),
`_curve_residual`, `_pick_int_ana`, `_intersect_surfaces`, and `_make_edge_from_curve`
(a circular edge needs `ElCLib`-style parameters, which is why `ElCLib` is already
imported). `_is_analytic` already admits cylinders.

## 5. CONVERGENCE LOOP

Iterate to the §6 gates, ceiling **6** iterations. EDIT, then EXECUTE §3 in order, then
PARSE the mismatch dict, then PATCH.

The single most useful instrument, and how the numbers above were obtained — monkeypatch
the two builders and count:

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
firing, `built_as` stops being all-exploded, and the `smoothBuilt*` counters leave zero
by themselves. **Do not chase `facesBeforeUnify` directly** — 908 is a consequence of the
fallback, and it becomes 40 when the build succeeds.

On ceiling without convergence: **stop, do not claim success**, return the diff and the
unresolved failure set.

## 6. TERMINATION CRITERIA (BOOLEAN GATES)

- [ ] `f2p == ALL_PASSED` — §3.3 reports **3 passed**.
- [ ] `p2p_regressions == 0` — §3.2 reports **45 passed**.
- [ ] `regression_subset == 22 passed` — §3.4, unchanged from baseline.
- [ ] `new_linter_diagnostics == 0` — post-edit `(file, code)` multiset over the §1
      writable files introduces no code absent from baseline and raises no count.
      Baseline for `src/mesh2step`:
      `{'I001': 1, 'TRY003': 17, 'BLE001': 1, 'E501': 8, 'F401': 1, 'TRY004': 1}` — 29.
      Absolute zero is NOT the gate.

## 7. GUARDRAILS

- **No fixture fitting.** No fixture name, triangle count, or golden constant in a
  conditional. `40`, `35`, `23`, `17`, `11` and `908` must not appear as targets.
- **Declare what you stub.** If something is left unported, say so at the point of
  definition with a band guard and the upgrade path, the way M3a's coarse-band stubs did.
  Never return a plausible-looking number from an unimplemented path.
- **Oracle supremacy.** The harness verdict is final. Report disagreement, do not edit tests.
- **Blast radius.** Minimal diffs inside §1. No new dependencies — stdlib, numpy, OCP only.
- **Baseline obligation.** Run §3 once before the first edit and record it.
- **Zero-assumption rule.** No completion claim without the four captured stdouts.
