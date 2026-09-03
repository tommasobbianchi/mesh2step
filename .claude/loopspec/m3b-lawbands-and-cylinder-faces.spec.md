# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

M3b — TrueForm law-band recognition, the coarse-band helpers, and cylindrical face
building. Second half of `.claude/loopspec/m3-trueform-cylinders.spec.md`; M3a
(`m3a-cylinder-recognition.spec.md`, commit `a991e93`) is already in.

## 1. TARGET GOAL

- **Functional Objective:** make `handle-lock.trueform` reproduce stl2step exactly. It is
  the corpus's real mechanical part: 908 triangles, 17 cylinders across 11 distinct radii,
  and it is the fixture the whole TrueForm engine exists for.

  Golden RESULT, every field gated:

      facesBeforeUnify 40    facesAfterUnify 35     facesAfterSmooth 35
      smoothPlanes 23        smoothCylinders 17     smoothDistinctRadii 11
      smoothRejected 0       smoothFacetFaces 0
      smoothBuiltPlanes 23   smoothBuiltCylinders 15
      smoothBuiltComponents 1  smoothRevertedComponents 0
      meshVolumeMM3 15868.884516   stepVolumeMM3 15868.831779   exit code 0

  Where we stand after M3a, measured 2026-09-03:

      {'facesBeforeUnify': (40, 908), 'facesAfterUnify': (35, 194),
       'smoothPlanes': (23, 51), 'smoothCylinders': (17, 14),
       'smoothDistinctRadii': (11, 0), 'facesAfterSmooth': (35, 194),
       'smoothBuiltPlanes': (23, 0), 'smoothBuiltCylinders': (15, 0),
       'smoothBuiltComponents': (1, 0), 'smoothRevertedComponents': (0, 1)}

  Read the shape of that: **planes over-count (51 against 23) while cylinders
  under-count (14 against 17)**. That is one defect, not two. Plane growing is currently
  eating surface that belongs to arc bands, because the law-band stage does not exist yet.

- **Target Files / Scope (writable):**
  - `src/mesh2step/refit/lawband.py`  (new — the L stage and its helpers)
  - `src/mesh2step/refit/segment.py`  (wire L in; see §4.1 for where)
  - `src/mesh2step/refit/build.py`    (cylindrical faces)
  - `src/mesh2step/refit/stats.py`, `src/mesh2step/refit/__init__.py`
  - `src/mesh2step/convert.py`        (census only, if a counter genuinely needs it)

  Read-only: `tests/**`, `tools/**`, `refs/**`, `pyproject.toml`, `webapp/**`,
  `src/mesh2step/brep_build.py`.

- **Open Bindings:** none.

## 2. HARNESS ENVIRONMENT AND GROUND TRUTH

- **Harness Interface:** the ordered §3 sequence and its exit codes are the sole oracle.
- **Fail-to-Pass (F2P):** `tests/test_parity.py -k "handle-lock and trueform"` — 3 tests,
  all 3 failing now. All 3 must pass.
- **Pass-to-Pass (P2P):** `tests/` minus `test_parity.py` — 45 tests, green now. Plus the
  §3.4 regression subset — **22** tests, green now (it includes S09 and cube trueform, so
  a law-band stage that disturbs the M3a gate census will be caught immediately).
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

### 4.1 Stage order — the reason planes over-count

`refs/stl2step/src/refit_segment.cpp:47-51` is the whole pipeline:

```cpp
if (!claimLawBandsL(mv, p, tol, work)) return false;   // L runs FIRST
if (!claimCylindersB1(mv, p, tol, work)) return false; // then B1
if (p.doFillets) claimFilletsC1(...);                  // then C1 (M4)
```

Law bands are claimed **before** cylinder growing, and both before the A3 plane commit.
Our `segment()` currently calls B1 with no L stage, so tessellated arc bands fall through
to plane growing and get committed as 51 planes. Wire L in at the reference's position.

### 4.2 Spans to port

| What | Where |
|---|---|
| `claimLawBandsL` | `refs/stl2step/src/refit_grow.cpp:2057-2456` |
| `lawBandsMergeable` | `refs/stl2step/src/refit_lawband.cpp:932-...` |
| law-band geometry helpers: `recoverAxisDir`, `collectUniqueVerts`, `cluster1d`, `uniquePositions`, `lsBisectorCenter`, `circumcenter2`, `circumMedianCenter`, `azimuth`, `rhoOf`, `clusterAngles` | `refit_lawband.cpp:163-380` |
| `LawBand` struct, `DerivedTols` | `refs/stl2step/src/refit_internal.hpp` (`LawBand` near :251) |
| **`refineCylinderRadius`** | `refs/stl2step/src/refit_math.cpp:613-...` |
| **`archChainRadiusFromPatch`** | `refs/stl2step/src/refit_math.cpp:1663-...` |
| their call sites in the commit gate | `refit_grow.cpp:834-890` |
| cylindrical surface build: `cylSurfaceForRegion`, `asCyl`, `cylForIntersect`, plane/cylinder and cylinder/cylinder intersection curves | `refs/stl2step/src/refit_build.cpp:170-200, 522-600, 761-1000` |

### 4.3 The two stubs M3a left, which you MUST fill

`segment.py` has `_refine_cylinder_radius` and `_arch_chain_radius_from_patch` returning
`False` behind a `ponytail:` comment naming the ceiling. That was correct for M3a — S09 is
54 triangles and never reaches them. **handle-lock is 908 triangles and lands squarely in
the 500..1200 coarse-fusion band**, so both run on every candidate here. Filling them is
the first task of this milestone, not cleanup. `coarse_fusion_band()` already exists.

## 5. CONVERGENCE LOOP

Iterate to the §6 gates, ceiling **6** iterations. EDIT, then EXECUTE §3 in order, then
PARSE the mismatch dict, then PATCH.

Suggested order, each step observable in the mismatch dict before you move on:

1. Fill the two coarse-band helpers. `smoothCylinders` should move off 14 and
   `smoothDistinctRadii` off 0 — the radii are what those helpers compute.
2. Port and wire the L stage. `smoothPlanes` should fall from 51 toward 23 as arc bands
   stop being absorbed into planes.
3. Build cylindrical faces. Only then can `smoothBuilt*` leave zero and
   `smoothRevertedComponents` reach 0.

Do not chase `facesBeforeUnify` directly. It is 908 today because the component reverts to
one face per triangle; it becomes 40 as a consequence of the build succeeding, not as a
target to aim at.

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
  conditional. Every threshold derived from the mesh or ported verbatim. In particular
  `17`, `23`, `11`, `35`, `40` and `908` must not appear as targets in your diff. A radius
  count of 11 that comes from anywhere but eleven measured distinct radii is a lie.
- **Declare what you stub.** M3a's stubs were acceptable *because they said so at the
  point of definition and named the fixture class that would need them*. If you leave
  anything unported, do the same: a band guard, a `ponytail:` comment, and the upgrade
  path. Never return a plausible-looking number from an unimplemented path.
- **Oracle supremacy.** The harness verdict is final. Report disagreement, do not edit tests.
- **Blast radius.** Minimal diffs inside §1. No new dependencies — stdlib, numpy, OCP only.
- **Baseline obligation.** Run §3 once before the first edit and record it.
- **Zero-assumption rule.** No completion claim without the four captured stdouts.
