# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

Project: `/home/tommaso/projects/mesh2step` (branch `main`). Python 3.12, OCCT via `OCP`
(`cadquery-ocp`). Editable install already resolves to `src/mesh2step/` — do not reinstall.

## 1. TARGET GOAL

**Functional Objective.** Make `mesh2step`'s CLI reproduce the `stl2step` reference engine
in **verbatim** mode, field for field and solid for solid. Concretely, all four must hold:

1. **RESULT contract.** The CLI accepts `--engine verbatim|trueform`, `--unify-angle <deg>`
   and `--quiet`, and prints as its **last stdout line** exactly `RESULT {json}` — one line,
   no trailing text. The object carries at least these keys with these meanings:

   | key | type | meaning |
   |---|---|---|
   | `ok` | bool | a STEP file was written (possibly with warnings) |
   | `input`, `output` | str | resolved paths |
   | `error` | str | present **only** when `ok` is false |
   | `triangles` | int | triangles read from the mesh |
   | `vertices` | int | vertices after welding |
   | `components` | int | manifold bodies the mesh split into |
   | `solids` | int | solids written |
   | `openShells` | int | components that could not close |
   | `facesBeforeUnify`, `facesAfterUnify` | int | face count around the coplanar merge |
   | `meshVolumeMM3`, `stepVolumeMM3` | float | source vs re-read volume (mm³) |
   | `volumeDeltaPct` | float | round-trip volume error; `-1` if not measured |
   | `watertight` | bool | every component closed with consistent winding |
   | `seconds` | float | wall clock |
   | `warnings` | list[str] | every warning emitted, in order |

   `--quiet` suppresses the existing human-readable stats block; without it, that block is
   still printed first and `RESULT` remains the last line. `--engine trueform` is **accepted
   and falls back to verbatim with a warning** in this milestone — it is implemented in M2–M5.

2. **Exit codes.** `0` clean · `2` STEP written but with warnings (open shell, volume
   mismatch, invalid shape) · `1` failed, no output written. These are stl2step's semantics
   and the harness compares them directly.

3. **Component splitting.** A mesh containing several disjoint or non-manifold-joined bodies
   is split into manifold components, each built and closed independently, and all of them
   are written to one STEP file. This is the measured v1 gap: on `Body11.stl` v1 reports
   `nonmanifold_edges=69, watertight=no, solid=no`, while the reference returns
   **2 solids, watertight, volume delta 0.000000%**.

4. **Sewing / ShapeFix repair path.** A component that does not close from shared-topology
   construction alone is routed through a sewing + shape-fix repair pass before being
   declared an open shell. A component that still cannot close is written as an open shell
   and counted in `openShells` — **never wrapped as a fake solid**, which is the existing
   design invariant in `brep_build.py` and stays.

`--unify-angle` is the same quantity the existing `--merge-coplanar ANGLE_DEG` already
controls; unify the two rather than adding a parallel knob.

**Target Files / Scope (writable).**

- `src/mesh2step/result.py` *(new)* — RESULT payload construction and emission
- `src/mesh2step/split.py` *(new)* — component splitting into manifold bodies
- `src/mesh2step/sew.py` *(new)* — sewing / ShapeFix repair path
- `src/mesh2step/convert.py` — orchestration; `ConvertStats` gains the new counters
- `src/mesh2step/cli.py` — flags, `--quiet`, RESULT emission, exit codes
- `src/mesh2step/brep_build.py` — only as needed to expose per-component build

**Read-only (modifying any of these invalidates the run).** `tests/**` — including
`tests/test_parity.py` and every byte under `tests/data/` — `tools/**`, `refs/**`,
`pyproject.toml`, `webapp/**`, `README.md`.

**Open Bindings.**

- *Multi-solid STEP assembly shape.* stl2step writes N solids into one file; whether they
  land as a compound or as separate roots is not pinned by the harness. **Default: a
  `TopoDS_Compound` of the solids**, which is what `STEPControl_Reader.OneShape()` reads
  back and what the overlay check integrates.
- *Welding.* stl2step exposes `--weld <tol>` separately from mesh2step's `--tolerance`.
  **Default: leave `--tolerance` as the single dedup knob for M1**; `--weld` is not in the
  F2P set and must not be invented.
- *`vertices`.* The reference reports vertices **after** welding. **Default: emit
  `n_unique_verts`**, which is the same quantity under mesh2step's dedup.

## 2. HARNESS ENVIRONMENT & GROUND TRUTH

