# recon-tools — the toolbox: one exact construction per junction family

## Create `tools/recon/recon_tools.py` (programs will use it as `rt`).

## Required behaviour (acceptance test: `tools/recon/tests/test_recon_tools.py`)
Every function takes and returns a cadquery Workplane holding one solid, and must produce ONLY exact analytic
faces (plane/cylinder/cone/torus/sphere) that stay analytic after STEP export + `canon.canonicalize_step`
(tools/recon/canon.py rewrites revolved circles as tori; a spindle torus R < r is legitimate, see canon.py).
Build blends explicitly from primitives (cq.Solid.makeTorus / makeCylinder / makeCone and booleans) whenever
cadquery's fillet() would produce B-splines or revolutions. `plane`/`base`/`top`/`wall` is a cq.Plane whose
origin lies on the face and whose normal points OUT of the material; `center` is in that plane's local x/y.
- `boss(solid, base, center, radius, height, base_fillet=0.0, top_round=0.0)`: cylinder added on the face;
  concave torus fillet at its foot; convex torus round at its top edge (top_round < radius; R may be < r).
- `hole(solid, top, center, radius, depth=None, mouth_chamfer=0.0, mouth_round=0.0)`: through when depth is None.
- `counterbore(solid, top, center, radius, bore_radius, bore_depth, depth=None)`.
- `ring_fillet(solid, wall, center, radius, fillet, convex=False)`: concave torus fillet where an existing
  cylinder of `radius` (axis = wall normal through center) meets the wall; convex=True rounds a hole's mouth.
- `edge_round(solid, selector, radius)`: cadquery fillet on selected edges; raise ValueError naming the edge
  if any resulting face is not analytic.
- Each function has a docstring (> 80 chars) with its parameters: the model reads them in its brief.

## Rules for every agent on this repo
- Read `docs/JUNCTIONS.md` first: it defines every field and signature. Do not redefine them.
- Do not edit tests. Do not commit. Touch only the files named below.
- Anything that outlives one shell command runs under `~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- <cmd>`;
  never nohup/setsid/&/polling loops; a job is finished only when `~/.claude/scripts/job status <name>` says so.
- OCP (OpenCascade bindings) and cadquery are installed; import `cqshim` before `cadquery` (see tools/recon/cqshim.py).

## Check
`cd <repo> && timeout 900 python3 -m pytest -q tools/recon/tests/test_recon_tools.py`
