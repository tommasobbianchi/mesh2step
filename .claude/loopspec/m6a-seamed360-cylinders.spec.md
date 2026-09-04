# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

## 1. TARGET GOAL

- **Functional Objective:** give `mesh2step` the constructor it is missing — a **seamed
  360° cylindrical face**. Today `BuiltAs.SEAMED360` is an enum value that is never
  assigned: `_build_cylindrical_face` builds a face for a `closed360=1` cylinder, the face
  does not sew, `build.py`'s **J6** check (`was_closed and not sh_closed`) fires, the
  recovery ladder explodes every region, and the component ships as one planar face per
  triangle wearing the analytic census.

  Port, from `refs/stl2step/src/refit_build.cpp`:
  - `seamVertexOf` (line 237)
  - `trySeamed360` (2599-2830)
  - `cylinderPostFitOk` (line 302) — gates acceptance of the seamed face
  - `tryTwoHalves` (2831) and the `CapLow`/`CapHigh` loop selection — the documented fallback
    when `trySeamed360` declines ("try TwoHalves" in its warnings)
  - the `closed360 && Cylinder` branch of `buildOneRegion` (3994-4015), which chooses
    between the two and sets `builtAs`
  - the plane-side binding of shared `Seamed360` cap circles: `refit_build.cpp:2114`
    ("Hole loops must bind shared Seamed360 cap circles with reversed orientation") and
    `:3888` ("Plane inner wires around Seamed360 holes: MakeEdge(circ,V,V)"). Without
    this the caps will not share the cylinder's seam circle and the shell will not close.
  - **`DIAG_COLLAPSE`** (3975-3979) as the acceptance instrument, gated on
    `MESH2STEP_COLLAPSE_DIAG` exactly as the reference gates on `STL2STEP_COLLAPSE_DIAG`.
    Same field names, same order, same format string — the two lines must diff directly.

  This is a **translation**, not a reimplementation. Where the C++ looks odd it is still
  the specification. This port has a documented precedent in both directions: where it
  transcribed, it matched the reference to six decimals first try; where it paraphrased
  what a function "seemed to do", it was wrong and cost two sessions. Cite
  `refit_build.cpp` line numbers in comments at every non-obvious step.

- **Target Files / Scope (writable):**
  - `src/mesh2step/refit/build.py` — all production code goes here.
  - `tests/test_seamed360.py` — NEW, the F2P file (see §4 authoring exception).

  Everything else is **read-only**: `segment.py`, `lawband.py`, `prism*.py`, `profile.py`,
  `dxf.py`, `convert.py`, every other test, every golden datum, and all of `refs/`
  (the reference is read-only truth — never edit it).

- **Open Bindings:**
  - Whether `tryTwoHalves` is reached at all on this corpus is unknown; the reference
    prefers `trySeamed360`. Port both, but if `tryTwoHalves` never fires on any fixture,
    say so in the report rather than inventing a test for it.
  - `_build_cylindrical_face`'s existing partial-cylinder path is NOT in scope. Do not
    refactor it. The new branch is taken only when `r.closed360` is true.

## 2. HARNESS ENVIRONMENT & GROUND TRUTH

- **Harness Interface:** the ordered command sequence in §3 is the sole oracle. There is
  no harness binary.

- **Ground truth, measured from the reference on 2026-09-04.** `nonprismatic-control` is a
  96-triangle, ~4-second fixture; use it, not Body11 (30+ minutes).

  Segmentation is ALREADY at exact parity — do not touch it:

  ```
  engine segment root=* regions=4 rejected=0 planes=2 cylinders=2 fillets=0 facetIslands=0
    id=0 type=cylinder tris=24 radius=10 closed360=1
    id=1 type=plane    tris=24 radius=0  closed360=0
    id=2 type=plane    tris=24 radius=0  closed360=0
    id=3 type=cylinder tris=24 radius=4  closed360=1
    cylinder radii:10.000000254386423,3.9999999641035373
  ```

  The reference's construction verdict, which is what you must reproduce:

  ```
  DIAG_COLLAPSE mix=0 none=0 fail=0 ok=4 total=4 recover=0 rounds=0
  ```

  Regenerate any of it with:
  ```
  STL2STEP_COLLAPSE_DIAG=1 refs/stl2step/RUN.sh tests/data/corpus/nonprismatic-control.stl \
    -o /tmp/ref_np.step --smooth --unify-angle 5 --quiet
  ```
  `refs/stl2step/RUN.sh` is REQUIRED — it sets the FreeCAD-snap `LD_LIBRARY_PATH`. The raw
  binary at `refs/stl2step/build/stl2step` exits 127.

- **Fail-to-Pass (F2P):** `tests/test_seamed360.py` — you author it (§4 exception). On
  `nonprismatic-control` it must assert, on OUR engine:
  1. both `closed360` cylinder regions end with `built_as == BuiltAs.SEAMED360`
     (today: `EXPLODED_TO_FACETS`);
  2. no region is exploded — the four regions build and stay built;
  3. the shell assembled from the analytic faces is **closed** (`BRep_Tool.IsClosed_s`),
     i.e. J6 does not fire and the facet fallback never runs;
  4. with `MESH2STEP_COLLAPSE_DIAG=1` the emitted `DIAG_COLLAPSE` line equals
     `mix=0 none=0 fail=0 ok=4 total=4 recover=0 rounds=0`.

  Drive our own pipeline to obtain the `MeshView` + `RegionSet` (see `tests/test_parity.py`
  and `src/mesh2step/convert.py` for the existing path; reuse it, do not invent a second).

