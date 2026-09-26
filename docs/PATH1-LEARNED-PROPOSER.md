# Path 1: CADFit as a verify/optimise proposer (bd projects-wtge)

## Decision log

- **2026-09-26, owner: CAD-Recode dropped.** CAD-Recode v1.5 (arXiv 2412.14042, open weights) ran on all 39
  mechparts (GPU, ~15 s/part, greedy + 4 sampled programs). Its programs, converted and measured with our scorer,
  won on merit on **0 of 39** parts: part 1 IoU 0.57 against our 0.99; its best parts (15, 18) reached score
  1.41-1.43 against our 1.496-1.500; 36 of 195 programs did not execute (arc construction failures) and several
  executed sketches were self-intersecting. Its coordinates are integers on a 200-step grid of the part's size, so
  its extents are quantized at about our tolerance. Its tooling was removed; path 1 is CADFit only.

## CADFit (arXiv 2605.01171 v3, ICML) — what it is

- **Operation set**: Extrude, Revolve, Fillet, Chamfer, Union, Cut. CadQuery/OCCT programs; no loft/sweep/intersect.
- **Loop**: optimisation, not generation. Single pass = (1) sketch profiles from planar-face clusters and
  axis-aligned slicing planes (loops resampled, fitted to line/arc/circle primitives); (2) extrude/revolve
  candidates per profile by a 1-D sweep of a one-sided Chamfer distance, keeping "stable intervals" (the error stays
  flat until the extrusion overshoots: the smallest interval containing h=0 and the largest one); (3) greedy forward
  selection of candidates that raise volume IoU, then IoU-guided backward pruning (drop any candidate whose removal
  does not lower IoU). Outer loop: residuals `M \ S` (fit and Union) and `S \ M` (fit and Cut), repeated until the
  residual volume is small or the budget ends. Finishing (App. N, flag `--fillet-chamfer`, off by default): per edge,
  a trial fillet/chamfer, kept if IoU rises, size refined by 1-D line search on IoU. A learned sketch prior (App. M,
  optional DINOv2 + MLP loop filter) only accelerates the search.
- **Cost**: minutes per shape (OCCT validation in the loop); paper reports zero invalid outputs.
- **Released**: code at github.com/ghadinehme/CADFit (commit fb31f63). **Licence CC BY-NC 4.0 and a provisional
  patent on the method**: research use only, commercial use needs a licence from the authors. No weights needed for
  the core loop (CPU only).
- **Failures they report**: shapes needing loft/sweep; smooth high-curvature parts with no stable planar sketches.

**Overlap with ours**: search.py already does evidence from planes/levels, level-snapped extents, greedy/beam
selection with pruning (`PR.prune`), residual cuts, and finishing by trial on the real solid. Worth adopting: revolve
candidates (we have none), the backward-pruning criterion "removal does not lower IoU", and the residual Union/Cut
loop running the same single-pass procedure on `M \ S` and `S \ M`.

## Running it here

- Clone in `.worktrees/interview/.cadfit`, venv `.venv-cadfit` (Python 3.10, `requirements.txt` as pinned: cadquery
  2.6.1, OCP 7.8.1, pymeshlab, manifold3d; all install from wheels). Both gitignored.
- `cd .cadfit && CADFIT_INNER_WORKERS=8 ../.venv-cadfit/bin/python run_pipeline.py <stl_dir> --output-folder out`
  (under watchjob). Output: `out/<n>/best_greedy_parallel_iterative.py`, a CadQuery script in the normalized frame
  (box centre, 2 / max extent).
- Conversion and measurement: `python3 tools/tree/cadquery_ir.py <script> <mesh> runs/tree/cadfit/<n>` (tree IR in
  mm, `analyse.measure` on both the tree and CADFit's own solid; revolve/fillet/chamfer are noted, not mapped).
- Results: `runs/tree/cadfit/summary.md` (39/39 ran; 3 merit wins: 15, 28, 37; none on the owner reference parts).
