# tools/recon — reflective reconstruction

Reverse engineering that relies on a model understanding the shape, not on a builder per
object type. Code measures and checks; the model decides the construction.

```
facts.py      mesh -> measured facts: slice levels along the least-varying axis, every loop fitted
              to exact lines/arcs with coordinates, per-loop draft (Steiner recess)
recon_loop.py renders + facts -> model writes a CadQuery program -> execute -> gate -> feed back
              WHERE it is wrong -> revise (<= N rounds); keeps the best round
shape_check.py two-way mesh <-> solid distance (tessellation respects face orientation)
cqshim.py     lets cadquery import where cadquery-ocp and cadquery-ocp-novtk coexist
one_part.sh / corpus_loop.sh / corpus_summary.py   resumable corpus run + live-vs-loop table
```

The gate reports, every round: BRepCheck validity (and which faces are invalid, with a
deterministic repair attempt via `feature_recon/auto25g.repair_step_shape`), the analytic face
census, two-way p95 distance, clusters of surface the solid misses or adds, and every mesh
cylinder patch that does not land on an exact analytic face (`scripts/patch_representation`,
the same strict instrument as `mechparts-baseline.tsv`). The best round is the one with most
represented features among rounds within 0.5 % of the diagonal.

## Run

```bash
# one part (numbered = ~/corpora/mechparts/<n>.stl, else runs/uploads/<name>.stl)
tools/recon/one_part.sh 16
# resumable corpus run (only parts without runs/recon2_<part>/best.json)
RECON_PARALLEL=2 RECON_QUOTA_RETRIES=18 RECON_BACKOFF_S=600 tools/recon/corpus_loop.sh
python3 tools/recon/corpus_summary.py
python3 -m pytest -q tools/recon/tests
```
Renders come from `~/.claude/skills/deepseek-vision/scripts/render.py` into `runs/vis/<part>/`.
Model CLI: `$CLAUDE_BIN` (default `~/.local/bin/claude`), model `$RECON_MODEL` (default opus).
A usage/rate limit retries the same round with backoff and exits 75 when exhausted.

## Measured 2026-09-21 (39 mechparts, strict instrument)

loop 1241/1244 = 99.8 % vs live pipeline 1116/1244 = 89.7 %; loop >= live on all 39 parts,
0 worse; every solid valid; p95 <= 0.08 mm. Blockers: 16 0->8/8, 19 0->17/17, 33 81->121/121,
6 14->49/52, 11 22->34/34, 17 50/50 (after the repair step). Forgetful memory 3236.
