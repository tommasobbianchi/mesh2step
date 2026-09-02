# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP — M2

Project: `/home/tommaso/projects/mesh2step`, branch `v2-parity`, clean tree at `7ed6a80`.
Python 3.12, OCCT via `OCP` (`cadquery-ocp`). Editable install already resolves to
`src/mesh2step/` — do not reinstall.

M1 is landed: the RESULT contract, exit codes, component splitting and the sewing repair
path all exist and all 16 `-k verbatim` parity cases are green. `--engine trueform` is
currently **accepted and silently downgraded to verbatim with a warning**. M2 removes that
downgrade for the planar case.

## 1. TARGET GOAL

**Functional Objective.** Implement TrueForm **planar** segmentation and analytic face
building, so that `--engine trueform` reproduces the stl2step reference engine on meshes
whose faces are all planar. Four things must hold:

1. **Segmentation.** Each *clean* component (one that closed from shared-topology
   construction, i.e. did not need the sewing path) is segmented into planar **regions** —
   maximal sets of adjacent triangles lying on a common plane within the reference's
   tolerance — plus the triangles no region claimed, which stay as individual **facet**
   faces. The reference's parameters at the golden invocation are its defaults:
   `smoothTolMM = 0.0` (auto, derived from the bbox diagonal — read the source for the
   derivation, do not invent one), `smoothAngleDeg = 2.0`, fillets enabled.

2. **Analytic face build.** Each planar region becomes ONE `Geom_Plane` face carrying the
   region's outer boundary (and inner boundaries where the region has holes), built on the
   component's existing shared vertices. Leftover triangles are built as before. A region
   that cannot produce a valid face falls back to its own triangles rather than failing the
   component.

3. **Accept / revert probe.** After building, the component's faces are assembled into a
   probe shell and accepted only if the shell is closed AND `BRepCheck_Analyzer` reports it
   valid. If either check fails, the whole component **reverts to the faceted build** and
   `smoothRevertedComponents` is incremented. This is the mechanism by which
   `nonprismatic-control` declines in the reference — do not weaken it.

4. **RESULT smooth counters.** In trueform mode the RESULT payload gains these keys, with
   the reference's meanings:

   | key | meaning |
   |---|---|
   | `smoothPlanes` | planar regions found by segmentation, all components |
   | `smoothCylinders`, `smoothFillets`, `smoothDistinctRadii` | 0 in M2 — M3/M4 |
   | `smoothRejected` | regions rejected during segmentation |
   | `smoothFacetFaces` | triangles no region claimed |
   | `facesAfterSmooth` | face count after the analytic build |
   | `smoothSkippedComponents` | components not segmented because the mesh was dirty |
   | `smoothBuiltPlanes`, `smoothBuiltCylinders`, `smoothBuiltFillets` | as actually built |
   | `smoothBuiltComponents` | components that accepted the analytic build |
   | `smoothRevertedComponents` | components that reverted to faceted |
   | `smoothMaxDevMM`, `smoothMaxEdgeTolMM`, `smoothVolPredictedMM3` | emitted, not gated |

   `facesBeforeUnify` in trueform mode is the face count of the **built** compound, i.e.
   after the analytic substitution and before the coplanar unify pass.

**The reference implementation is on disk and is the specification.** Port it; do not
reinvent it. `refs/stl2step/src/` — `refit_segment.cpp` (entry), `refit_grow.cpp` (region
growing), `refit_build.cpp` (face construction), `refit_math.cpp`, `refit_internal.hpp`,
`refit.hpp` (the `MeshView` / `Region` / `RegionSet` / `SegmentParams` / `RefitStats`
contracts), and `stl2step.cpp` around lines 545-660 for the orchestration. **Only the
planar path is in scope for M2**: cylinders, law-band arc recognition, fillets and the
prismatic rebuild are M3-M5 and must be left as stubs that find nothing.

**Ground truth measured from the reference binary, 2026-09-02**, so you can check
intermediate state and not only the final assertion. `STL2STEP_SEGMENT_SUMMARY=1
refs/stl2step/RUN.sh <stl> -o /tmp/x.step --engine trueform --unify-angle 5` prints a
per-component region dump; on `S09.stl` it prints exactly:

```
engine segment root=17 regions=22 rejected=8 planes=22 cylinders=0 fillets=0 facetIslands=5
engine segment root=9  regions=6  rejected=0 planes=6  cylinders=0 fillets=0 facetIslands=0
```