**Harness Interface.** There is no harness binary in this repo. The harness **is** the
ordered §3 command sequence and its exit codes; that sequence is the sole deterministic
oracle of task status.

**Fail-to-Pass (F2P).** `tests/test_parity.py -k verbatim` — **16 tests, all red at
baseline**, verified 2026-09-02: every one fails with `mesh2step emitted no RESULT line`.
They compare mesh2step's RESULT against golden fixtures captured from the reference binary,
and for the four fixtures with a golden `.step` they additionally require a boolean volume
overlay `V(A∩B)/V(A∪B) >= 1 - 1e-9`. That ratio is the literal "100% overlay" requirement.

**Pass-to-Pass (P2P).** `tests/` excluding `tests/test_parity.py` — **45 passed** at
baseline, none red. Any drop is a regression you caused.

**Known-red and NOT your problem.** The 16 `-k trueform` parity cases stay red through M1.
Do not chase them, do not skip them, do not mark them xfail.

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
   `/usr/bin/python3 -m pytest -q "tests/test_parity.py" -k verbatim`

Interpreter is pinned deliberately: this host has no `.venv`, the package is installed
`--user` in editable mode, and a different `python` on PATH will not import `mesh2step`
from `src/`. Slot 3 collects **16** tests; a run collecting any other number is a broken
binding, not a pass.

## 4. CONVERGENCE LOOP (FORMAL EXECUTION PROTOCOL)

Iterate until termination criteria hold, ceiling **6** iterations:

1. **EDIT:** apply scoped modifications to in-scope source files.
2. **EXECUTE:** run the §3 sequence in order.
3. **PARSE:** consume the structured payload — failing assertions, stack traces, ruff records.
4. **PATCH:** derive root cause from the parsed diagnostics and refine the edit.

Suggested order of attack, because it maximises green per iteration: RESULT contract and
exit codes first (turns `test_exit_code_matches_reference` and the small-fixture invariants),
then component splitting (`S09`, `Body11`), then the sewing path (`Body11` closure).

On ceiling without convergence: stop, do **not** report success, return the last diff plus
the unresolved failure set.

## 5. TERMINATION CRITERIA (BOOLEAN GATES)

Finalize IF AND ONLY IF all gates hold, each backed by captured stdout:

- [ ] `harness_exit_code == 0` for §3 slots 2 and 3
- [ ] `fail_to_pass_status == ALL_PASSED` — 16/16 in slot 3
- [ ] `pass_to_pass_regressions == 0` — slot 2 reports **45 passed**, no fewer
- [ ] `new_linter_diagnostics == 0` — the post-edit `(file, code)` multiset over the §1
      writable files introduces no code absent from the baseline and raises no count.
      Baseline for `src/mesh2step`: `brep_build.py::BLE001 1, brep_build.py::I001 1,
      brep_build.py::TRY003 1, cli.py::E501 4, convert.py::E501 1, convert.py::F401 1,
      cut.py::F401 1, cut.py::TRY003 4, cut.py::TRY004 1, dedup.py::E501 1,
      dedup.py::TRY003 1, io_mesh.py::TRY003 5, merge_coplanar.py::E501 2,
      repair.py::TRY003 2, step_export.py::TRY003 4` (**24 diagnostics**, full repo
      fingerprint in `.claude/loopspec/lint-baseline.json`). **Absolute zero is NOT the
      gate**; the pre-existing diagnostics are out of scope and fixing them is a scope
      violation.

## 6. GUARDRAILS & EXECUTION CONSTRAINTS

- **Zero-Assumption Rule:** completion is never declared without verifiable stdout and exit codes.
- **Context Preservation:** no raw log dumps; extract diagnostic diffs and failure traces only.
- **Blast Radius Limitation:** minimal diffs, strictly inside the §1 scope; no drive-by
  refactors, no dependency additions, no reformatting of untouched lines. `numpy`, `trimesh`
  and `cadquery-ocp` are already available — nothing else may be added.
- **Oracle Supremacy:** the harness verdict is final. A parity case you believe is wrong is
  still the specification; report the disagreement and stop, do not edit the test to agree.
- **Baseline Obligation:** before the first EDIT, run §3 once and record the baseline.
- **No fake solids.** The existing invariant holds: an open mesh comes back as a shell with
  boundary/non-manifold edge counts reported, never as a solid with an invented volume.
- **Long commands go under `watchjob`,** never `nohup`/`&`/`pgrep`:
  `~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- <command>`, status via
  `~/.claude/scripts/job status <name>`. The full parity suite takes ~50 s; `Body11`
  and `Body28` dominate.
