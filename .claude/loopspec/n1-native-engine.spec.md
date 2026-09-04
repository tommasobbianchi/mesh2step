# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

## 1. TARGET GOAL

- **Functional Objective:** route the web app's conversions through the native C++
  engine (`stl2step`) instead of the Python engines, because it is **20x faster on the
  same input and produces byte-identical output by definition** (it is the reference the
  parity tests assert against). Measured on this host: Body11, 15,300 triangles —
  Python 1681 s, native 84.5 s; handle-lock, 908 triangles — Python 86.0 s, native 1.97 s.

  Two pieces of work:

  **(a) `src/mesh2step/native.py` — NEW.** A thin, well-tested wrapper around the binary.

  ```python
  def native_binary() -> Path | None      # locate it; None when unavailable
  def native_available() -> bool
  def convert_native(input_path, output_path, *, engine="verbatim", schema="ap214",
                     unify_angle=None, timeout=None) -> dict
  ```

  - **Locating it**, in this order: `$MESH2STEP_NATIVE` if set (a path to the launcher or
    the binary); else `refs/stl2step/RUN.sh` relative to the repo root; else `stl2step` on
    `PATH`. Return None rather than raising when nothing is found — the caller decides.
  - **You MUST invoke the launcher `RUN.sh`, not `build/stl2step` directly.** The binary
    links OCCT 7.8 from the FreeCAD snap and the launcher is what sets
    `LD_LIBRARY_PATH`; the raw binary exits 127. Read `refs/stl2step/RUN.sh` — it is 6 lines.
  - **The contract with the binary:** last stdout line is `RESULT {json}`; exit code 0 ok,
    2 ok-with-warnings, 1 failed. Parse the RESULT json and return it as a dict, with the
    exit code under key `exit_code`. Treat exit 2 as SUCCESS — it means warnings, and the
    reference uses it for the ordinary "analytic rebuild reverted" case.
  - `--engine verbatim|trueform`, `--schema`, `--unify-angle`, `--quiet`. Use
    `subprocess.run` with a timeout; on timeout raise a clear error naming the seconds.
  - Never pass user text to a shell. Argument list only, `shell=False`.

  **(b) `webapp/server.py` — route `/api/convert` through it.** Both engines:
  `engine=faceted` → `--engine verbatim`; `engine=trueform` → `--engine trueform`.

  - **Non-STL input must be transcoded first.** The binary takes STL only; the endpoint
    accepts `.stl/.obj/.3mf/.ply`. Load with the existing `mesh2step.io_mesh.load_mesh`
    and write a temporary binary STL next to the upload, then convert that. Do not add a
    new mesh-loading path.
  - **Keep the response envelope byte-compatible with today's**: `{"ok", "stats",
    "download_token"}`, with `stats["engine"]` present, plus `input_path`/`output_path`
    rewritten to the user's filename exactly as now. The RESULT json's field names are the
    reference's; map them onto the keys the client already renders — the existing
    `_trueform_stats` mapping is your model, and `src/mesh2step/result.py` documents the
    field set. `is_solid` = `solids > 0 and open_shells == 0`.
  - **Fall back to the Python engine when the binary is unavailable**, so a checkout
    without `refs/` still works. Put the fallback behind `native_available()` and record
    which path ran in `stats["backend"] = "native" | "python"`. This is not optional: the
    binary lives in a gitignored directory.
  - `repair` and `cuts` have no native equivalent. Under the native path, keep today's
    behaviour: they are already refused with 400 for trueform; for faceted, if `repair`
    or `cuts` is requested, use the PYTHON path for that request and set
    `stats["backend"] = "python"`. Do not silently drop a knob the user set.
  - **Do not touch `/api/edit` or `/api/segment`.** They are trimesh work with no native
    counterpart and are not in scope.

- **Target Files / Scope (writable):**
  - `src/mesh2step/native.py` (new)
  - `webapp/server.py`
  - `tests/test_native.py` (new), `tests/test_webapp_api.py` (append only)

  Everything else is read-only: all other `src/mesh2step/**` (do NOT delete or modify the
  Python engines in this milestone — retiring them is a separate, later step that depends
  on this one being live and proven), all other tests, and **everything under `refs/`,
  which is read-only reference truth and must never be edited**.

- **Open Bindings:** default timeout 900 s. `stats["backend"]` is a new key; adding it is
  intended.

## 2. HARNESS ENVIRONMENT & GROUND TRUTH

- **Harness Interface:** the §3 command sequence is the sole oracle.

- **Ground truth for the wrapper**, measured on this host 2026-09-04:

  ```
  refs/stl2step/RUN.sh tests/data/corpus/cube.stl -o /tmp/c.step --engine verbatim --quiet
  ```
  exits 0 and its last stdout line is `RESULT {...}` with `"solids": 1`. The same file with
  `--engine trueform` also succeeds. `tests/data/corpus/nonprismatic-control.stl` with
  `--engine trueform` exits **2** with the warning
  `smooth: analytic rebuild reverted on one component -- kept faceted` — use it as the
  exit-2-is-success case.

- **Fail-to-Pass (F2P):** `tests/test_native.py` and new cases appended to
  `tests/test_webapp_api.py`. At minimum:
  1. `native_available()` is True on this host, and `native_binary()` points at an existing file.
  2. `convert_native` on `cube.stl`, engine verbatim: returns a dict with `exit_code == 0`,
     `solids == 1`, and writes a STEP file starting with `ISO-10303-21`.
  3. `convert_native` on `nonprismatic-control.stl`, engine trueform: `exit_code == 2`,
     treated as success, warnings non-empty.
  4. Through the API: `engine=faceted` on the cube returns 200, `is_solid` True,
     volume ≈ 1000.0, `stats["backend"] == "native"`.
  5. Through the API: `engine=trueform` on the cube — same, `stats["engine"] == "trueform"`.
  6. Through the API with `repair=weld`: still 200 and `stats["backend"] == "python"`.
  7. A non-STL upload (build a small `.obj` or `.ply` with trimesh in the fixture)
     converts successfully through the native path.

  **Every new test must assert something that fails without your change.** A test that
  passes against the current server proves nothing — the last delegation on this repo
  shipped exactly that mistake: a download-roundtrip case that passed because an ignored
  field fell through to the old path. Check each one by stashing your source change.

- **Pass-to-Pass (P2P):** `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`.
  Baseline **86 passed, 1 failed**; the failure is `test_dxf_byte_identical`, a known
  3-ulp divergence that is NOT yours. No test passing at baseline may fail after.

- **Test Integrity Constraint:** modifying, mocking, skipping, xfailing or loosening any
  existing test or fixture is prohibited and invalidates the run.

## 3. VERIFICATION COMMANDS

1. Lint: `python3 -m ruff check src/mesh2step/native.py webapp/server.py tests/test_native.py tests/test_webapp_api.py`
2. F2P: `python3 -m pytest -q tests/test_native.py tests/test_webapp_api.py`
3. P2P: `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`

In that order. `python3`, never `python`. Slot 3 takes ~12 min: redirect it to a file under
`/tmp/claude-1000/-home-tommaso-projects-mesh2step/55ed36d6-4f09-4e83-a602-2227174fbd8a/scratchpad/`
and read the file rather than streaming it into your context.

**Lint baseline:** `webapp/server.py` + `tests/test_webapp_api.py` carry **18 pre-existing
diagnostics** (`{I001:3, F401:1, E501:8, B008:3, B904:2, B905:1}`) — they are NOT yours and
fixing them is a scope violation. The gate is zero NEW codes and no count increase, as a
`(file, code)` multiset. The two new files must be clean.

## 4. CONVERGENCE LOOP

Ceiling **6** iterations: EDIT (§1 scope) → EXECUTE (§3 in order) → PARSE the failures →
PATCH from the diagnostics. Author the F2P tests FIRST and confirm they are RED.
On the ceiling without convergence: STOP, report the diff and the unresolved failures.

## 5. TERMINATION CRITERIA (BOOLEAN GATES)

- [ ] `fail_to_pass_status == ALL_PASSED` — all seven cases.
- [ ] `pass_to_pass_regressions == 0` — still ≥86 passed, `test_dxf_byte_identical` the only failure.
- [ ] `new_linter_diagnostics == 0` against the baseline multiset above.
- [ ] Each F2P case demonstrated RED before the change.
- [ ] **A measured speed comparison, in the report**: handle-lock through the API on the
      native path vs the Python path, wall-clock, both numbers, one command each.

## 6. GUARDRAILS

- **Zero-Assumption Rule:** no completion claim without stdout and exit codes.
- **Never edit anything under `refs/`.** It is gitignored, so `git status` gives you NO
  protection there — an edit is invisible and unrecoverable.
- **Do not delete or modify the Python engines** (`convert_file`, `convert_trueform`, or
  anything in `src/mesh2step/refit/`). They remain the fallback and the parity subject.
- **Blast radius:** minimal diffs inside §1. No new dependency, no refactor of the faceted
  path beyond the routing, no reformatting of untouched lines.
- **Security:** the input filename comes from an HTTP upload. Argument lists only, never a
  shell string; never interpolate the filename into a command.
- **No git operations.** No commit, push, stash, checkout or branch. Leave the tree dirty.

## 7. REPORT BACK

`git diff --stat` then the `native.py` body and the server hunk; the three command outcomes
with exit codes; proof each F2P case was red first; the native-vs-Python wall-clock numbers
from gate 5; and the P2P count against the 86/1 baseline. Name anything you could not make
work, with numbers.
