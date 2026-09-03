# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

M3c-1 — the analytic curve constructors, and NOTHING that changes converter behaviour.

First half of `.claude/loopspec/m3c-analytic-intersection-curves.spec.md`. Read that file
for the full diagnosis; this one is the binding contract and it is deliberately narrower.

## 0. WHY THIS IS SPLIT, AND THE ONE RULE THAT MATTERS

A previous run at the whole of M3c timed out (`exit 124`) after 7200s and left the tree
in a state that **regressed `S09.trueform` from green to failing** — `smoothRejected`
8 to 0, `smoothPlanes` 28 to 6, `smoothRevertedComponents` 0 to 1. That work was reverted.
Its own inline comment explained why it could not finish: collapsing a plane|cylinder
chain onto an analytic edge needs pcurve and orientation handling that
`_build_cylindrical_face` does not have, so it left the collapse plane|plane-only while
changing enough around it to break a passing fixture.

So this milestone builds **only the constructors**, under a gate that makes a regression
impossible to miss:

> **The converter's output must not change at all.** Every currently-green parity case
> must stay green with byte-identical RESULT counters. If any number in any RESULT
> payload moves, this milestone has failed, however good the new code looks.

Wiring the constructors into the chain collapse is M3c-2 and is explicitly OUT of scope.

## 1. TARGET GOAL

- **Functional Objective:** grow `build.py`'s `_Curve` from a two-kind type (`NONE`,
  `LIN`) into the reference's multi-kind `AnalyticCurve`, and port the constructors that
  produce the missing kinds, with unit tests that prove each one against geometry whose
  answer is known in closed form.

  Required constructors, all from the reference:
  - `cylinderIsoCircle` — the circle at a given v on a cylinder.
  - `planePerpCylinder`, `planeVOnCylinder` — is this plane perpendicular to the axis,
    and at what v does it cut.
  - `constructedPlaneCylCap` — plane perpendicular to a cylinder gives a CIRCLE.
  - `constructedGenerator` — plane containing the axis direction gives a LINE.
  - `_curve_residual` extended to the new kinds (a point's distance to a circle, to an
    ellipse), because every consumer of a curve picks solutions by residual.
  - `_make_edge_from_curve` extended to build a circular edge (this is why `ElCLib` is
    already imported: a circular edge needs its parameters, not just endpoints).

- **Target Files / Scope (writable):**
  - `src/mesh2step/refit/build.py` — the curve type, the constructors, the residual, the
    edge maker. **You may NOT change `_intersect_surfaces`'s dispatch, the chain-collapse
    decision, `_build_planar_face`, or `_build_cylindrical_face`.** Those are M3c-2.
  - `tests/test_refit_curves.py` — NEW FILE, yours to author. This is the sole exception
    to the read-only test rule and it exists only because the F2P criterion is to write it.

  Read-only: everything else, explicitly including the rest of `tests/**`, `tools/**`,
  `refs/**`, `pyproject.toml`, `webapp/**`, `src/mesh2step/convert.py`,
  `src/mesh2step/brep_build.py`, `src/mesh2step/refit/lawband.py`,
  `src/mesh2step/refit/segment.py`, `src/mesh2step/refit/mesh_view.py`.

- **Open Bindings:** none.

## 2. HARNESS ENVIRONMENT AND GROUND TRUTH

- **Harness Interface:** the ordered §3 sequence and its exit codes are the sole oracle.
- **Fail-to-Pass (F2P):** `tests/test_refit_curves.py`, which you author. Confirm it FAILS
  against unmodified source before you implement — a test that passes before the change
  proves nothing and invalidates the run.
- **Pass-to-Pass (P2P):** `tests/` minus `test_parity.py` — 45 tests green now, and the
  §3.4 regression subset — **22 tests green now, including all three S09.trueform cases.**
  This is the gate the previous attempt broke. It is not negotiable.
- **Test Integrity Constraint:** modifying, mocking, skipping or xfailing any EXISTING
  test, or regenerating any golden under `tests/data/`, is prohibited and invalidates the
  run. You may only create `tests/test_refit_curves.py`.

## 3. VERIFICATION COMMANDS

1. Lint: `/usr/bin/python3 -m ruff check --output-format=json src/mesh2step`
2. P2P: `/usr/bin/python3 -m pytest -q tests --ignore=tests/test_parity.py`
3. F2P: `/usr/bin/python3 -m pytest -q tests/test_refit_curves.py`
4. Regression: `/usr/bin/python3 -m pytest -q "tests/test_parity.py" -k "verbatim or (trueform and (cube or S09))"`

