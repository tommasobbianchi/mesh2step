# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP — M3

Project: `/home/tommaso/projects/mesh2step`, branch `v2-parity`, clean tree at `baf72ce`.
Python 3.12, OCCT via `OCP` (`cadquery-ocp`). Editable install already resolves to
`src/mesh2step/` — do not reinstall.

M1 and M2 are landed. `src/mesh2step/refit/` already contains the MeshView, the planar
region growing, the analytic plane face build, the explode ladder and the accept/revert
probe, and `cube.trueform` matches the reference exactly. M3 adds the **curved** half.

## 1. TARGET GOAL

**Functional Objective.** Reproduce the stl2step reference engine on `handle-lock.stl` and
close `S09.stl` in trueform mode. Four things must hold:

1. **Cylinder seeding and the G1-G4 candidate gates.** The reference grows cylinder
   candidates from seed triangles and puts each through four gates; a candidate failing
   G1-G4 (but not G5) is recorded in `RegionSet.rejected` and counted in `smoothRejected`.
   **This pass runs on every mesh, including all-planar ones** — it is why `S09.trueform`
   reports `smoothRejected: 8` while finding zero cylinders, and that single number is the
   only thing still red on S09. Port `refit_grow.cpp`'s `Gate` enum, its four gate tests and
   the rejection record faithfully; the count is an observable, not a target to tune toward.

2. **Law-band arc recognition.** A CAD-exported mesh is the deterministic output of a
   tessellator, so a radius is recovered by the closed-form inverse `R = w / (2 sin(theta/2))`
   with **self-calibrated** law parameters, not by least-squares fitting. Law-driven
   segmentation claims arc bands *before* plane absorption, splits mixed-radius chimeras
   rather than averaging them, and splits chains whose per-strip radii disagree. Source:
   `refit_lawband.cpp`, `refit_chains.cpp`, and the cylinder half of `refit_grow.cpp`.

3. **Cylindrical face build.** An accepted cylinder region becomes a
   `Geom_CylindricalSurface` face on the component's shared vertices, with the same F4
   tolerance-budget rule M2 established for planes: absorb the fit residual into tolerance
   if it fits within `_mesh_tol_cap`, otherwise explode the region to its triangles rather
   than poison adjacent faces. `cylinderPostFitOk` (the sagitta/R gate) and
   `partialFaceTolCap` are part of this. Seamed 360-degree cylinders and the two-halves
   fallback are in `refit_build.cpp`.

4. ~~**The revert path must reproduce the verbatim build exactly.**~~ **WITHDRAWN
   2026-09-03 — this item was my error and is NOT in scope.** It read:

   | fixture / mode | facesBeforeUnify | facesAfterUnify | stepVolumeMM3 |
   |---|---|---|---|
   | handle-lock / verbatim | 908 | **194** | 16038.862197 |
   | handle-lock / trueform, reverted (ours) | 908 | **180** | 16042.022724 |

   I read the 194-vs-180 gap as a defect in our revert path. It is not. `stl2step.cpp:914-931`
   runs a **second** coplanar merge — "smooth-flat", at a mesh-jitter-derived angle — guarded
   by `smooth && !forceSew && nTri >= 500 && nTri <= 1200`, and its own comment says it exists
   for *"faceted islands (revert fallback and analytic+facet mixes)"*. handle-lock has 908
   triangles, so the reference would run it too on a reverted component. The 194 figure comes
   from **verbatim** mode, where the `smooth &&` guard keeps the pass off entirely.

   So the two numbers were never comparable, and a reverted component is deliberately *not*
   byte-equivalent to verbatim. There is no bug here to fix. `convert.py:493-506` already
   ports this pass faithfully; the only fidelity gaps left are that ours omits `weldTol` from
   `epsMesh` and omits the `!forceSew` guard, both of which are M4 housekeeping, not this
   milestone.

**Ground truth.** `handle-lock.trueform` golden, every field gated:

```
facesBeforeUnify 40   facesAfterUnify 35   facesAfterSmooth 35
smoothPlanes 23   smoothCylinders 17   smoothDistinctRadii 11   smoothRejected 0
smoothFacetFaces 0   smoothBuiltPlanes 23   smoothBuiltCylinders 15
smoothBuiltComponents 1   smoothRevertedComponents 0
meshVolumeMM3 15868.884516   stepVolumeMM3 15868.831779   exit code 0
```

