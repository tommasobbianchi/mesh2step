# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

## 1. TARGET GOAL

- **Functional Objective:** expose the TrueForm (analytic) engine through the web app,
  alongside the existing faceted one. `POST /api/convert` gains one field:

      engine: str = Form("faceted")     # "faceted" | "trueform"

  `"faceted"` keeps TODAY'S behaviour byte for byte — same call to `convert_file`, same
  response shape, same keys. Every existing test in `tests/test_webapp_api.py` must pass
  unchanged; that is the definition of "unchanged".

  `"trueform"` instead calls

      mesh2step.convert.convert_trueform(in_path, out_path, unify_angle=<unify_angle>,
                                         schema=<schema>)

  and returns its `ParityResult` mapped onto the SAME response envelope the client already
  renders: `{"ok": bool, "stats": {...}, "download_token": str}`.

  `convert_trueform` takes ONLY `unify_angle`, `schema` and `dxf_dir` — no tolerance, no
  repair, no cuts, no merge-coplanar. So:
  - add `unify_angle: float = Form(5.0)`, used only by the trueform path;
  - if `engine == "trueform"` and `repair` is not None, or `cuts` is not None → **HTTP 400**
    naming the field ("repair is not available with the trueform engine"). Do not silently
    ignore them: a knob that appears to apply and does not is worse than a refusal.
  - `tolerance` and the two `merge_coplanar_*` fields are slider defaults the browser always
    sends, so under trueform they are accepted and ignored. Say so in one comment.
  - reject any `engine` outside the two values with **HTTP 400**, the way `schema` already is.

  **The stats mapping** (`ParityResult` → the dict the client reads). Emit these keys, so the
  existing frontend renders a trueform result without changes:

      is_solid          <- solids > 0 and open_shells == 0
      watertight        <- watertight
      n_faces_built     <- faces_after_smooth if smooth else faces_after_unify
      volume            <- step_volume_mm3
      n_input_tris      <- triangles
      n_input_verts     <- vertices
      schema            <- the request's schema
      seconds           <- seconds
      warnings          <- warnings

  plus, passed through verbatim for a trueform-aware UI:
  `smooth_planes`, `smooth_cylinders`, `smooth_fillets`, `smooth_built_components`,
  `smooth_reverted_components`, `faces_after_smooth`, `volume_delta_pct`.
  Add `"engine": "faceted"|"trueform"` to the stats dict on BOTH paths.

  On `result.ok == False`, mirror the faceted path exactly: remove the workdir and return
  `{"ok": False, "stats": d}` with no token.

- **Target Files / Scope (writable):**
  - `webapp/server.py`
  - `webapp/static/index.html`, `webapp/static/app.js`, `webapp/static/style.css`
  - `tests/test_webapp_api.py` — **append only**. You may add new test functions; you may not
    modify, rename, weaken or delete a single existing one (§4 authoring exception).

  Everything else is read-only, in particular all of `src/mesh2step/**` (the conversion
  engines are finished and byte-verified against a reference binary — if you believe one is
  wrong, report it, do not edit it), every other test, and `refs/`.

- **Frontend:** an engine selector in the settings panel (`#settings-panel`, alongside the
  existing `#repair` `<select>` at index.html:130). Selecting TrueForm must DISABLE the
  controls it cannot honour — the repair select, the tolerance slider + number input, and the
  cut buttons/panel — and show the unify-angle input in their place. Disabled, visibly, not
  hidden: the user should see the knob exists and does not apply here. Match the existing
  markup and CSS conventions; do not restyle the panel or introduce a framework.

- **Open Bindings:**
  - Default engine stays `"faceted"`. Do not make trueform the default.
  - `unify_angle` default 5.0 (the value the corpus and the CLI use).
  - TrueForm is slow on large meshes (minutes). Do NOT add a timeout, a progress bar or a
    background-job queue — out of scope, and the existing 200 MB cap already bounds input.

## 2. HARNESS ENVIRONMENT & GROUND TRUTH

- **Harness Interface:** the ordered command sequence in §3 is the sole oracle.

