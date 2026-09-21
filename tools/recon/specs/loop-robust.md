# loop-robust — make recon_loop.py survive model-CLI failures and pick a sane best round

## Context
`recon_loop.py` drives a reverse-engineering loop: it asks a model CLI (`claude -p ...`) to write a
CadQuery program, executes it, measures the result against a mesh (`gate()`), feeds the report
back, and repeats. In a real run, every part after the first 20 logged "model wrote no program"
for all rounds: the CLI failed (almost certainly a usage limit) and the loop neither saw why nor
waited. It also picked a "best" round that was 8.2 mm off the part because it ranked rounds by
feature count alone.

## Change ONLY `recon_loop.py`. Do not edit anything under `tests/`. Do not add dependencies.

## Required behaviour (the acceptance test is `tests/test_loop.py`; read it first)

1. **Importable.** `import recon_loop` must not read `sys.argv`, load meshes or run anything.
   Move the script body into `main()` and end the file with
   `if __name__ == "__main__": sys.exit(main())`. Keep the command line unchanged:
   `recon_loop.py <stl> <facts.json> <render_dir> <workdir> [model=opus] [iters=4]`.
   Everything `main()` needs that is currently a module global computed from argv (STL, WD,
   mesh, renders, BRIEF, ...) must be computed inside `main()` and passed where it is used.
   Helper functions that are pure (`select_best`, see 5) must stay at module level.

2. **Model CLI path.** Use `os.environ.get("CLAUDE_BIN", "/home/tommaso/.local/bin/claude")`.

3. **Capture the CLI result.** `ask_model()` must return the CLI's return code and its combined
   stdout+stderr text (trimmed to the last 2000 characters is fine).

4. **Failure handling per round.**
   - If the program file was written, proceed as today.
   - If it was not written and the CLI output matches a usage/rate limit (case-insensitive
     substrings: `usage limit`, `rate limit`, `rate_limit`, `overloaded`, `429`, `quota`), retry the
     SAME round: sleep `float(os.environ.get("RECON_BACKOFF_S", "600"))` seconds, call again, up to
     `int(os.environ.get("RECON_QUOTA_RETRIES", "3"))` retries. Retries do not consume a round.
     If all retries fail: append the round to history with `"error"` containing the CLI output,
     write `history.json`, and exit with code **75**.
   - Any other failure (no file, CLI output not a limit): append the round with `"error"`
     containing the CLI output (not just "no file"), and continue to the next round. No retry.
5. **Best-round selection.** Add a module-level pure function
   `select_best(history, diag) -> dict | None`:
   - consider only entries whose `report` is a dict with `valid == True`
   - fidelity bound = `0.005 * diag`; `err(h) = max(report["p95_mesh_to_solid"], report["p95_solid_to_mesh"])`
   - among entries with `err <= bound`: pick max `report["features"]["curved"]`, tie-break smaller `err`
   - if none is within the bound: pick the valid entry with the smallest `err`
   - no valid entry: return `None`
   Use it where the best round is chosen today (`diag` = the mesh's bounding-box diagonal), keeping
   `best.step`, `best.json` and the printed `BEST`/`REPRESENT` lines.
6. **Exit codes.** At the end of `main()`: return 0 if at least one valid round exists, else 2.
   Quota exhaustion returns 75 as in 4.

## Do not change
The prompt text sent to the model (other than where it is built), `gate()`'s measurements,
`represent_detail()`, the stop rule, or the facts/render handling.

## Check
`cd <worktree> && python3 -m pytest -q tests/test_loop.py` must pass (it takes ~2 minutes: it runs
real CadQuery and the real gate on a small cube, with a fake CLI).
