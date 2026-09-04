# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

## 1. TARGET GOAL

- **Functional Objective:** Port `writeProfileDxf` from `refs/stl2step/src/dxf_export.cpp`
  (326 lines) to Python as `write_profile_dxf(profile, lv, path) -> bool`, producing a DXF
  **byte-identical** to the reference's, and expose it through the CLI as `--dxf <dir>`
  (mirroring `refs/stl2step/src/main.cpp:113` and `stl2step.cpp:298`): one file per slab,
  named `<stem>-comp<N>-slab<M>.dxf`, written only for prismatic parts, off by default.

  This is a **translation**, not a reimplementation. The reference is a pure serializer
  (`refit_prism.hpp:66`: "P4. Pure serializer; never consulted by the engine") — so this
  milestone must not change any geometry, any counter, or any existing output.

- **Target Files / Scope (writable):**
  - `src/mesh2step/refit/dxf.py` — NEW. All serializer code.
  - `tests/test_dxf.py` — NEW. The F2P test file (see §4 authoring exception).
  - `src/mesh2step/refit/__init__.py` — exports ONLY.
  - `src/mesh2step/cli.py` — add the `--dxf <dir>` argument and its call site ONLY.
  - `src/mesh2step/convert.py` — pass the dxf directory through ONLY. A few lines; do not
    restructure anything, do not touch route P's geometry.

  Everything else is **read-only**: `segment.py`, `lawband.py`, `build.py`, `prism.py`,
  `profile.py`, `prism_build.py`, `webapp/`, every other test, and all of `refs/`
  (read-only truth — instrument a COPY under /tmp if you need debug output, never `refs/`).

- **Prerequisites already in the tree:** `profile.py` (`Profile`, `ProfLoop`, `ProfSeg`),
  `prism.py` (`PrismLevels`), and route P wired into `convert.py` by milestone P3.

- **Open Bindings:** none. The output format is fixed byte-for-byte by the oracle below.

## 2. HARNESS ENVIRONMENT & GROUND TRUTH

- **Harness Interface:** the ordered command sequence in §3 is the sole oracle.

- **Ground truth — two DXF files committed to the repo**, verified byte-identical across
  two separate reference runs before being committed (so a byte comparison is legitimate):
  - `tests/data/reference/handle-lock-comp0-slab0.dxf` (520 lines, 3686 bytes)
  - `tests/data/reference/handle-lock-comp0-slab1.dxf` (1378 bytes)

  Note the header carries real data you must reproduce exactly, including full float
  precision — e.g. `$PROJECTNAME` = `slab=0 y0=-288.8257335910635 y1=-280.4507313341132`,
  and the `999` comment lines `stl2step profile dxf`, `declined=0`,
  `axis=7.780675247834571e-06,0.9999999999697307,0`. Float formatting is part of the
  contract: match the reference's `printf` formats exactly, do not use Python defaults and
  hope.

  Regenerate with:
  ```
  refs/stl2step/RUN.sh tests/data/corpus/handle-lock.stl -o /tmp/ref.step \
    --smooth --unify-angle 5 --dxf <outdir> --quiet
  ```
  `refs/stl2step/RUN.sh` is REQUIRED (FreeCAD-snap `LD_LIBRARY_PATH`); the raw binary at
  `refs/stl2step/build/stl2step` exits 127.

  handle-lock is the ONLY prismatic fixture in the corpus, so it is the whole F2P set.
  Body11/Body28 are excluded (30-60 min each, neither prismatic).

- **Fail-to-Pass (F2P):** `tests/test_dxf.py` — you author it. It must run our own CLI with
  `--dxf` on handle-lock into a tmp dir and assert the produced files are **byte-identical**
  to the two committed goldens (`filecmp.cmp(..., shallow=False)` or a bytes comparison).
  On mismatch, report the first differing line number and both lines — a bare `assert
  a == b` on 3686 bytes is undebuggable.

- **Pass-to-Pass (P2P):** `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`.
  **Measure the baseline yourself before editing.** As of milestone P3 the expectation is
  2 remaining failures (nonprismatic-control.trueform x2); if you measure something else,
  report the discrepancy rather than assuming. No currently-passing test may fail.

  **Critical:** without `--dxf`, every existing output must be byte-identical to before
  your change. This is a serializer; if any RESULT field of any fixture moves, you have
  broken something — report it, do not absorb it.

- **Test Integrity Constraint:** modifying, mocking, skipping, xfailing or loosening any
  existing test, fixture or golden datum is prohibited and invalidates the run. The two
  `.dxf` files and everything else under `tests/data/reference/` are ORACLES — never edit
  them. You may create `tests/test_dxf.py` and nothing else under `tests/`.

## 3. VERIFICATION COMMANDS

1. Lint: `python3 -m ruff check src/mesh2step/refit/dxf.py src/mesh2step/refit/__init__.py src/mesh2step/cli.py src/mesh2step/convert.py tests/test_dxf.py`
2. F2P: `python3 -m pytest -q tests/test_dxf.py`
3. P2P: `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`

In that order. `python3`, never `python`. P2P takes ~8 min — redirect to a file and read it.

## 4. CONVERGENCE LOOP

Ceiling **6** iterations: EDIT (§1 scope only) -> EXECUTE (§3 in order) -> PARSE -> PATCH.

**Author `tests/test_dxf.py` FIRST and confirm it fails** before implementing.

On the ceiling without convergence: STOP, do not report success, return the diff and the
unresolved failures with the first differing byte offset.

## 5. TERMINATION CRITERIA (BOOLEAN GATES)

- [ ] `fail_to_pass_status == ALL_PASSED` — both DXF files byte-identical to the goldens.
- [ ] `pass_to_pass_regressions == 0` — no previously-passing test fails.
- [ ] `new_linter_diagnostics == 0` on the §3.1 files (`cli.py`/`convert.py` measured as a
      delta against their own pre-edit fingerprints, not absolute zero).
- [ ] `tests/test_dxf.py` was demonstrated RED before the implementation existed.

## 6. GUARDRAILS

- **Zero-Assumption Rule:** never declare completion without stdout and exit codes.
- **Translate, do not paraphrase.** Float formatting especially: transcribe the reference's
  format strings. A DXF that "looks right" but prints `-288.82573359106350` where the
  reference prints `-288.8257335910635` fails, correctly.
- **Oracle Supremacy:** the goldens are final. Never regenerate a golden to match your
  output. If you believe a golden is wrong, STOP and report it.
- **This milestone changes no geometry.** It is a serializer. Any movement in any existing
  RESULT field is a bug you introduced.
- **Blast Radius:** minimal diffs, strictly inside §1.
- **Long commands:** redirect to a file under the scratchpad and read it. Do NOT rely on
  `watchjob`/`job log` — child stdout is discarded on this machine.
- **No git operations.** No commit, push, stash, checkout or branch. Leave the tree dirty.

## 7. REPORT BACK

The diff, the three command outcomes with exit codes, proof the F2P test was red first,
byte-comparison results for both DXF files, and the P2P counts against your measured
baseline. Confirm explicitly that no fixture's RESULT changed when `--dxf` is not passed.