Note `smoothCylinders 17` against `smoothBuiltCylinders 15`: seventeen cylinder regions are
found, fifteen become analytic faces, and the two that do not go through the explode ladder —
the same mechanism M2 built for planes, which is why `smoothFacetFaces` stays 0 and
`facesBeforeUnify` is 40 rather than 38. Also note the analytic rebuild *corrects* the
volume: 15868.83 against verbatim's 16038.86 on the same mesh.

`STL2STEP_SEGMENT_SUMMARY=1 refs/stl2step/RUN.sh <stl> -o /tmp/x.step --engine trueform
--unify-angle 5` prints the reference's per-region plan including every cylinder radius, and
`STL2STEP_LAWBAND_DIAG=1` dumps the law-band decisions. **Use them.** Comparing your region
set against the reference's directly is far cheaper than inferring it from a failing
assertion, and M2 was solved that way.

**Target Files / Scope (writable).**

- `src/mesh2step/refit/lawband.py` *(new)* — the tessellation-law inverse and its
  self-calibration
- `src/mesh2step/refit/chains.py` *(new)* — arc chains, per-strip radius agreement, chimera
  split
- `src/mesh2step/refit/segment.py` — cylinder seeding, the G1-G4 gates, the rejection record
- `src/mesh2step/refit/build.py` — cylindrical faces; the faceted-revert fix
- `src/mesh2step/refit/stats.py`, `src/mesh2step/refit/__init__.py` — counters and exports
- `src/mesh2step/convert.py` — only if the orchestration needs the new counters
- `src/mesh2step/brep_build.py` — only if the revert fix requires sharing its facet builder

**Read-only. Modifying any of these invalidates the run.** `tests/**` — including
`tests/test_parity.py` and every byte under `tests/data/` — `tools/**`, `refs/**`,
`pyproject.toml`, `webapp/**`, `README.md`. `refs/**` is read-only but you are expected to
READ it in depth; porting it is the task.

**Open Bindings.**

- *Fillet strips.* `smoothFillets` stays 0 in M3; fillet recovery is M4. Leave the fillet
  path a stub that finds nothing.
- *Prismatic rebuild and DXF.* M5. Not in scope.
- *Parallelism.* Serial, as in M2. The harness does not measure time.
- *`smoothDistinctRadii`.* The reference counts distinct radii across accepted cylinder
  regions. **Default: distinct values under the same rounding the reference applies** — read
  it, do not invent a tolerance.

## 2. HARNESS ENVIRONMENT AND GROUND TRUTH

**Harness Interface.** There is no harness binary. The harness **is** the ordered §3 command
sequence and its exit codes; that sequence is the sole deterministic oracle of task status.

**Fail-to-Pass (F2P).** `tests/test_parity.py -k "trueform and (handle-lock or S09)"` —
**6 collected, 4 red and 2 green at baseline**, verified 2026-09-03:

```
FAILED test_result_invariants_match_reference[S09.trueform]        - {'smoothRejected': (8, 0)}
FAILED test_result_invariants_match_reference[handle-lock.trueform] - facesBeforeUnify ...
FAILED test_exit_code_matches_reference[handle-lock.trueform]       - assert 2 == 0
FAILED test_geometric_overlay_is_total[handle-lock.trueform]        - volume 16042.02 vs 15868.83
```

All 6 must pass. A run collecting any other number is a broken binding, not a pass.

**Regression subsets (must not break).**
- `tests/test_parity.py -k verbatim` — **16 green** at baseline.
- `tests/test_parity.py -k "trueform and cube"` — **3 green** at baseline.

**Pass-to-Pass (P2P).** `tests/` excluding `tests/test_parity.py` — **45 passed**, none red.

**Known-red and NOT your problem.** `nonprismatic-control.trueform` (3 cases) is M4: the
reference reverts that component and we currently accept an analytic build for it. The four
`Body` trueform cases are M5. Do not chase them, do not skip them, do not mark them xfail.

**Test Integrity Constraint.** Modifying, mocking, skipping, xfailing or otherwise tampering
with the harness suites or the golden fixtures in `tests/data/reference/` is prohibited and
invalidates the run. The golden set is the specification. Regenerating it via
`tools/capture_reference.py` is likewise prohibited here.

## 3. VERIFICATION COMMANDS

1. Lint and static analysis:
   `/usr/bin/python3 -m ruff check --output-format=json src/mesh2step`
2. Harness patch evaluation (P2P):
   `/usr/bin/python3 -m pytest -q tests --ignore=tests/test_parity.py`
3. Targeted test execution (F2P):
   `/usr/bin/python3 -m pytest -q "tests/test_parity.py" -k "trueform and (handle-lock or S09)"`
