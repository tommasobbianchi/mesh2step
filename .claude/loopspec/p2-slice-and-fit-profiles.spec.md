# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

## 1. TARGET GOAL

- **Functional Objective:** Port route P's profile stage from
  `refs/stl2step/src/refit_profile.cpp` to Python:
  - `slice_profiles(mv, rs, lv, tols) -> list[Profile]` — `sliceProfiles`, refit_profile.cpp:999
  - `fit_profile(mv, tols, profile) -> int` — `fitProfile`, refit_profile.cpp:1093;
    returns `n_declined`, mutating the profile's loops in place.

  Together these must reproduce the reference's `DIAG_PROFILE` output for handle-lock
  **exactly**: per loop the header row (`slab`, `loop`, `outer`, `nSeg`, `nLine`, `nArc`,
  `nDecl`, `area`) and per segment the row (`i`, `kind`, `R`, `phi`, `decl`), in the
  reference's own order.

  This is a **translation**, not a reimplementation. Read the C++ and transcribe it,
  citing `refit_profile.cpp` line numbers in comments. Where the reference looks odd, it
  is still the specification. `refit_profile.cpp` is 1290 lines; the supporting helpers
  (`buildFrame`, `sliceTri`, `chainEdges`, `emitCircle`, `mergeSameCircle`, `stitchLoop`,
  `recomputePhi`, `analyticArea`, `circIntersect`, `unwrapSpan`, ...) are part of the port.

- **Target Files / Scope (writable):**
  - `src/mesh2step/refit/profile.py` — NEW. All production code.
  - `tests/test_profile.py` — NEW. The F2P test file (see §4 authoring exception).
  - `src/mesh2step/refit/__init__.py` — export the new public names ONLY.

  Everything else is **read-only**: `segment.py`, `lawband.py`, `build.py`, `prism.py`,
  `cli.py`, `convert.py`, every other test, and all of `refs/` (read-only truth — never edit).

- **Prerequisite already in the tree:** `src/mesh2step/refit/prism.py` provides
  `detect_prismatic(mv, rs, tols) -> PrismLevels` and the dataclasses `PrismTols`
  (`tau_surf`, `tau_lvl`, `tau_fit`, `tau_ax`) and `PrismLevels` (`axis`, `y`,
  `cap_region`, `ok`, `failed_cond`, plus the census counts). Use them; do not
  reimplement or modify them. `derive_prism_tols` in that module is your tolerance source.

- **Open Bindings:**
  - `ProfSeg` / `ProfLoop` / `Profile` field names are not fixed by anything existing.
    Mirror the C++ struct (`refit_prism.hpp:38-50`) in snake_case:
    `ProfSeg(is_arc, a, b, center, r, phi, ccw, declined_ambiguous)`,
    `ProfLoop(segs, outer, area)`, `Profile(slab, loops)`. Default assumed: dataclasses.
  - 2D points: use a plain `numpy` shape-(2,) float64 array in place of `gp_Pnt2d`.

## 2. HARNESS ENVIRONMENT & GROUND TRUTH

- **Harness Interface:** the ordered command sequence in §3 is the sole oracle.

- **Ground truth, measured from the reference binary and committed to the repo:**
  `tests/data/reference/handle-lock.profile.txt` — 39 lines, the verbatim `DIAG_PROFILE`
  output. **Parse that file in the test; do not retype its numbers into the source.**
  It contains three loops:

  | slab | loop | outer | nSeg | nLine | nArc | nDecl | area |
  |---:|---:|---:|---:|---:|---:|---:|---:|---|
  | 0 | 0 | 1 | 27 | 15 | 12 | 0 | 1855.303553 |
  | 0 | 1 | 0 | 1 | 0 | 1 | 0 | 103.868926 |
  | 1 | 0 | 1 | 8 | 4 | 4 | 0 | 424.977623 |

  Regenerate it with:
  ```
  STL2STEP_PRISM_DIAG=1 refs/stl2step/RUN.sh tests/data/corpus/handle-lock.stl \
    -o /tmp/ref_hl.step --smooth --unify-angle 5 --quiet 2>&1 | grep '^DIAG_PROFILE'
  ```
  `refs/stl2step/RUN.sh` is REQUIRED — it sets the FreeCAD-snap `LD_LIBRARY_PATH`. The raw
  binary at `refs/stl2step/build/stl2step` exits 127.

  **handle-lock is the ONLY prismatic fixture in the corpus** (`detect_prismatic` returns
  `ok=True` for it and `ok=False` for cube, S09 and nonprismatic-control). It is therefore
  the whole F2P set. Body11/Body28 are excluded: 30-60 min each and neither is prismatic.