with the 22 regions of the first component covering 28 of its 42 triangles, leaving 14
facet triangles in 5 islands, and the second component's 6 regions covering all 12 of its
triangles. **Note the arithmetic gap and resolve it from the source, not by tuning a
constant:** 28 region faces + 14 facet faces + nothing else = 42, but the golden
`facesBeforeUnify` is **44**. Two more faces are emitted than regions-plus-leftovers
predicts. The likely cause is a region that cannot be built as one face being demoted to
its own triangles while still counting as a plane in the segmentation stats — confirm in
`refit_build.cpp` before implementing.

**Target Files / Scope (writable).**

- `src/mesh2step/refit/__init__.py` *(new)* — package marker and the public entry points
- `src/mesh2step/refit/mesh_view.py` *(new)* — per-component adjacency: triangle→edge
  indices and orientations, edge→triangle map, normals, areas, bbox diagonal
- `src/mesh2step/refit/segment.py` *(new)* — planar region growing, rejection, facet islands
- `src/mesh2step/refit/build.py` *(new)* — analytic planar faces, facet fallback, the
  closed/valid probe
- `src/mesh2step/refit/stats.py` *(new)* — the counter record
- `src/mesh2step/convert.py` — trueform orchestration, per-component accept/revert
- `src/mesh2step/result.py` — the smooth keys in the payload
- `src/mesh2step/cli.py` — drop the "trueform falls back to verbatim" warning
- `src/mesh2step/brep_build.py` — only if the per-component build must expose its vertices

**Read-only. Modifying any of these invalidates the run.** `tests/**` — including
`tests/test_parity.py` and every byte under `tests/data/` — `tools/**`, `refs/**`,
`pyproject.toml`, `webapp/**`, `README.md`, and every `src/mesh2step/*.py` not listed above.
`refs/**` is read-only but you are expected to READ it; that is the point.

**Open Bindings.**

- *Auto tolerance.* `smoothTolMM = 0.0` means "derive it". **Default: whatever
  `refit_segment.cpp` / `refit_grow.cpp` derive it from — port the expression verbatim.** Do
  not substitute a fixed epsilon; a hard-coded tolerance will fit these two fixtures and
  fail M3-M5.
- *Region face with holes.* Whether a planar region's inner loops become wires on the same
  face or separate faces is not pinned by the harness. **Default: the reference's
  behaviour**; if the source is ambiguous, one face with inner wires.
- *Parallelism.* The reference segments components on a thread pool. **Default: serial.**
  The harness does not measure time and threads would only add nondeterminism.
- *New CLI flags.* `--smooth-tol` / `--smooth-angle` / `--no-smooth-fillets` exist in the
  reference. **Default: do NOT add them.** The golden set uses the defaults, they are not in
  the F2P set, and an untested flag is a liability.

## 2. HARNESS ENVIRONMENT & GROUND TRUTH

**Harness Interface.** There is no harness binary. The harness **is** the ordered §3 command
sequence and its exit codes; that sequence is the sole deterministic oracle of task status.

**Fail-to-Pass (F2P).** `tests/test_parity.py -k "trueform and (cube or S09)"` — **6 tests
collected, 5 red and 1 green at baseline**, verified 2026-09-02:

```
FAILED test_result_invariants_match_reference[cube.trueform]  - facesBeforeUnify ...
FAILED test_result_invariants_match_reference[S09.trueform]
FAILED test_exit_code_matches_reference[cube.trueform]        - assert 2 == 0
FAILED test_exit_code_matches_reference[S09.trueform]         - assert 2 == 0
FAILED test_geometric_overlay_is_total[S09.trueform]          - overlay 0.999998712677
```

All 6 must pass. A run collecting any number other than 6 is a broken binding, not a pass.

**Regression subset (must not break).** `tests/test_parity.py -k verbatim` — **16 tests, all
green at baseline.** Trueform work that changes verbatim output is a defect.

**Pass-to-Pass (P2P).** `tests/` excluding `tests/test_parity.py` — **45 passed** at
baseline, none red. Any drop is a regression you caused.

**Known-red and NOT your problem.** The 10 remaining trueform cases — `handle-lock`,
`nonprismatic-control`, `Body11`, `Body28` — stay red through M2. Do not chase them, do not
skip them, do not mark them xfail. In particular `nonprismatic-control` is expected to end
M2 red; it is M4.

**Test Integrity Constraint.** Modifying, mocking, skipping, xfailing or otherwise tampering
with the harness suites or the golden fixtures in `tests/data/reference/` is prohibited and
invalidates the run. The golden set is the specification. Regenerating it via
`tools/capture_reference.py` is likewise prohibited here.

## 3. VERIFICATION COMMANDS

1. Lint & Static Analysis:
   `/usr/bin/python3 -m ruff check --output-format=json src/mesh2step`
