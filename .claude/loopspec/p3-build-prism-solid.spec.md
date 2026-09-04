# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

## 1. TARGET GOAL

- **Functional Objective:** Port route P's construction stage from
  `refs/stl2step/src/refit_prism_build.cpp` (1188 lines) and wire route P into the engine:
  - `build_prism_solid(profiles, lv, tols) -> shape` — `buildPrismSolid` (refit_prism.hpp:59).
    Extrude each slab's profile between its cap levels, fuse the axially disjoint prisms,
    then run the reference's post-build passes: `usd-try`, `plane-adj`, `unify`, and the
    two-condition volume gate.
  - **Engine wiring:** in the trueform/smooth path, after segmentation, call
    `detect_prismatic`. When it returns `ok=True`, take route P (slice -> fit -> build) and
    report route P's census. When `ok=False`, behaviour must be **byte-identical to today**.

  This is a **translation**, not a reimplementation. Transcribe the C++ and cite
  `refit_prism_build.cpp` line numbers in comments. Where the reference looks odd, it is
  still the specification.

- **Target Files / Scope (writable):**
  - `src/mesh2step/refit/prism_build.py` — NEW. All construction code.
  - `tests/test_prism_build.py` — NEW. The F2P test file (see §4 authoring exception).
  - `src/mesh2step/refit/__init__.py` — exports ONLY.
  - `src/mesh2step/convert.py` — the route P branch ONLY. This is a **surgical** change:
    one branch on `detect_prismatic(...).ok`. Do not restructure the function, do not
    touch the route G path, do not reformat untouched lines.

  Everything else is **read-only**: `segment.py`, `lawband.py`, `build.py`, `prism.py`,
  `profile.py`, `cli.py`, every other test, and all of `refs/`.

- **Prerequisites already in the tree:** `prism.py` (`detect_prismatic`, `PrismTols`,
  `PrismLevels`, `derive_prism_tols`) and `profile.py` (`slice_profiles`, `fit_profile`,
  `Profile`, `ProfLoop`, `ProfSeg`). Use them; do not modify or reimplement them.

- **Open Bindings:**
  - OCP/OCCT is the geometry kernel (as in `build.py`). Use `BRepPrimAPI_MakePrism` /
    `BRepBuilderAPI_MakeFace` on the fitted 2D loops, mirroring the reference's OCCT calls.
    Default assumed: the same OCCT classes the C++ names, called through OCP.

## 2. HARNESS ENVIRONMENT & GROUND TRUTH

- **Harness Interface:** the ordered command sequence in §3 is the sole oracle.

- **Ground truth A — the build trace**, committed at
  `tests/data/reference/handle-lock.prismbuild.txt` (9 lines, verbatim `DIAG_PRISMBUILD`).
  **Parse it in the test; do not retype its numbers into the source.** It pins the whole
  construction: per-slab `faces`/`vol`/`valid`, the fuse face count, the `usd-try` face
  transition `P=23->23 C=17->15`, `plane-adj`, `unify` (`G1/G2/G4`, volume before/after),
  the volume gate (`D_signed`, `D_abs`, `V_ref`, `budget`, `envelope`, `cond1`, `cond2`),
  and the final `comp=0 slabs=2 faces=40 planes=23 cyls=17 vol=15868.832006
  watertight=1 valid=1 reverted=0`.

- **Ground truth B — end-to-end parity.** This milestone is what makes handle-lock pass.
  `tests/data/reference/handle-lock.trueform.json` currently fails on 9 fields; after this
  change every one must match exactly:

  | field | reference | ours today |
  |---|---:|---:|
  | facesBeforeUnify | 40 | 908 |
  | facesAfterUnify | 35 | 194 |
  | facesAfterSmooth | 35 | 194 |
  | smoothPlanes | 23 | 13 |
  | smoothCylinders | 17 | 15 |
  | smoothBuiltPlanes | 23 | 0 |
  | smoothBuiltCylinders | 15 | 0 |
  | smoothBuiltComponents | 1 | 0 |
  | smoothRevertedComponents | 0 | 1 |

  and the overlay volume must move 16038.862197 -> 15868.831779.

  **Note carefully:** our segmentation census (13 planes / 15 cylinders) already equals the
  reference's own (`DIAG_PRISM nPlane=13 nCyl=15`). The 23/17 are route P's OUTPUT, not
  segmentation's. Do NOT "fix" segmentation to reach 23/17 — that would be wrong and is
  out of scope. The numbers change because a different route reports them.

  Regenerate either oracle with:
  ```
  STL2STEP_PRISM_DIAG=1 refs/stl2step/RUN.sh tests/data/corpus/handle-lock.stl \
    -o /tmp/ref_hl.step --smooth --unify-angle 5 --quiet 2>&1 | grep '^DIAG_PRISMBUILD'
  ```
  `refs/stl2step/RUN.sh` is REQUIRED (FreeCAD-snap `LD_LIBRARY_PATH`); the raw binary at
  `refs/stl2step/build/stl2step` exits 127.

