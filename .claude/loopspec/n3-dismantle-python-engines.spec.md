# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

## 1. TARGET GOAL

- **Functional Objective:** remove the Python conversion engines. The native C++
  engine (`src/mesh2step/native.py` → `stl2step`) is now the only converter; it is
  20-35x faster on identical input and its output is the reference the Python port
  was written to match. This is a **deletion** task: the goal is less code that still
  does everything the deployed service does.

  **Delete:**
  - `src/mesh2step/refit/` — the entire TrueForm port (~10,200 lines).
  - `convert_trueform` and `convert_file` from `src/mesh2step/convert.py`, plus every
    helper that becomes unreachable once they are gone. If the module ends up holding
    only dead code, delete the module and move anything still imported elsewhere to
    where it is used.
  - The test files that exist solely to exercise the deleted engines:
    `tests/test_parity.py`, `test_dxf.py`, `test_prism.py`, `test_profile.py`,
    `test_seamed360.py`, `test_refit_curves.py`, `test_prism_build.py`,
    `test_primitives.py`.
    They compare the Python port against the reference; with the port gone they would
    be comparing the reference to itself.

  **Keep, and do not touch beyond what re-pointing requires:**
  - `src/mesh2step/native.py`, `io_mesh.py`, `cut.py`, `repair.py`, `dedup.py`,
    `step_export.py`, `merge_coplanar.py`, `brep_build.py`, `result.py` and anything
    else the surviving paths import. **Verify by import, not by name** — grep before
    deleting anything.
  - `tests/test_cut.py`, `test_repair.py`, `test_webapp_api.py`, `test_native.py`,
    `test_real_scan.py` — they test surviving behaviour. Any of them that imports a
    deleted engine must be re-pointed at the native path, NOT deleted, and its
    assertions must keep their meaning.
  - `webapp/server.py`'s `/api/edit` and `/api/segment` — untouched.

  **Re-point:**
  - `src/mesh2step/cli.py` must convert through `native.py`. It is the interface the
    parity harness and `tools/` use; keep its flags (`--engine`, `--unify-angle`,
    `-o`, `--quiet`, `--schema`) behaving the same from the outside, including the
    `RESULT {json}` last line and the exit codes (0 ok, 2 ok-with-warnings, 1 failed).
  - `webapp/server.py`: delete the Python fallback branch and the `backend` split.
    With no Python engine there is no fallback, so `stats["backend"]` is always
    `"native"` — keep the key (the frontend and tests read it) but stop branching.
  - **The binary is now required.** When it is absent, fail LOUDLY and EARLY with a
    clear message naming `MESH2STEP_NATIVE` — at import or app startup, not per
    request, and never with a silent degradation.
  - `src/mesh2step/__init__.py` — drop exports of deleted names.

- **Target Files / Scope (writable):** everything named above, plus `README.md` and
  `webapp/README.md` where they document the removed engines. **Never touch anything
  under `refs/`** — read-only reference truth, and gitignored, so git gives you no
  protection there.

- **Open Bindings:** if a surviving module imports something from `refit/` that is not
  engine code (a pure geometry helper), move that helper rather than deleting it, and
  say which in your report.

## 2. HARNESS ENVIRONMENT & GROUND TRUTH

- **Harness Interface:** the §3 sequence is the sole oracle.

- **Fail-to-Pass (F2P):** there is no new behaviour, so F2P is the surviving suite
  passing with the engines gone, plus these behavioural checks you must add to
  `tests/test_native.py`:
  1. `python3 -m mesh2step.cli tests/data/corpus/cube.stl -o <tmp> --engine trueform
     --quiet` exits 0 and its last stdout line parses as `RESULT {json}` with
     `solids == 1`.
  2. The same for `--engine faceted` (or whatever the CLI spells the verbatim mode),
     producing a STEP whose first bytes are `ISO-10303-21`.
  3. `import mesh2step` does not import `mesh2step.refit` (assert the module is not
     importable), proving the deletion is real and not merely unreferenced.