- **Fail-to-Pass (F2P):** new test functions you append to `tests/test_webapp_api.py`. They
  must cover, at minimum:
  1. `engine=trueform` on the existing `cube_stl_bytes` fixture returns 200, `ok is True`,
     `stats["engine"] == "trueform"`, `is_solid is True`, and `abs(volume - 1000.0) < 1e-3`
     — the same cube the faceted test asserts, so the two engines are compared on one shape.
  2. `engine=trueform` with `repair=weld` → 400.
  3. `engine=trueform` with a non-empty `cuts` JSON → 400.
  4. `engine=bogus` → 400.
  5. the download token from a trueform conversion round-trips through `/api/download/{token}`
     and the bytes start with `ISO-10303-21` (a real STEP file, not an empty one).

  Reuse the module's existing fixtures and `client`; do not add a second app-construction path.

- **Pass-to-Pass (P2P):** `python3 -m pytest -q tests/test_webapp_api.py` — **12 passed** at
  baseline, every one of which must still pass.

  Then the full guard: `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`.
  Baseline is **81 passed, 1 failed**. The one failure is `test_dxf_byte_identical`; it is a
  known 3-ulp floating-point divergence in an unrelated file, it is NOT yours, and fixing it
  is out of scope. No test that passes at baseline may fail afterwards.

- **Test Integrity Constraint:** modifying, mocking, skipping, xfailing or loosening any
  existing test, fixture or golden datum is prohibited and invalidates the run.

## 3. VERIFICATION COMMANDS

1. Lint: `python3 -m ruff check webapp/server.py tests/test_webapp_api.py`
2. F2P + webapp P2P: `python3 -m pytest -q tests/test_webapp_api.py`
3. Full P2P: `python3 -m pytest -q tests/ -k "not Body11 and not Body28"`

In that order. `python3`, never `python`. Slot 3 takes ~12 minutes — redirect it to a file
under `/tmp/claude-1000/-home-tommaso-projects-mesh2step/55ed36d6-4f09-4e83-a602-2227174fbd8a/scratchpad/`
and read the file; do not stream it into your context.

**Lint baseline:** `webapp/server.py` and `tests/test_webapp_api.py` are both ruff-clean
today. The gate is therefore zero NEW diagnostics on those two files. Do not lint or fix the
rest of the repo — it has pre-existing diagnostics that are not yours (`convert.py:181` E501
among them).

## 4. CONVERGENCE LOOP

Ceiling **6** iterations: EDIT (§1 scope only) → EXECUTE (§3 in order) → PARSE the failing
assertions → PATCH from the diagnostics.

**Author the F2P tests FIRST and confirm they fail** against the unmodified server. A test
that has never been red proves nothing.

On reaching the ceiling without convergence: STOP, do not report success, return the diff and
the unresolved failures.

## 5. TERMINATION CRITERIA (BOOLEAN GATES)

Finalize IF AND ONLY IF, each backed by captured stdout and an exit code:
- [ ] `fail_to_pass_status == ALL_PASSED` — all five F2P cases.
- [ ] `pass_to_pass_regressions == 0` — `tests/test_webapp_api.py` still ≥12 passed; the full
      run still ≥81 passed with `test_dxf_byte_identical` as the only failure.
- [ ] `new_linter_diagnostics == 0` on the two §3.1 files.
- [ ] The F2P tests were demonstrated RED before the server change existed.
- [ ] A faceted request produces a response dict identical to today's apart from the added
      `"engine": "faceted"` key. Show it.

## 6. GUARDRAILS

- **Zero-Assumption Rule:** never declare completion without stdout and exit codes.
- **Blast Radius:** minimal diffs inside §1. No refactor of the faceted path, no new
  dependency, no reformatting of untouched lines, no restyling of the settings panel beyond
  the one new control and the disabling logic.
- **Do not touch `src/`.** If the mapping in §1 cannot be built from `ParityResult` as it
  stands, say which field is missing and stop — do not add one.
- **Oracle Supremacy:** the harness verdict is final. A test you believe is wrong is still the
  specification; report the disagreement, do not edit the test to agree with your code.
- **Long commands:** redirect to a file in the scratchpad and read the file. Do NOT rely on
  `watchjob`/`job log` for child stdout — it is discarded on this machine.
- **No git operations.** No commit, push, stash, checkout or branch. Leave the tree dirty for
  review.

## 7. REPORT BACK

The diff (`git diff --stat` then the server hunk), the three command outcomes with exit codes,
proof the F2P tests were red first, the faceted-response comparison from gate 5, the trueform
stats dict for the cube, and the P2P counts against the 12 / 81+1 baselines. Name anything you
could not make work, with the numbers.
