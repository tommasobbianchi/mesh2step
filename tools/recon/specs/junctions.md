# junctions — take a B-rep apart into junctions and blends (library, part 1)

## Create `tools/recon/junctions.py`.

## Required behaviour (acceptance test: `tools/recon/tests/test_junctions.py`, shapes in `tests/junction_shapes.py`)
1. `extract(step_path) -> {"junctions": [...], "blends": [...]}` — read the STEP with OCP (STEPControl_Reader).
   - One junction per edge shared by two DIFFERENT faces (skip seam edges, where a face meets itself, and
     degenerate edges). Fields exactly as docs/JUNCTIONS.md: a, b (sorted), curve, tangent, convex, angle, radius,
     coaxial, centre, length, plus `sig` = "a|b|curve|state".
   - Face kind from BRepAdaptor_Surface.GetType(); curve kind from BRepAdaptor_Curve.GetType().
   - Outward normals must respect face orientation (TopAbs_REVERSED flips the surface normal).
   - tangent: normals agree within 2 degrees at 5 samples along the edge. convex: material angle < 180 degrees
     (e.g. test a point just inside both faces near the edge with BRepClass3d_SolidClassifier, or use the sign of
     (nA x nB) . edge tangent with a consistent edge orientation — your choice, the tests decide).
   - A blend is a cylinder/cone/torus/sphere face tangent to two different neighbouring faces; fields blend,
     between, round, radius (cylinder radius / torus MINOR radius / sphere radius), centre, sig. round = the
     material is on the concave side of the blend surface (convex bulge); a fillet fills an inside corner.
2. CLI `junctions.py catalog <out.json> <step> [<step> ...]` -> {"parts": n, "signatures": {sig: {"count": int,
   "examples": [{"part": <file stem>, "centre": [...], "radius": r|null}, ... at most 5]}}}, junctions and blends
   together.

## Rules for every agent on this repo
- Read `docs/JUNCTIONS.md` first: it defines every field and signature. Do not redefine them.
- Do not edit tests. Do not commit. Touch only the files named below.
- Anything that outlives one shell command runs under `~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- <cmd>`;
  never nohup/setsid/&/polling loops; a job is finished only when `~/.claude/scripts/job status <name>` says so.
- OCP (OpenCascade bindings) and cadquery are installed; import `cqshim` before `cadquery` (see tools/recon/cqshim.py).

## Check
`cd <repo> && timeout 900 python3 -m pytest -q tools/recon/tests/test_junctions.py`