- **Fail-to-Pass (F2P):**
  1. `tests/test_prism_build.py` — you author it. Asserts every field of the
     `DIAG_PRISMBUILD` golden. Integers (`faces`, `planes`, `cyls`, `valid`, `watertight`,
     `reverted`, `G1`, `G2`, `G4`, `cond1`, `cond2`, `nAdj`, `nExact`) **exact**; volumes
     and tolerances `pytest.approx(rel=1e-6)`.
  2. `tests/test_parity.py -k "handle-lock and trueform"` — **3 currently-failing tests
     that must turn green.** This file is READ-ONLY; you make it pass by fixing the code.

- **Pass-to-Pass (P2P):** `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`.
  Baseline BEFORE your first edit: **5 failed** (handle-lock.trueform x3,
  nonprismatic-control.trueform x2). Afterwards: the 3 handle-lock failures must be gone
  and the 2 nonprismatic-control ones must REMAIN (they are a different defect, out of
  scope — `detect_prismatic` returns `ok=False, failedCond=3` for that fixture, so route P
  must not touch it). **Measure the baseline yourself; do not trust these numbers.**
  Every currently-passing test must still pass — cube and S09 are non-prismatic and their
  output must not move by a single field.

- **Test Integrity Constraint:** modifying, mocking, skipping, xfailing or loosening any
  existing test, fixture or golden datum is prohibited and invalidates the run.
  `tests/test_parity.py` and everything under `tests/data/reference/` are ORACLES — never
  edit them. You may create `tests/test_prism_build.py` and nothing else under `tests/`.

## 3. VERIFICATION COMMANDS

1. Lint: `python3 -m ruff check src/mesh2step/refit/prism_build.py src/mesh2step/refit/__init__.py src/mesh2step/convert.py tests/test_prism_build.py`
2. F2P-a: `python3 -m pytest -q tests/test_prism_build.py`
3. F2P-b: `python3 -m pytest -q tests/test_parity.py -k "handle-lock and trueform"`
4. P2P: `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`

In that order. `python3`, never `python`. P2P takes ~7 min — redirect to a file and read it.

## 4. CONVERGENCE LOOP

Ceiling **6** iterations: EDIT (§1 scope only) -> EXECUTE (§3 in order) -> PARSE -> PATCH.

**Author `tests/test_prism_build.py` FIRST and confirm it fails** before implementing.
(The `test_parity.py` half is already red, which is the point — do not touch it.)

On reaching the ceiling without convergence: STOP, do not report success, return the diff
and the unresolved failures with their numbers.

## 5. TERMINATION CRITERIA (BOOLEAN GATES)

- [ ] `fail_to_pass_status == ALL_PASSED` — every `DIAG_PRISMBUILD` field, AND the 3
      handle-lock parity tests green.
- [ ] `pass_to_pass_regressions == 0` — exactly 2 failures remain (nonprismatic-control),
      and no previously-passing test fails.
- [ ] `new_linter_diagnostics == 0` on the §3.1 files (`convert.py` measured as a delta
      against its own pre-edit fingerprint, not absolute zero).
- [ ] `tests/test_prism_build.py` was demonstrated RED before the implementation existed.

## 6. GUARDRAILS

- **Zero-Assumption Rule:** never declare completion without stdout and exit codes.
- **Translate, do not paraphrase.** Where this port transcribed the C++ it matched to six
  decimals first try; where it paraphrased what a function "seemed to do" it was wrong and
  cost two sessions.
- **Oracle Supremacy:** the reference's numbers are final. If your output disagrees, YOUR
  CODE is wrong. Never adjust an expected value to match what you produced. If convinced a
  golden datum is itself wrong, STOP and report it.
- **The non-prismatic path is a regression surface, not a target.** cube, S09 and
  nonprismatic-control must come out bit-identical to before your change. If any field of
  their RESULT moves, you have broken something — report it, do not absorb it.
- **Numerics:** bit-sensitive codebase. Transcribe tolerance expressions. `np.dot` on a
  3-vector is OpenBLAS `ddot` (an FMA chain) and equals neither `a*b+c*d+e*f` nor `m @ w`;
  `np.arctan2` differs from `math.atan2` by 1 ulp on ~2.4% of inputs. Reuse `lawband.py`'s
  `_row_dots` / `_ATAN2` rather than rolling your own.
- **Blast Radius:** minimal diffs, strictly inside §1. `convert.py` gets one branch.
- **Long commands:** redirect to a file under the scratchpad and read it. Do NOT rely on
  `watchjob`/`job log` — child stdout is discarded on this machine.
- **No git operations.** No commit, push, stash, checkout or branch. Leave the tree dirty.

## 7. REPORT BACK

The diff, the four command outcomes with exit codes, proof `test_prism_build.py` was red
first, the `DIAG_PRISMBUILD` assertion table (expected vs actual per field), the
handle-lock RESULT field table (all 9 fields above), and the P2P counts. Confirm explicitly
that cube, S09 and nonprismatic-control RESULTs are unchanged. Name anything you could not
make match, with the numbers.
