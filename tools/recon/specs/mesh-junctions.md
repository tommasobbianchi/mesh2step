# mesh-junctions — the same junctions and blends, found on a triangle mesh (library, part 2)

## Create `tools/recon/mesh_junctions.py`.

## Required behaviour (acceptance test: `tools/recon/tests/test_mesh_junctions.py`)
`extract(stl_path) -> {"junctions": [...], "blends": [...]}` with the SAME record schema and `sig` strings as
`tools/recon/junctions.py` (docs/JUNCTIONS.md). Fields that cannot be known from a mesh may be approximate
(radius within 3%, torus blend radius within 5%) but kinds, curve, state and round/fillet must be right.
1. Segment the mesh into faces: planar regions (coplanar triangle clusters), and cylinder/cone/torus/sphere
   regions by fitting. Existing code you may reuse: `tools/feature_recon/quads.py` (`classify` finds
   cylinder patches with radius and axis from tessellation quads), numpy, scipy, trimesh.
2. Region adjacency via shared triangle edges; for each adjacent pair classify the junction (tangent from the
   normal jump across the boundary, convex from its sign, curve line/circle by fitting the boundary polyline,
   circle radius from the fit). A boundary between two planes is one junction per straight segment.
3. Blends: a curved region tangent to two different neighbours, same rules as junctions.py.
4. Bounded cost: mechparts/15.stl (1784 triangles) in under 120 s.

## Rules for every agent on this repo
- Read `docs/JUNCTIONS.md` first: it defines every field and signature. Do not redefine them.
- Do not edit tests. Do not commit. Touch only the files named below.
- Anything that outlives one shell command runs under `~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- <cmd>`;
  never nohup/setsid/&/polling loops; a job is finished only when `~/.claude/scripts/job status <name>` says so.
- OCP (OpenCascade bindings) and cadquery are installed; import `cqshim` before `cadquery` (see tools/recon/cqshim.py).

## Check
`cd <repo> && timeout 900 python3 -m pytest -q tools/recon/tests/test_mesh_junctions.py`

## v2 (2026-09-22): the first version passed the synthetic tests and failed the corpus
`mesh_junctions.py` exists (738 lines) and passes the 5 synthetic tests, but on the 39 corpus parts, scored
against the exact blends of their accepted CAD: blend recall 16.8%, precision 0.1%, 4 crashes
(numpy.linalg.LinAlgError "Eigenvalues did not converge" in `_sor_axis`, parts 9, 11, 20 and polydryer).
Measured failure: OVER-SEGMENTATION. One real cylinder is split into many small cylinder regions, each tangent
to its neighbours, so each is counted as a blend: 136144 spurious `blend:cylinder|cylinder+cylinder|round`.
Real STLs are coarse (CAD-exported, few long thin triangles), unlike the test shapes' fine tessellation.
Required now, in addition to everything above:
- Merge adjacent regions that fit the SAME surface (same kind, axis within 1 degree and 0.5% of the diagonal,
  radius within 2%) before classifying junctions and blends. A blend is never between two regions of one surface.
- Never crash: a fit that fails (LinAlgError, degenerate region) makes that region `other`.
- New acceptance test `test_corpus_blends_match_the_accepted_cad`: blend recall >= 60% and precision >= 60%
  over every mechparts part with <= 30k triangles (truth in tools/recon/tests/data/blend_truth.json), each
  part under 120 s. The 5 synthetic tests must keep passing. You may rewrite mesh_junctions.py entirely.

## Check (v2)
`cd <repo> && timeout 1500 python3 -m pytest -q tools/recon/tests/test_mesh_junctions.py`
