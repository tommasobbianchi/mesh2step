# Task: make tools/feature_recon/scanbuild.py produce a VALID solid on the mechpart scan

## Goal (observable)
`python3 tools/feature_recon/check_scanbuild.py` exits 0. It runs scanbuild.py on runs/scan/mechpart.clean.stl +
runs/scan/mechpart.labels.npz and requires ALL of: solid true, valid true (BRepCheck_Analyzer), free_edges 0,
|volume| within 2 % of the mesh volume (37720.2 mm3), and >= 30 analytic faces. Current output: solid true, valid
FALSE, free_edges 0, volume off by 108 %, 59 analytic faces.

## Scope
- You may edit ONLY `tools/feature_recon/scanbuild.py`.
- Do NOT edit check_scanbuild.py, denoise.py, edgebuild.py, or anything under runs/. Do not change the gates.
- No git commits, no pushes. Python is `python3` (OCP, numpy, trimesh, scipy installed).
- Any command that runs longer than 60 s: `~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- '<cmd> > <log> 2>&1'`
  then `~/.claude/scripts/job status <name>`. Never pgrep/ps. One scanbuild run takes about 40-120 s.

## What scanbuild.py does (read it first)
One face per region: the region's fitted analytic surface (plane/cylinder/cone/sphere/torus, from the npz "surf"),
bounded by the region's border loops in the cleaned mesh as polyline edges shared between neighbouring regions; each
face built in a forked child (OCCT segfaults on some); faces sewn (BRepBuilderAPI_Sewing), ShapeFix_Shape on the whole
sewn shell, largest shell -> ShapeFix_Shell -> MakeSolid -> ShapeFix_Solid. Triangles in no region are single planar
faces. `build_until_valid` rebuilds regions whose face is invalid after sewing from their triangles, up to 3 passes.

## Measured facts (do not re-theorise; re-measure if in doubt)
- One build() pass: 918 faces, 0 free edges, one shell; 7 regions have faces INVALID after sewing: regions
  [1, 5, 20, 46, 49, 59, 60]; BRepCheck statuses 6 x BRepCheck_UnorientableShape, 1 x BRepCheck_InvalidImbricationOfWires.
  Regions 1 and 5 are planes with 6 boundary loops; 20 and 46 are spheres (46 has 2 loops).
- Replacing those regions by their triangles cascades: after 3 passes 11 regions faceted, 2 still invalid, |volume|
  78652 vs mesh 37720 (faces overlap or cover the wrong side).
- A face's area vs its region's mesh area is already checked (both wire orientations tried, 25 % limit).

## Already tried and FAILED (do not repeat)
1. Checking face validity before sewing and faceting failures: 69 regions rejected, almost everything faceted.
2. ShapeFix_Shape per face before sewing: rebuilt the edges, sewing then left 677 free edges.
3. Orienting planar wires by signed area (outer CCW about the face normal, holes CW): the same 7 regions stay invalid.
4. B-spline chain edges (GeomAPI_PointsToBSpline): ends missed the corner vertices, wires did not close.

## Hints (unverified; measure before believing)
- BRepCheck_UnorientableShape on a face with several wires often means an inner wire is not inside the outer one in the
  surface's parameter space, or two loops touch at a vertex (a region pinched at one vertex gives loops sharing it).
  `loops()` may split a pinched boundary wrongly.
- The volume can be wrong even when faces are individually fine, if some face covers the complement of its region on a
  closed surface (sphere, torus) or its normal points inward.
- Splitting a problematic multi-loop region into simpler faces (e.g. one face per connected component after cutting
  the pinch) is allowed if the gates still pass.

## Loop until green
Edit scanbuild.py -> run `python3 tools/feature_recon/check_scanbuild.py` -> read its JSON (gates, dv, analytic,
result.bad_regions, result.bad_why) -> fix the root cause -> repeat. Stop when it exits 0, or after 8 attempts; then
report exactly what you changed, the final check JSON, and what still fails.