**Never run the whole parity file.** The four `Body*` trueform cases take about ten
minutes each and belong to M5.

## 4. WHERE THE ANSWER IS

Read these spans, not the whole reference.

| What | Where |
|---|---|
| `struct AnalyticCurve` — the shape `_Curve` must become | `refs/stl2step/src/refit_build.cpp:470-516` |
| `cylinderIsoCircle` | `refit_build.cpp:517-521` |
| `planePerpCylinder`, `planeVOnCylinder` | `refit_build.cpp:522-535` |
| `constructedPlaneCylCap` (plane perpendicular to cylinder -> circle) | `refit_build.cpp:759-766` |
| `constructedGenerator` (plane parallel to axis -> line) | `refit_build.cpp:767-784` |

In our port: `_Curve` at `build.py:210` (currently `NONE, LIN`), `_curve_residual`,
`_make_edge_from_curve`. `_is_analytic` already admits cylinders. `Region` already carries
`radius`, `closed360`, `u_min/u_max/v_min/v_max` and `ax`.

## 5. WHAT THE F2P TESTS MUST ASSERT

Closed-form geometry, not fixture replay. No STL file should appear in this test file.

1. **Plane perpendicular to a cylinder gives the right circle.** Build a cylinder region
   of known axis and radius R and a plane at height h perpendicular to it;
   `constructedPlaneCylCap` must return a CIRCLE of radius R whose centre lies on the
   axis at height h, to within `1e-9`.
2. **Plane containing the axis direction gives a generator line.** The returned LINE must
   be parallel to the axis to within `1e-9` and lie at distance R from it.
3. **A plane that is neither must produce no constructed curve** — the constructors
   decline rather than returning a plausible wrong answer.
4. **Residual behaves.** A point exactly on a constructed circle has residual `0` to
   within `1e-9`; a point displaced by `d` along the radius has residual `d`.
5. **A circular edge is buildable.** `_make_edge_from_curve` on a CIRCLE returns a
   non-null edge whose two vertices sit on the circle.

Every tolerance above is absolute and derived from the construction, so none of these
tests needs a fixture, a golden, or a tuned constant.

## 6. CONVERGENCE LOOP

Iterate to the §7 gates, ceiling **6** iterations. EDIT, EXECUTE §3 in order, PARSE, PATCH.

Order that keeps you honest: write `tests/test_refit_curves.py` FIRST, run §3.3, and
confirm it fails. Then implement. Then run §3.4 after every single edit — it is the gate
that catches the failure mode that killed the previous attempt, and it takes 80 seconds.

On ceiling without convergence: **stop, do not claim success**, return the diff and the
unresolved failure set.

## 7. TERMINATION CRITERIA (BOOLEAN GATES)

- [ ] `f2p == ALL_PASSED` — §3.3 green, and proven RED before the implementation.
- [ ] `p2p_regressions == 0` — §3.2 reports **45 passed**.
- [ ] `regression_subset == 22 passed` — §3.4. **All three S09.trueform cases green.**
- [ ] `converter_output_unchanged` — the RESULT counters for every fixture are what they
      were at `4ee36e1`. §3.4 passing is the machine-checkable form of this.
- [ ] `new_linter_diagnostics == 0` — post-edit `(file, code)` multiset over the §1
      writable files adds no code absent from baseline and raises no count. Baseline for
      `src/mesh2step`:
      `{'I001': 1, 'TRY003': 17, 'BLE001': 1, 'E501': 8, 'F401': 1, 'TRY004': 1}` — 29.
      Absolute zero is NOT the gate.

## 8. GUARDRAILS

- **Dead code is expected here and is fine.** The constructors will not be called by the
  converter at the end of this milestone. That is the design, not an oversight: they are
  wired up in M3c-2, behind their own F2P. Do not wire them early "so they do something".
- **No fixture fitting.** No fixture name or golden constant in a conditional.
- **Oracle supremacy.** The harness verdict is final; report disagreement, do not edit tests.
- **Blast radius.** Minimal diffs inside §1. No new dependencies — stdlib, numpy, OCP only.
- **Zero-assumption rule.** No completion claim without the four captured stdouts.
