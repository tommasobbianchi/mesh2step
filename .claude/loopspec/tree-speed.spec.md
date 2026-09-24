# DELEGATION SPECIFICATION: HARNESS-DRIVEN VALIDATION LOOP

## 1. TARGET GOAL
- **Functional Objective:** `python3 tools/tree/bench.py` exits 0: the gate part's analysis
  (`tools/tree/analyse.py` on `~/corpora/tree_bench/gate.stl`, planner replies replayed from
  `tools/tree/bench/gate_plans.json`) finishes in **under 180 s wall** (baseline 250 s) while every part keeps
  its chosen path and quality floors (gate: planner, volume IoU ≥ 0.89, surface explained ≥ 0.77; clamp and
  m16: proposal, floors in `bench.py`). Achieve it with these four levers, which a second opinion verified in
  the code (file:line references valid at commit 73df8b1):
  1. **Fork-parallel axis trials in `plan.residual_prisms`** (plan.py ~286-340): for each blob the three axis
     candidates are independent given the base shape. Compile the base shape in the parent, then evaluate the
     candidates in `multiprocessing` workers started with the **fork** context (children inherit the OCCT shape
     and the cached mesh KD-tree copy-on-write; OCCT shapes are not picklable — pass tree JSON / indices, return
     plain floats and the candidate dict). At most 4 workers. **Threads are forbidden**: OCP holds the GIL and
     threads measured 0.34× (slower) on these calls.
  2. **No recomputed occupancy:** `tree.volume_iou` (tree.py ~420-430) computes the solid's occupancy grid and
     throws it away; `residual_prisms` then recomputes it on the identical shape and grid (plan.py ~301). Return
     it (e.g. `volume_iou(..., return_occ=True)` → `(iou, occ)`) and reuse it. The mesh's occupancy at n=60 is
     computed in both `analyse.py` (~line 35) and `plan.residual_prisms` (~288): compute once, pass it in.
     Do NOT change the n=40 grid used by `plan.build`'s score (changing grids shifts scores; see limits).
  3. **Prefix-cached compile:** `tree.compile_tree` recompiles every feature list from scratch. Add a cache keyed
     by the JSON of the feature-list prefix that returns the already-compiled OCCT shape of that prefix, so a
     candidate that appends/inserts one feature reuses the shape of the unchanged prefix. Use it where the
     prefix repeats: `plan.build`'s `score`, `plan.residual_prisms`' `score`, `propose.refine`/`propose.score`.
     The compiled result for a given feature list must be identical to today's (same booleans on the same
     inputs, same `ShapeUpgrade_UnifySameDomain` at the end — keep that step exactly as is).
  4. **No duplicate final scoring:** the final tree is compiled and measured several times (end of
     `plan.build`, `plan.plan_tree`, `analyse.measure`); thread the already-computed shape / deviation /
     score through instead of recomputing when the tree is unchanged.
- **Target Files / Scope:** writable: `tools/tree/tree.py`, `tools/tree/plan.py`, `tools/tree/propose.py`,
  `tools/tree/analyse.py`. Everything else is read-only — in particular `tools/tree/bench.py`,
  `tools/tree/bench/gate_plans.json`, `tools/tree/test_tree.py`, `tools/tree/fcstd.py`, `tools/tree/fix.py`,
  `tools/interview/*`, `tools/recon/*`, and the meshes in `~/corpora/tree_bench/`.
- **Open Bindings:**
  - Random sampling (`trimesh.sample.sample_surface`) is seeded once in `analyse.main` (`np.random.seed(0)`).
    Parallel workers consume random numbers in a different order, so surface metrics may move by ~1e-3.
    Default: acceptable as long as `bench.py` passes; do not add per-worker reseeding games to force equality.
  - If one lever gives no measurable gain, leaving it out is allowed; the gate is the benchmark, not the list.

## 2. HARNESS ENVIRONMENT & GROUND TRUTH
- **Harness Interface:** there is no harness binary; the harness is the ordered command sequence of §3 and its
  exit codes. `tools/tree/bench.py` is the sole oracle of speed and quality. Interpreter: `/usr/bin/python3`
  (OCP, trimesh, shapely, scipy are installed in the user site; there is no venv).
- **Fail-to-Pass (F2P) Criteria:** `python3 tools/tree/bench.py --only gate` — fails now (wall ≈ 250 s >
  180 s), must pass at the end.
- **Pass-to-Pass (P2P) Criteria:** `python3 -m pytest -q tools/tree/test_tree.py` (4 tests, green at baseline)
  and the clamp + m16 parts of `python3 tools/tree/bench.py` (green at baseline: 22.6 s and 15.3 s).
