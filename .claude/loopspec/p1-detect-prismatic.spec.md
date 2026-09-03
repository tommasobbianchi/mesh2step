# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

## 1. TARGET GOAL

- **Functional Objective:** Port `detectPrismatic` from
  `refs/stl2step/src/refit_prism.cpp:157-377` to Python as
  `detect_prismatic(mv, rs, tols) -> PrismLevels`, reproducing the reference's
  `DIAG_PRISM` verdict **exactly** on every corpus fixture: the `ok` flag, the
  `failedCond` code (which of the six conditions rejected, 0 when accepted), the five
  counts `nCyl/nPlane/nCap/nLat/nOblique`, the two self-computed tolerances
  `tauAx/tauLvl`, and — when accepted — the ordered cap levels reported by
  `DIAG_PRISMLVL` (`y` and `capRegion` per level).

  This is a **translation**, not a reimplementation. Read the C++ and transcribe it.
  The reference is the specification; where it looks odd, it is still the specification.
  Do not "improve" a condition, reorder the tests, or substitute a tolerance.
  `failedCond` is emitted at the FIRST failing condition and the function returns
  immediately — the order of the six tests is therefore observable behaviour, not an
  implementation detail.

- **Target Files / Scope (writable):**
  - `src/mesh2step/refit/prism.py` — NEW. All production code goes here.
  - `tests/test_prism.py` — NEW. The F2P test file (see §4 authoring exception).
  - `src/mesh2step/refit/__init__.py` — export `detect_prismatic` and `PrismLevels` ONLY.

  Everything else in the repo is **read-only**, in particular `src/mesh2step/refit/segment.py`,
  `lawband.py`, `build.py`, `cli.py`, `convert.py`, all other tests, and everything under
  `refs/` (the reference is read-only truth — never edit it).

- **Open Bindings:**
  - `PrismLevels` field names are not fixed by anything existing; use the reference's
    (`ok`, `failed_cond`, `axis`, `levels`, `tau_ax`, `tau_lvl`, plus the five counts) and
    keep them snake_case. Default assumed: a `@dataclass` mirroring the C++ struct.
  - The reference emits one `DIAG_PRISM` line per component. `detect_prismatic` is called
    per component and returns one result; the per-component loop is NOT in scope here.

## 2. HARNESS ENVIRONMENT & GROUND TRUTH

- **Harness Interface:** the ordered command sequence in §3 is the sole oracle. There is
  no harness binary.

- **Ground truth, measured from the reference binary on 2026-09-04** (this is the data to
  assert against; it is already captured at
  `/tmp/claude-1000/-home-tommaso-projects-mesh2step/55ed36d6-4f09-4e83-a602-2227174fbd8a/scratchpad/ref_prism.txt`,
  and you can regenerate it yourself — see below):

  | fixture | comp | ok | failedCond | nCyl | nPlane | nCap | nLat | nOblique | tauAx | tauLvl |
  |---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
  | cube | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 0 | 1.000e-06 | 5.000e-05 |
  | S09 (1st) | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 0 | 1.000e-06 | 7.297e-05 |
  | S09 (2nd) | 0 | 0 | 1 | 0 | 22 | 0 | 0 | 0 | 1.000e-06 | 7.297e-05 |
  | nonprismatic-control | 0 | 0 | **3** | 2 | 2 | 1 | 0 | **1** | 1.111e-05 | 5.000e-05 |
  | handle-lock | 0 | **1** | 0 | 15 | 13 | 3 | 10 | 0 | 5.536e-05 | 7.820e-05 |

  handle-lock cap levels (`DIAG_PRISMLVL`), in order:

  | i | y | capRegion |
  |---:|---|---:|
  | 0 | -288.825734 | 0 |
  | 1 | -280.450731 | 1 |
  | 2 | -277.625728 | 2 |

  Regenerate any of it with:
  ```
  STL2STEP_PRISM_DIAG=1 refs/stl2step/RUN.sh tests/data/corpus/<F>.stl \
    -o /tmp/ref_<F>.step --smooth --unify-angle 5 --quiet 2>&1 | grep DIAG_PRISM
  ```
  `refs/stl2step/RUN.sh` is REQUIRED — it sets the FreeCAD-snap `LD_LIBRARY_PATH`. The raw
  binary at `refs/stl2step/build/stl2step` exits 127.

  Body11 and Body28 are deliberately excluded: they take 30-60 min each and neither is
  prismatic. Do not add them to the F2P set.

