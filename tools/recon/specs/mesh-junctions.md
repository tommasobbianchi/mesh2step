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
