# Task: improve tools/feature_recon/regions.py (mesh region growing into CAD faces)

Repo: /home/tommaso/projects/mesh2step. Python 3 system interpreter (python3), numpy, OCP available.

## What the code does (read the file, do not trust this summary)
tools/feature_recon/regions.py groups STL triangles into CAD faces WITHOUT removing vertices:
1. cylinder seeds from tools/feature_recon/quads.py (coplanar triangle pairs, normal lines meeting on an axis), refit on vertices, grown;
2. planar regions grown from the largest triangle; small smooth regions are "held" as possible curved facets and restored as planes if nothing claims them and they stood alone;
3a. whole smooth components fitted as one cylinder / cone / sphere (fit_smooth);
3b. seeded growth on the rest: fit a 3-ring neighbourhood with fit_smooth or fit_revolution (line-complex torus fit), dry-grow each candidate, keep the larger.

## MEASURED FACTS (do not re-theorise these)
Command: cd tools/feature_recon; REGION_TOL=3e-4 python3 region_census.py normal
Current result: all three counts (planes, cylinders, other) exact on 82/103 CAD-sourced models (the *_recon models are excluded on purpose: their truth comes from an earlier reconstruction).
Remaining failures, truth [planes, cyl, other] vs got:
  L04_chamf_cube T[26,0,0] G[6,0,1]; L04_chamf_hex T[14,0,0] G[2,1,0]     (chamfer networks)
  L04_puck T[2,1,2] G[1,27,16] unassigned 15%                              (torus rims fragment into many small cylinders)
  L05_t_pipe T[4,4,0] G[4,0,0] unassigned 76%; L09_cross_block T[7,5,0] G[11,0,0] (cylinders cut by cross holes)
  L09_actuator_mount T[8,7,2] G[7,20,1]; L09_clamp T[9,8,0] G[6,8,0]; L09_crank_arm T[17,5,0] G[15,3,0]
  L08_angle_plate T[10,8,0] G[12,4,0]; L10_idler_bracket T[19,6,0] G[25,4,0]; L10_tool_holder T[15,16,0] G[15,12,0]
  L09_valve_body T[7,21,24] G[2,19,19]; clamp_half_a T[12,11,2] G[12,15,1]
On L05_t_pipe the leftover seed rings (13 facets) had normals nearly all parallel (|mean n . axis| ~ 0.99) before the uncentred-moment fix; vertices of its cylinders lie at radius 8.00 +- 0.01 and 15.00 +- 0.06.
REGION_TOL 1e-4 / 3e-4 / 1e-3 changed the exact count only 129/132/131 (all models), so tolerance is not the lever.

## Attempts already made and reverted or insufficient (one line each)
- fitting whole smooth components as one surface: blobs of several surfaces never fit (p9: 19k-triangle component).
- line-complex (Pottmann-Randrup) fit for every surface of revolution: axis arbitrary for cylinders/cones/spheres (multi-dim null space); regressed cones and spheres.
- triangle-count rule for held facets (<= 2, then <= 8): cone generator strips have 10+ coplanar triangles.
- boundary-length rule alone: regressed tori/sphere fans into planes; now OR-ed with the count rule; chamfers flip-flop between versions.
- dry-grow best-of-two candidates: did not fix L04_puck fragmentation.

## PREMISES FOUND FALSE
- "centred covariance of normals gives the cylinder axis": false on small arcs (picks the mean normal).
- "a 2-triangle plane is a curved facet": false for faces between tangent fillets.

## What to do
Read regions.py, quads.py, region_census.py and slice.py fully. Be sceptical of everything above except the measurements.
Improve region growing so the census exact count rises ABOVE 82/103 AND no model that is exact at baseline becomes non-exact.
First run the census once and save the baseline list of exact models. Cite file:line for each change you make and why.

## Limits
- Modify ONLY tools/feature_recon/regions.py. Do not touch quads.py, region_census.py, src/, tests/, or any corpus/truth file.
- No git commands. No dependency installs.
- Anything that runs longer than a couple of minutes must be launched with
  ~/.claude/skills/watchjob/scripts/watchjob.sh <name> -- '<command>' and checked with ~/.claude/scripts/job status <name>;
  never nohup, setsid, a bare background ampersand, or pgrep. (The census itself takes about 1-2 minutes and may run in the foreground.)
- Report at the end: baseline vs final exact count, the list of models that changed status, and file:line of each change.
