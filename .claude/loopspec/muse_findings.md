## What I changed (all in `tools/feature_recon/scanbuild.py`, only file touched)
1. **Chain direction follows loop traversal** (`chain_edge`): cached wires were canonicalized by vertex-id, scrambling half the wires. Now the cached wire is rebuilt in caller order (a bare `Reversed()` was insufficient — `TopExp_Explorer` ignores the wire-level flag).
2. **`_face_normal` keyed on signed area** (`Mass<0`), not the orientation flag — ShapeFix on closed surfaces returns wire-reversed faces still marked FORWARD.
3. **Sphere caps via direct `MakeFace` first** (ShapeFix fallback): ShapeFix "repairs" UV orientation, which on a closed surface swaps material side. This fixed the volume killer: region 43/47 caps selected at 540/209 mm² were coming out as 8301/5740 mm² complements (volume 2× inverted).
4. **Radial majority vote for sphere orientation** (`_sphere_outward_ok`): mesh normal sums cancel on large caps.
5. **Topology guards** (`_bad_topology` → force-facet): multi-loop spheres, winding-0 sphere loops, plane loops that touch/cross (segment intersection — centroid tests looked clean on planes 1/5 yet both sewed unorientable).
6. **Sliver triage + remesh stage** in `build_until_valid`: micro-slivers dropped, border slivers absorbed into analytic neighbours, interior slivers kite-merged; resample-cover + `late_bad` final-solid feedback (attempt 8).
Verified along the way (measured, not theorised): tolerance sweeps (sew/ShapeFix precision/max) change nothing — the defect is combinatorial; mesh is watertight/manifold but bad regions contain sub-precision-area slivers (region 20: triangles down to 3e-4 mm²).
## Final check JSON (attempt 8/8, exit 1)
`solid false, valid false, free_edges 160, dv 0.1947, analytic 345 (inflated counter; true ~40)` — `bad_regions []`, `late_bad [5,22,52,305]`, `faceted 26`, `remeshed [1,5,22,43,52,305]`, volume 30376 vs 37720.
## What still fails
- **Attempt 8 diverged**: the `late_bad` nearest-centroid attribution misfires (region `305` is a phantom — no such region), over-faceting 26 regions and opening 160 free edges. The feedback loop is unstable as implemented.
- **Best state was attempt 7** (4/5 gates): `solid true, free_edges 0, analytic ✓, bad_regions []`, but `valid false` (7 faces invalid only on the final solid: 190 mm² cyl r58, 263 mm² torus r51, 8.7 mm² cyl r70 + 4 sliver facets — all missed by the sew-time check because unmodified faces skip the Modified map) and `volume dv 0.0313` (need <0.02).
- **Suggested next step** (needs attempts beyond budget): keep attempt-7 code, replace nearest-centroid attribution with surface-parameter matching for analytic faces (exact, no phantoms), feed only those back to facet; handle sliver-facet sources via the existing triage. Do not re-enable the centroid version.
Script done on 2026-09-30 11:22:46+02:00 [COMMAND_EXIT_CODE="0"]