4. Regression subset:
   `/usr/bin/python3 -m pytest -q "tests/test_parity.py" -k "verbatim or (trueform and cube)"`

The interpreter is pinned deliberately: this host has no `.venv`, the package is installed
`--user` in editable mode, and a different `python` on PATH will not import `mesh2step` from
`src/`. **Never run the whole parity file**: the four `Body` trueform cases take about ten
minutes each (measured: Body11 trueform 593 s against verbatim 11.5 s, with the C++ reference
itself needing 80 s), which is why every command above is scoped.

## 4. CONVERGENCE LOOP (FORMAL EXECUTION PROTOCOL)

Iterate until termination criteria hold, ceiling **6** iterations:

1. **EDIT:** apply scoped modifications to in-scope source files.
2. **EXECUTE:** run the §3 sequence in order.
3. **PARSE:** consume the structured payload — failing assertions, stack traces, ruff records.
4. **PATCH:** derive root cause from the parsed diagnostics and refine the edit.

Suggested order of attack: the G1-G4 gates FIRST, since they close S09 on their own and cost
nothing in geometry — that slice is now split out as
`.claude/loopspec/m3a-cylinder-recognition.spec.md`; then law-band recognition and the
cylindrical face build together,
checked against `STL2STEP_SEGMENT_SUMMARY` region by region before you look at the assertion.

On ceiling without convergence: stop, do **not** report success, return the last diff plus the
unresolved failure set.

## 5. TERMINATION CRITERIA (BOOLEAN GATES)

Finalize IF AND ONLY IF all gates hold, each backed by captured stdout:

- [ ] `harness_exit_code == 0` for §3 slots 2, 3 and 4
- [ ] `fail_to_pass_status == ALL_PASSED` — **6/6** in slot 3
- [ ] `regression_subsets == ALL_PASSED` — **19/19** in slot 4
- [ ] `pass_to_pass_regressions == 0` — slot 2 reports **45 passed**, no fewer
- [ ] `new_linter_diagnostics == 0` — the post-edit `(file, code)` multiset over
      `src/mesh2step` introduces no code absent from the baseline and raises no count.
      **Post-M2 baseline, 29 diagnostics**, measured 2026-09-03:
      `brep_build.py::BLE001 1, brep_build.py::I001 1, brep_build.py::TRY003 1,
      cli.py::E501 4, convert.py::E501 1, cut.py::F401 1, cut.py::TRY003 4,
      cut.py::TRY004 1, dedup.py::E501 1, dedup.py::TRY003 1, io_mesh.py::TRY003 5,
      merge_coplanar.py::E501 2, repair.py::TRY003 2, step_export.py::TRY003 4`.
      **Absolute zero is NOT the gate**; the pre-existing diagnostics are out of scope and
      fixing them is a scope violation.

## 6. GUARDRAILS AND EXECUTION CONSTRAINTS

- **Zero-Assumption Rule:** completion is never declared without verifiable stdout and exit
  codes. Paste the actual pytest summary lines.
- **Never run git.** No commit, no push, no branch, no stash, no checkout. Leave the work in
  the working tree; the orchestrator reviews it by diff and owns every git action.
- **No fixture fitting.** No fixture name in a conditional, no golden face count, no magic
  volume, no branch keyed on triangle count. Radii come from the tessellation law with
  self-calibrated parameters; tolerances are derived from the mesh. A gate passed by a
  constant that encodes the answer is a failed run, and the diff will be read for exactly
  that.
- **Blast Radius Limitation:** minimal diffs, strictly inside the §1 scope; no drive-by
  refactors, no dependency additions, no reformatting of untouched lines. `numpy`, `trimesh`
  and `cadquery-ocp` are already available — nothing else may be installed or imported.
- **Oracle Supremacy:** the harness verdict is final. A parity case you believe is wrong is
  still the specification; report the disagreement with the measurement that shows it and
  stop, do not edit the test to agree. This has already paid off twice on this project: an
  executor caught a defect in the oracle in M1, and a measurement forced a milestone boundary
  to move in M2.
- **Baseline Obligation:** before the first EDIT, run §3 once and record the baseline.
- **No fake solids.** A component that will not close is written as an open shell and
  counted, never wrapped as a solid with an invented volume.
- **Long commands go under `watchjob`,** never `nohup`, `setsid`, a bare `&`, or a polling
  loop: `~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- <command>`, status via
  `~/.claude/scripts/job status <name>`, never `pgrep` or `ps | grep`.