- **Fail-to-Pass (F2P):** `tests/test_profile.py` — you author it (§4 exception). It must
  drive the same path `tests/test_prism.py` already uses to obtain a `MeshView` +
  `RegionSet` + `PrismLevels` for handle-lock (reuse it; do not invent a second path),
  call `slice_profiles` then `fit_profile`, parse the golden file, and assert:
  - loop count and per-loop `outer` / `nSeg` / `nLine` / `nArc` / `nDecl` — **exact integers**
  - per-loop `area` and per-segment `R`, `phi` — `pytest.approx(rel=1e-6)`
    (the reference prints 6 decimals; exact equality is NOT available and demanding it is a
    spec violation)
  - per-segment `kind` (line/arc) and `decl` — **exact**

- **Pass-to-Pass (P2P):** `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`.
  Baseline BEFORE your first edit is **73 passed, 5 failed** (78 collected, 8 deselected).
  The 5 failures are pre-existing in `tests/test_parity.py` (handle-lock.trueform x3,
  nonprismatic-control.trueform x2). They are NOT yours to fix and fixing them is out of
  scope — this milestone does not wire route P into the engine, so they stay red.
  **Measure the baseline yourself before editing; do not trust this number.**

- **Test Integrity Constraint:** modifying, mocking, skipping, xfailing or loosening any
  existing test, fixture or golden datum is prohibited and invalidates the run. In
  particular `tests/data/reference/handle-lock.profile.txt` is the oracle — never edit it.
  You may create `tests/test_profile.py` and nothing else under `tests/`.

## 3. VERIFICATION COMMANDS

1. Lint: `python3 -m ruff check src/mesh2step/refit/profile.py src/mesh2step/refit/__init__.py tests/test_profile.py`
2. F2P: `python3 -m pytest -q tests/test_profile.py`
3. P2P: `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`

Run them in that order. `python3`, never `python` (no venv, no `python` on PATH).
P2P takes ~6 min — redirect it to a file and read the file.

## 4. CONVERGENCE LOOP

Iterate to a ceiling of **6** iterations: EDIT (scope of §1 only) -> EXECUTE (§3 in order)
-> PARSE (failing assertions, linter records) -> PATCH (cause derived from diagnostics).

**Author the F2P test FIRST and confirm it fails** against absent/stub code before
implementing. A test that has never been red proves nothing.

On reaching the ceiling without convergence: STOP. Do not report success. Return the diff
and the unresolved failures, with the numbers.

## 5. TERMINATION CRITERIA (BOOLEAN GATES)

Finalize IF AND ONLY IF, each backed by captured stdout:
- [ ] `fail_to_pass_status == ALL_PASSED` — every loop and every segment row of the golden.
- [ ] `pass_to_pass_regressions == 0` — still >=73 passed, no baseline-passing test now failing.
- [ ] `new_linter_diagnostics == 0` — the §3.1 files are NEW, baseline empty, ruff must be
      clean on them. Do NOT lint or fix the rest of the repo (pre-existing, not yours).
- [ ] The F2P test was demonstrated RED before the implementation existed.

## 6. GUARDRAILS

- **Zero-Assumption Rule:** never declare completion without stdout and exit codes.
- **Translate, do not paraphrase.** This port's history: where it transcribed the C++ it
  matched to six decimals first try; where it paraphrased what a function "seemed to do"
  (`lawCalibrate`) it was wrong and cost two sessions.
- **Oracle Supremacy:** the reference's numbers are final. If your output disagrees, YOUR
  CODE is wrong — do not adjust expected values to match what you produced. If you become
  convinced a golden datum is itself wrong, STOP and report it; do not edit it.
- **Numerics:** this codebase is bit-sensitive. Transcribe tolerance expressions, never
  "simplify" them. Note a measured trap: `np.dot` on a 3-vector is OpenBLAS `ddot` (an FMA
  chain) and does NOT equal `a*b+c*d+e*f` nor `m @ w`; `np.arctan2` differs from
  `math.atan2` by 1 ulp on ~2.4% of inputs. `lawband.py` has `_row_dots`/`_ATAN2` helpers
  that reproduce the scalar path bit-exactly — reuse them rather than rolling your own.
- **Blast Radius:** minimal diffs, strictly inside §1. No refactors, no new dependencies,
  no reformatting of untouched lines.
- **Long commands:** redirect to a file under the scratchpad and read the file. Do NOT rely
  on `watchjob`/`job log` — child stdout is discarded on this machine.
- **No git operations.** No commit, push, stash, checkout or branch. Leave the tree dirty.

## 7. REPORT BACK

The diff, the three command outcomes with exit codes, proof the F2P test was red first, the
F2P assertion table (expected vs actual per loop and per segment), and the P2P pass/fail
counts against the 73/5 baseline. Name anything you could not make match, with the numbers.