- **Pass-to-Pass (P2P):** `python3 -m pytest -q tests/`. Baseline before your first
  edit is **94 passed, 1 failed** (`test_dxf_byte_identical`, a known 3-ulp
  divergence in the DXF writer of the engine you are DELETING — that failure should
  disappear with the file, which is expected and correct, not a regression).
  After the deletion the count will be lower because whole files are gone. That is the
  intent. What must hold: **no surviving test fails**, and the count of surviving
  tests matches the files you kept.

- **Test Integrity Constraint:** you may DELETE the eight files listed in §1 and
  re-point the five listed as surviving. You may not weaken, skip, xfail or mock a
  test you keep. Deleting a test to make a failure go away — other than the eight
  named — invalidates the run.

## 3. VERIFICATION COMMANDS

1. Lint: `python3 -m ruff check src/mesh2step/ webapp/server.py tests/`
2. Import sanity: `python3 -c "import mesh2step, mesh2step.native; print('ok')"`
3. CLI: `python3 -m mesh2step.cli tests/data/corpus/handle-lock.stl -o /tmp/hl.step --engine trueform --quiet`
4. Suite: `python3 -m pytest -q tests/`
5. Service smoke: `python3 -c` starting `webapp.server:app` under `TestClient` and
   converting the cube on both engines, asserting `ok is True` and volume ≈ 1000.

Run in that order. `python3`, never `python`. Slot 4 is now fast (the slow parity
tests are the ones being deleted) but still redirect long output to a file under
`/tmp/claude-1000/-home-tommaso-projects-mesh2step/55ed36d6-4f09-4e83-a602-2227174fbd8a/scratchpad/`.

**Lint baseline** on the files you keep: `webapp/server.py` + `tests/test_webapp_api.py`
carry `{I001:1, E501:8, B008:3, B904:2, B905:1}` plus `{I001:2, F401:1}`; `src/` has
pre-existing diagnostics of its own (`convert.py:181` E501 among them). The gate is
zero NEW codes on surviving files as a `(file, code)` multiset. Deleting files that
carried diagnostics is a decrease, which is fine and needs no comment.

## 4. CONVERGENCE LOOP

Ceiling **6** iterations: EDIT → EXECUTE §3 in order → PARSE → PATCH.
**Delete in dependency order and re-run slot 2 after each deletion** — an ImportError
found immediately is one minute; found after six more deletions it is an afternoon.
On the ceiling without convergence: STOP, report the diff and the failures.

## 5. TERMINATION CRITERIA (BOOLEAN GATES)

- [ ] `mesh2step.refit` is gone from disk and not importable.
- [ ] No surviving test fails; every kept test still asserts what it asserted before.
- [ ] The CLI converts both engines and emits its `RESULT` line and exit codes.
- [ ] The web app converts on both engines under `TestClient`, volume ≈ 1000 on a cube.
- [ ] Absent binary fails loudly at startup with a message naming `MESH2STEP_NATIVE`
      — demonstrate it (`MESH2STEP_NATIVE=/nonexistent`) and show the message.
- [ ] `new_linter_diagnostics == 0` on surviving files.
- [ ] Report the line count deleted.

## 6. GUARDRAILS

- **Zero-Assumption Rule:** no completion claim without stdout and exit codes.
- **Never edit anything under `refs/`.**
- **Grep before you delete.** Every removal is justified by "nothing imports it",
  demonstrated, not assumed. A name being *engine-sounding* is not evidence.
- **No behaviour changes smuggled into a deletion.** If something must change to keep
  a surviving test meaningful, say so explicitly in the report.
- **No git operations.** No commit, push, stash, checkout, branch. Leave the tree dirty.

## 7. REPORT BACK

`git diff --stat` (it will be large and mostly deletions), the five command outcomes
with exit codes, the surviving test count against what you kept, the loud-failure
demonstration, total lines deleted, and anything you kept that the spec expected you to
delete — with the import that justified keeping it.