- **Test Integrity Constraint:** Modifying, mocking, skipping, xfailing or otherwise tampering with
  `tools/tree/test_tree.py`, `tools/tree/bench.py`, `tools/tree/bench/gate_plans.json` or the meshes invalidates
  the run. Lowering sample counts, slice counts, tessellation deflection, refine evaluations or acceptance
  thresholds to win time is tampering with the quality contract and is also prohibited.

## 3. VERIFICATION COMMANDS
1. Lint & Static Analysis: `ruff check --output-format=json tools/tree/tree.py tools/tree/plan.py tools/tree/propose.py tools/tree/analyse.py`
2. Harness Patch Evaluation: `python3 tools/tree/bench.py`
3. Targeted Test Execution: `python3 -m pytest -q tools/tree/test_tree.py`

Run slot 2 under a memory cap and a supervisor, never bare in the background: it takes minutes and OCCT can
allocate tens of GB on a bad shape. Use:
`~/.claude/skills/watchjob/scripts/watchjob.sh tree-speed-bench -- 'cd <worktree> && ulimit -v 12000000 && python3 tools/tree/bench.py > bench.out 2>&1'`
and read `bench.out`; check status with `~/.claude/scripts/job status tree-speed-bench` (never pgrep/ps).

## 4. CONVERGENCE LOOP (FORMAL EXECUTION PROTOCOL)
Iterate until termination criteria hold, ceiling 6 iterations:
1. **EDIT:** apply scoped modifications to in-scope source files.
2. **EXECUTE:** run the §3 sequence in order.
3. **PARSE:** read bench.py's JSON lines (wall_s, chosen, iou, explained, fails), pytest failures, ruff records.
4. **PATCH:** derive root cause from the parsed diagnostics and refine the edit. To find where time goes,
   time functions with wrappers (see how `time.time()` deltas per function were summed) — do not guess.
On ceiling without convergence: stop, do not report success, return the last diff plus the unresolved failure set.

## 5. TERMINATION CRITERIA (BOOLEAN GATES)
Finalize IF AND ONLY IF all gates hold, each backed by captured stdout:
- [ ] `harness_exit_code == 0` (bench.py prints `{"verdict": "PASS", ...}`)
- [ ] `fail_to_pass_status == ALL_PASSED` (gate line: `"ok": true`, `wall_s` < 180)
- [ ] `pass_to_pass_regressions == 0` (pytest 4 passed; clamp and m16 lines `"ok": true`)
- [ ] `new_linter_diagnostics == 0` — post-edit `(file, code)` multiset over the four writable files introduces
      no code absent from the baseline and raises no count. Baseline fingerprint (ruff 0.16.5, commit 73df8b1):
      `{('analyse.py','E501'):7, ('analyse.py','I001'):1, ('analyse.py','E702'):1, ('plan.py','E501'):70,
      ('plan.py','I001'):3, ('plan.py','E702'):11, ('plan.py','TRY003'):4, ('plan.py','B905'):1,
      ('plan.py','E401'):1, ('plan.py','F401'):1, ('plan.py','E731'):1, ('plan.py','RUF005'):1,
      ('propose.py','E501'):35, ('propose.py','E702'):20, ('propose.py','I001'):1, ('propose.py','E731'):1,
      ('propose.py','B905'):1, ('propose.py','RUF005'):1, ('propose.py','B023'):1, ('tree.py','E501'):45,
      ('tree.py','I001'):2, ('tree.py','E731'):3, ('tree.py','E702'):39, ('tree.py','TRY003'):1,
      ('tree.py','RUF005'):1}` (analyse.py gained one import line after the fingerprint; an I001 there is not new).
      Absolute zero is NOT the gate; fixing pre-existing diagnostics is a scope violation.

## 6. GUARDRAILS & EXECUTION CONSTRAINTS
- **Zero-Assumption Rule:** completion is never declared without verifiable stdout and exit codes.
- **Context Preservation:** no raw log dumps; extract diagnostic diffs and failure traces only.
- **Blast Radius Limitation:** minimal diffs, strictly inside the §1 scope; no drive-by refactors, no dependency
  additions, no reformatting of untouched lines. No git commits, no pushes.
- **Oracle Supremacy:** the harness verdict is final. A floor you believe is wrong is still the specification;
  report the disagreement and stop.
- **Baseline Obligation:** before the first EDIT, run §3 once and record the baseline.
- **Memory:** never run more than 4 OCCT worker processes; the analysis runs under an 8 GB cap in production.