- **Fail-to-Pass (F2P):** `tests/test_prism.py` — you author it (§4 exception). It must
  drive our own segmentation to obtain a `RegionSet` per component (see
  `tests/test_parity.py` and `src/mesh2step/convert.py` for how a `MeshView` + `RegionSet`
  is produced for a fixture; reuse that path, do not invent a second one), call
  `detect_prismatic`, and assert every column of the table above. `tauAx`/`tauLvl` and the
  level `y` values compare with `pytest.approx(rel=1e-3)` — the reference prints them to
  4 and 6 significant figures respectively, so exact equality is NOT available and
  demanding it is a spec violation. Every integer field (`ok`, `failedCond`, the five
  counts, `capRegion`) must match **exactly**.

- **Pass-to-Pass (P2P):** `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`.
  Baseline BEFORE your first edit is **19 passed, 5 failed** in `tests/test_parity.py`
  (handle-lock.trueform ×3, nonprismatic-control.trueform ×2). Those five are
  pre-existing, they are NOT yours to fix, and fixing them is out of scope. No test that
  passes at baseline may fail afterwards.

- **Test Integrity Constraint:** modifying, mocking, skipping, xfailing or loosening any
  existing test, fixture or golden datum is prohibited and invalidates the run. You may
  create `tests/test_prism.py` and nothing else under `tests/`.

## 3. VERIFICATION COMMANDS

1. Lint: `python3 -m ruff check src/mesh2step/refit/prism.py src/mesh2step/refit/__init__.py tests/test_prism.py`
2. F2P: `python3 -m pytest -q tests/test_prism.py`
3. P2P: `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`

Run them in that order. `python3`, never `python` (there is no venv and no `python` on PATH).

## 4. CONVERGENCE LOOP

Iterate to a ceiling of **6** iterations:
1. **EDIT** — scoped changes to the §1 writable files only.
2. **EXECUTE** — the §3 sequence, in order.
3. **PARSE** — read failing assertions and linter records.
4. **PATCH** — derive the cause from the diagnostics and refine.

**Author the F2P test FIRST and confirm it fails** against absent/stub code before
implementing. A test that has never been red proves nothing.

On reaching the ceiling without convergence: STOP. Do not report success. Return the diff
and the unresolved failures.

## 5. TERMINATION CRITERIA (BOOLEAN GATES)

Finalize IF AND ONLY IF, each backed by captured stdout:
- [ ] `fail_to_pass_status == ALL_PASSED` — every row and column of the §2 tables.
- [ ] `pass_to_pass_regressions == 0` — still ≥19 passed, and no baseline-passing test now failing.
- [ ] `new_linter_diagnostics == 0` — the §3.1 files are all NEW or nearly so; the baseline is
      empty, so ruff must be clean on them. Do not lint or fix the rest of the repo (it has
      pre-existing diagnostics that are not yours).
- [ ] The F2P test was demonstrated RED before the implementation existed.

## 6. GUARDRAILS

- **Zero-Assumption Rule:** never declare completion without stdout and exit codes.
- **Translate, do not paraphrase.** This port's own history: where it transcribed the C++ it
  matched to six decimals first try; where it paraphrased what a function "seemed to do"
  (`lawCalibrate`) it was wrong and cost two sessions. Cite `refit_prism.cpp` line numbers
  in comments for each of the six conditions.
- **Blast Radius:** minimal diffs, strictly inside §1. No refactors, no new dependencies, no
  reformatting of untouched lines, no changes to `segment.py`.
- **Oracle Supremacy:** the reference's numbers are final. If your output disagrees, YOUR
  CODE is wrong — do not adjust the expected values to match what you produced. If you
  become convinced a golden datum is itself wrong, stop and report it; do not edit it.
- **Numerics:** this codebase is bit-sensitive. Do not "simplify" a tolerance expression;
  transcribe it. `tauSurf = max(5e-5, 4*weldTol, 1e-6*diag)` and
  `tauAx = max(1e-6, 2*tauSurf/hMin)` are load-bearing.
- **Long commands:** redirect to a file under the scratchpad and read the file. Do NOT rely on
  `watchjob`/`job log` — child stdout is discarded on this machine. The P2P run takes ~5 min.
- **No git operations.** No commit, no push, no stash, no checkout, no branch. Leave the
  working tree dirty for review.

## 7. REPORT BACK

The diff, the three command outcomes with exit codes, proof the F2P test was red first, the
F2P assertion table (expected vs actual per fixture), and the P2P pass/fail counts against
the 19/5 baseline. Name anything you could not make match, with the numbers.
