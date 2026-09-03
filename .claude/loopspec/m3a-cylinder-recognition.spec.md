# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

M3a — TrueForm cylinder RECOGNITION (segmentation only, no face building).

This is the first half of `.claude/loopspec/m3-trueform-cylinders.spec.md`. Read that
file for background; this one is the binding contract.

## 1. TARGET GOAL

- **Functional Objective:** port `claimCylindersB1` and the gate chain it calls from
  the reference C++ into the Python segmentation stage, so that the number of cylinder
  candidate seeds **rejected** by the G1-G5 gates matches stl2step exactly.

  The fixture that defines this milestone is S09, whose golden RESULT is:

      smoothCylinders 0       smoothRejected 8      smoothPlanes 28
      smoothBuiltCylinders 0  smoothBuiltPlanes 28  facesBeforeUnify 44

  Read that carefully, because it is the whole point of the slice: B1 seeds **eight**
  cylinder candidates on S09 and **all eight fail the gates**. Not one cylinder region
  survives. So a faithful port changes `smoothRejected` from 0 to 8 and changes
  **nothing else** — no plane count, no face count, no volume, no geometry. If your
  change moves any other field on any fixture, the port is wrong. And a `smoothRejected`
  of 8 reached by any route other than eight genuinely-evaluated-and-failed candidates
  is a fabricated counter, not an implementation.

- **Target Files / Scope (writable):**
  - `src/mesh2step/refit/segment.py`   (the port lands here)
  - `src/mesh2step/refit/stats.py`     (only if a census field is genuinely missing)
  - `src/mesh2step/refit/__init__.py`  (exports only)

  Everything else is **read-only**, explicitly including `src/mesh2step/refit/build.py`,
  `src/mesh2step/convert.py`, `src/mesh2step/brep_build.py`, `tests/**`, `tools/**`,
  `refs/**`, `pyproject.toml`, `webapp/**`. Cylinder *face building* is M3b and is NOT
  in this slice: B1 may produce cylinder regions in the RegionSet, but you must not
  teach `build.py` to build them.

- **Open Bindings:** none.

## 2. HARNESS ENVIRONMENT AND GROUND TRUTH

- **Harness Interface:** the ordered §3 command sequence and its exit codes are the sole
  oracle. The reference implementation is authority on *behaviour*; the harness is
  authority on *done*.
- **Fail-to-Pass (F2P):** `tests/test_parity.py -k "S09 and trueform"` — 3 tests,
  currently 1 failing on `{'smoothRejected': (8, 0)}`. All 3 must pass.
- **Pass-to-Pass (P2P):** `tests/` minus `test_parity.py` — 45 tests, all green now.
  Plus the regression subset in §3.4 — 19 tests, all green now.
- **Test Integrity Constraint:** modifying, mocking, skipping or xfailing any test, or
  regenerating any golden fixture under `tests/data/`, is prohibited and invalidates the
  run. The goldens were captured from the reference binary; they are the specification.

## 3. VERIFICATION COMMANDS

1. Lint and static analysis:
   `/usr/bin/python3 -m ruff check --output-format=json src/mesh2step`
2. Harness patch evaluation (P2P):
   `/usr/bin/python3 -m pytest -q tests --ignore=tests/test_parity.py`
3. Targeted test execution (F2P):
   `/usr/bin/python3 -m pytest -q "tests/test_parity.py" -k "S09 and trueform"`
4. Regression subset:
   `/usr/bin/python3 -m pytest -q "tests/test_parity.py" -k "verbatim or (trueform and cube)"`

**Never run the whole parity file.** The four `Body*` trueform cases take about ten
minutes each and are not part of this milestone.

## 4. WHERE THE ANSWER IS

Do not read the whole reference. The previous executor spent its entire budget reading
and delivered nothing. These are the exact spans:

