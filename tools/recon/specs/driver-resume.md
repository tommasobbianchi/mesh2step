# driver-resume — resumable corpus driver and an honest summary

## Context
`corpus_loop.sh` runs `one_part.sh` for every part (39 numbered mechparts plus `hotend` and
`polydryer`) and then `corpus_summary.py` prints a live-vs-loop table. Two defects: a failed run
cannot be resumed without redoing every finished part, and the summary counted "better/worse" by
slicing the printed string (it reported 0 better / 0 worse while parts 6, 11, 12, 16, 19 gained and
part 17 lost). It also cannot tell a part that never ran from one that ran and failed.

## Change ONLY `corpus_summary.py` and `corpus_loop.sh`. Do not edit anything under `tests/`.

## Required behaviour (the acceptance test is `tests/test_driver.py`; read it first)

1. `corpus_summary.py` must be importable with no side effects: move the current top-level work
   into `main()` and end with `if __name__ == "__main__": main()`.
2. Add, at module level:
   - `part_status(workdir, part) -> "done" | "failed" | "not_run"`
     (`done`: `workdir/recon2_<part>/best.json` exists; `failed`: that directory exists without
     `best.json`; `not_run`: no such directory). Accept `str` or `Path` for `workdir`.
   - `parts_to_run(workdir, parts) -> list` — parts whose status is not `done`, order preserved.
   - `tally(rows) -> dict` with keys `better, worse, same, failed, not_run`, where `rows` are dicts
     `{"part", "live", "loop", "status"}`: for `done` compare the numbers `loop` vs `live`; a
     `failed` part counts in `failed` and also in `worse` when `live > 0`; `not_run` counts only in
     `not_run`.
3. `main()` keeps printing the same per-part table and the TOTAL line, adds a `status` column
   (`done`/`failed`/`not_run`), and replaces the broken "parts better/worse" line with the output of
   `tally()`. The working directory stays the current default but may be overridden with
   `$RECON_WORKDIR`.
4. `corpus_loop.sh`: build the part list as today, then run only
   `parts_to_run(<workdir>, <all parts>)` (call it via `python3 -c`), with parallelism from
   `$RECON_PARALLEL` (default **2**, was 4 — four parallel model sessions exhausted the quota), then
   run the summary. Keep using `one_part.sh` and `xargs -P`.

## Check
`cd <worktree> && python3 -m pytest -q tests/test_driver.py` must pass.