2. Harness Patch Evaluation (P2P):
   `/usr/bin/python3 -m pytest -q tests --ignore=tests/test_parity.py`
3. Targeted Test Execution (F2P):
   `/usr/bin/python3 -m pytest -q "tests/test_parity.py" -k "trueform and (cube or S09)"`
4. Regression subset:
   `/usr/bin/python3 -m pytest -q "tests/test_parity.py" -k verbatim`

The interpreter is pinned deliberately: this host has no `.venv`, the package is installed
`--user` in editable mode, and a different `python` on PATH will not import `mesh2step`
from `src/`.

## 4. CONVERGENCE LOOP (FORMAL EXECUTION PROTOCOL)

Iterate until termination criteria hold, ceiling **6** iterations:

1. **EDIT:** apply scoped modifications to in-scope source files.
2. **EXECUTE:** run the §3 sequence in order.
3. **PARSE:** consume the structured payload — failing assertions, stack traces, ruff records.
4. **PATCH:** derive root cause from the parsed diagnostics and refine the edit.

Suggested order of attack: read the reference's segment/build sources FIRST and port the
data structures before writing any algorithm; then `cube` (six one-region-per-face planes,
no leftovers, no rejections — it isolates the plumbing from the growing); then `S09`, which
is where rejection, facet islands and the two-extra-faces question actually bite.

On ceiling without convergence: stop, do **not** report success, return the last diff plus
the unresolved failure set.

## 5. TERMINATION CRITERIA (BOOLEAN GATES)

Finalize IF AND ONLY IF all gates hold, each backed by captured stdout:

- [ ] `harness_exit_code == 0` for §3 slots 2, 3 and 4
- [ ] `fail_to_pass_status == ALL_PASSED` — **6/6** in slot 3
- [ ] `regression_subset == ALL_PASSED` — **16/16** in slot 4
- [ ] `pass_to_pass_regressions == 0` — slot 2 reports **45 passed**, no fewer
- [ ] `new_linter_diagnostics == 0` — the post-edit `(file, code)` multiset over
      `src/mesh2step` introduces no code absent from the baseline and raises no count.
      **Post-M1 baseline, 29 diagnostics**, measured 2026-09-02:
      `brep_build.py::BLE001 1, brep_build.py::I001 1, brep_build.py::TRY003 1,
      cli.py::E501 4, convert.py::E501 1, cut.py::F401 1, cut.py::TRY003 4,
      cut.py::TRY004 1, dedup.py::E501 1, dedup.py::TRY003 1, io_mesh.py::TRY003 5,
      merge_coplanar.py::E501 2, repair.py::TRY003 2, step_export.py::TRY003 4`.
      **Absolute zero is NOT the gate**; the pre-existing diagnostics are out of scope and
      fixing them is a scope violation.

## 6. GUARDRAILS & EXECUTION CONSTRAINTS

- **Zero-Assumption Rule:** completion is never declared without verifiable stdout and exit
  codes. Paste the actual pytest summary lines.
- **Never run git.** No commit, no push, no branch, no stash, no checkout. Leave the work in
  the working tree; the orchestrator reviews it by diff and owns every git action.
- **No fixture fitting.** No fixture name, no golden face count, no magic volume, and no
  branch keyed on triangle count may appear anywhere in `src/`. The tolerance is derived
  from the mesh, never tuned until a number matches. A gate passed by a constant that
  encodes the answer is a failed run, and it will be checked for.
- **Blast Radius Limitation:** minimal diffs, strictly inside the §1 scope; no drive-by
  refactors, no dependency additions, no reformatting of untouched lines. `numpy`, `trimesh`
  and `cadquery-ocp` are already available — nothing else may be installed or imported.
- **Oracle Supremacy:** the harness verdict is final. A parity case you believe is wrong is
  still the specification; report the disagreement with the measurement that shows it and
  stop, do not edit the test to agree. A spec error you catch is worth more than a
  workaround you hide — this happened in M1 and the executor was right.
- **Baseline Obligation:** before the first EDIT, run §3 once and record the baseline.
- **No fake solids.** The existing invariant holds: a component that will not close is
  written as an open shell and counted, never wrapped as a solid with an invented volume.
- **Long commands go under `watchjob`,** never `nohup`, `setsid`, a bare `&`, or a polling
  loop: `~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- <command>`, status via
  `~/.claude/scripts/job status <name>`, never `pgrep` or `ps | grep`. The F2P subset runs
  in ~10 s and is fine in the foreground; the full parity suite is ~50 s and `Body11` /
  `Body28` dominate it.