| What | Where |
|---|---|
| the claim itself | `refs/stl2step/src/refit_grow.cpp:1476-1836` |
| the reject census, G1..G4 to Reject reasons | `refit_grow.cpp:1813-1827` |
| `evaluateCommit`, the gate chain | `refit_grow.cpp:810-992` |
| `classifyG1Reject` | `refit_grow.cpp:644-...` |
| `computeOutwardCylinder` | `refit_grow.cpp:602-643` |
| `testT1Running`, `testG1Commit`, `areaWeightedNbar`, `axisTiltStats`, `testG1CommitSeedAxis`, `epsCylRing`, `maxVertexResidual`, `estimateNBandsFromPatch` | `refit_grow.cpp:332-475` |
| `fillCylinderRegion`, `mergeCoaxialCylinders`, `seedPairAxis` | `refit_grow.cpp:993-1130` |
| `estimateFullCircleSides`, `refineCylinderRadius` | `refs/stl2step/src/refit_math.cpp:570-700` |
| struct definitions: `Work`, `Provisional`, `Region`, `Reject`, `Gate`, `CommitEval`, `DerivedTols` | `refs/stl2step/src/refit_internal.hpp` |

The existing Python port in `segment.py` is your style guide: it already has `SurfType`,
`Reject`, `Origin`, the `DerivedTols` scaffold with `theta_cyl_lo/hi` and `theta_bin`
fields, and the `RegionSet.rejected` list that the census in `convert.py` already reads.
Match its naming and its determinism conventions. The C++ sort orders are load-bearing:
`sortRegions(work.rejected)` at `refit_grow.cpp:1834` exists so the census is stable.

## 5. CONVERGENCE LOOP

Iterate to the §6 gates, ceiling **6** iterations:

1. **EDIT** — scoped changes to §1 writable files only.
2. **EXECUTE** — run §3 in order, 1 then 2 then 3 then 4.
3. **PARSE** — read the failing assertion and the mismatched-field dict, which names the
   exact counter and the exact expected value.
4. **PATCH** — derive the cause from the diagnostic and from the C++ span above.

A useful intermediate probe: the mismatch dict prints `{'smoothRejected': (expected,
got)}`. `got` climbing 0, 3, 8 as you implement gates is the port converging. `got`
overshooting past 8 means your seeding is too permissive, not that a gate is too strict.

On ceiling without convergence: **stop, do not claim success**, return the diff and the
unresolved failure set.

## 6. TERMINATION CRITERIA (BOOLEAN GATES)

Finalize IF AND ONLY IF all hold, each backed by captured stdout:

- [ ] `f2p == ALL_PASSED` — §3.3 reports **3 passed**.
- [ ] `p2p_regressions == 0` — §3.2 reports **45 passed**.
- [ ] `regression_subset == 19 passed` — §3.4, unchanged from baseline.
- [ ] `new_linter_diagnostics == 0` — the post-edit `(file, code)` multiset over the §1
      writable files introduces no code absent from the baseline and raises no count.
      Baseline fingerprint for `src/mesh2step`:
      `{'I001': 1, 'TRY003': 17, 'BLE001': 1, 'E501': 8, 'F401': 1, 'TRY004': 1}` — 29
      total. **Absolute zero is NOT the gate**; the pre-existing 29 are out of scope and
      fixing them is a scope violation.

## 7. GUARDRAILS

- **No fixture fitting.** No fixture name, triangle count, or golden constant may appear
  in a conditional. Every threshold must be derived from the mesh or ported verbatim from
  the reference. Grepping your diff for `S09`, for `908`, or for `8` used as a target
  must come up empty.
- **Oracle supremacy.** The harness verdict is final. A golden you believe is wrong is
  still the specification: report the disagreement and stop, do not edit the test.
- **Blast radius.** Minimal diffs inside §1. No drive-by refactors, no reformatting of
  untouched lines, no new dependencies — stdlib, numpy and OCP only.
- **Baseline obligation.** Run §3 once before your first edit and record it, so you can
  tell a regression you caused from one that was already there.
- **Zero-assumption rule.** Never declare completion without the four captured stdouts.
