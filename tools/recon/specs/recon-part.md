# recon-part — one upload through render -> facts -> reflective loop, over a model cascade

## Context
`tools/recon/recon_loop.py` reconstructs one part with one model. The webapp needs a single
command that takes an uploaded STL and produces the best reconstruction it can, trying cheaper
models first and escalating only when the gate is not satisfied.

## Create `tools/recon/recon_part.py`. Do not modify other files. Do not edit `tests/`.

## Required behaviour (acceptance test: `tools/recon/tests/test_recon_part.py` — read it first)
CLI: `recon_part.py <stl> <workdir> --models M1 [M2 ...] [--rounds N=5] [--timeout S=2700]`

1. Create `<workdir>`. Render the mesh with
   `python3 ~/.claude/skills/deepseek-vision/scripts/render.py <stl> --out <workdir>/vis --crops 2`
   (make `<workdir>/vis` exist even if rendering fails; log and continue — the loop runs without
   images). Then `python3 <here>/facts.py <stl> <workdir>/facts.json auto`.
2. For each model in order: run
   `python3 <here>/recon_loop.py <stl> <workdir>/facts.json <workdir>/vis <workdir>/m<i>_<slug> <model> <rounds>`
   (slug = model string with every non-alphanumeric char replaced by `_`; `i` starts at 1), with
   the remaining share of `--timeout` as the subprocess timeout (a timeout counts as a non-accepted
   run; start each loop with `start_new_session=True` and on timeout `os.killpg` its group with
   SIGKILL -- the loop keeps its model call in its own group, so this is what stops a hung call).
   Environment is inherited (CLAUDE_BIN, OPENCODE_BIN, RECON_* pass through).
   Record `{"model", "exit", "accepted"}` in `models_tried`.
3. ACCEPTED means: `<modeldir>/best.json` exists, its `report.valid` is true,
   `max(report.p95_mesh_to_solid, report.p95_solid_to_mesh) <= 0.005 * diag` (diag = the mesh's
   bounding-box diagonal via trimesh), and `represent.curved == represent.patches`.
   The first accepted model wins: stop the cascade.
4. If no model is accepted, keep the best valid result across all models that produced a
   `best.json`: highest `represent.curved`, then smaller max p95.
5. Write `<workdir>/recon_result.json` with keys `status`, `model`, `best_step` (absolute path of
   the winning model dir's `best.step`, or null), `report`, `represent`, `models_tried`, `seconds`,
   and exit: `accepted` → 0, `best_effort` → 3, `unavailable` (every model's loop exited 75) → 75,
   `failed` (no valid best anywhere) → 2.
6. Print one final line: `RECON status=<s> model=<m> seconds=<t> curved=<c>/<p> p95=<e>`.

## Check
`cd /home/tommaso/projects/mesh2step && timeout 1200 python3 -m pytest -q tools/recon/tests/` — all pass.