- **Pass-to-Pass (P2P):** `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`.
  Baseline BEFORE your first edit is **78 passed, 3 failed** (`test_dxf_byte_identical`,
  and `nonprismatic-control.trueform` ×2). Those three are pre-existing.

  **Expected and permitted:** the two `nonprismatic-control.trueform` failures will very
  likely STILL FAIL after this milestone, because matching the reference's RESULT also
  needs the per-region volume-residual gate (`DIAG_CASCADE resid`, `refit_build.cpp:3282`)
  and the U0/U1/U2 cascade, which are **M6b and explicitly out of scope here**. What is
  NOT permitted is any test that passes at baseline failing afterwards, or the failure
  *reason* on those two changing to something worse (e.g. a crash instead of a counter
  mismatch). Report their exact assertion text before and after.

- **Test Integrity Constraint:** modifying, mocking, skipping, xfailing or loosening any
  existing test, fixture or golden datum is prohibited and invalidates the run. You may
  create `tests/test_seamed360.py` and nothing else under `tests/`.

## 3. VERIFICATION COMMANDS

1. Lint: `python3 -m ruff check src/mesh2step/refit/build.py tests/test_seamed360.py`
2. F2P: `python3 -m pytest -q tests/test_seamed360.py`
3. P2P: `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`

Run them in that order. `python3`, never `python` (there is no venv and no `python` on PATH).

## 4. CONVERGENCE LOOP

Iterate to a ceiling of **6** iterations:
1. **EDIT** — scoped changes to the §1 writable files only.
2. **EXECUTE** — the §3 sequence, in order.
3. **PARSE** — read failing assertions and linter records.
4. **PATCH** — derive the cause from the diagnostics and refine.

**Author the F2P test FIRST and confirm it fails** against the current code before
implementing. A test that has never been red proves nothing. Assertion 1 above is red today
for a reason you can print in one command.

**Build `DIAG_COLLAPSE` FIRST, before any constructor work.** It is the instrument that
tells you whether a chain collapsed, mixed, or failed, and this port's most expensive
lesson is that a counter is not a measurement until you know its domain. Porting the
reference's diagnostic first overturned two stated findings in a single session.

On reaching the ceiling without convergence: STOP. Do not report success. Return the diff
and the unresolved failures.

## 5. TERMINATION CRITERIA (BOOLEAN GATES)

Finalize IF AND ONLY IF, each backed by captured stdout:
- [ ] `fail_to_pass_status == ALL_PASSED` — all four assertions of §2.
- [ ] `pass_to_pass_regressions == 0` — still ≥78 passed, and no baseline-passing test now
      failing. The two `nonprismatic-control` failures may persist; nothing else may appear.
- [ ] `new_linter_diagnostics == 0` over the §1 writable files, compared as a
      `(file, code)` multiset against the pre-edit baseline. Absolute zero is NOT the gate —
      `convert.py:181` already carries a pre-existing `E501` that is not yours. Do not lint
      or fix the rest of the repo.
- [ ] The F2P test was demonstrated RED before the implementation existed.

## 6. GUARDRAILS

- **Zero-Assumption Rule:** never declare completion without stdout and exit codes.
- **Oracle Supremacy:** the reference's numbers are final. If your output disagrees, YOUR
  CODE is wrong — never adjust an expected value to match what you produced. If you become
  convinced a golden datum is itself wrong, stop and report it; do not edit it.
- **Blast Radius:** minimal diffs, strictly inside §1. No refactors, no new dependencies,
  no reformatting of untouched lines, no changes to `segment.py` or `convert.py`.
- **Numerics:** this codebase is bit-sensitive. Do not "simplify" a tolerance expression;
  transcribe it. Do not replace a scalar loop with a vectorised one — `np.dot` on a
  3-vector is OpenBLAS `ddot` and does not equal the scalar sum.
- **Long commands:** the P2P run takes ~11 minutes, which exceeds a foreground shell here.
  Launch it under
  `~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- '<command> > <file> 2>&1'`
  and read the file. Never `nohup`, `setsid`, a bare `&`, or a polling loop. Never answer
  "is it still running?" with `pgrep`/`ps`; use `~/.claude/scripts/job status <name>`.
  Redirect child stdout to a file — `job log` loses it on this machine.
- **No git operations.** No commit, no push, no stash, no checkout, no branch. Leave the
  working tree dirty for review.
- **Prior art:** an earlier attempt at this area (M3c, the plane|cylinder collapse) was
  rolled back after timing out at 7200 s having half-changed the surrounding code and
  broken S09. If you find yourself changing anything outside `_build_cylindrical_face`'s
  new `closed360` branch and its cap-wire binding, stop and report instead.

## 7. REPORT BACK

The diff, the three command outcomes with exit codes, proof the F2P test was red first, our
`DIAG_COLLAPSE` line beside the reference's, the `built_as` of all four regions before and
after, and the P2P pass/fail counts against the 78/3 baseline. Name anything you could not
make match, with the numbers.
