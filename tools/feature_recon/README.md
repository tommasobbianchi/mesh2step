# feature_recon — macroscopic (feature-level) reconstruction prototypes

Rebuilds mechanical STL parts as feature models (extrusions, stepped levels, turned bodies, holes, slots,
fillets/chamfers measured from slices) instead of stitching triangle-level fits. Prototype scripts from the
2026-09-13 session; NOT yet wired into the mesh2step engine and NOT run against the cadbench corpus gate.

Acceptance for a part: FreeCAD reads the STEP as one valid solid with 0 invalid faces, volume within 1% of the mesh.
State on ~/corpora/mechparts (39 parts): 28 solved — see results/recon_summary.txt and RESUME.md (entries DH..FA).

| script | role |
|---|---|
| slice.py | STL loader, plane sections, loop tracing, circle fit |
| auto2d.py | 2.5D extrusion: mid-slice lines/arcs -> prism -> per-loop fillet/chamfer from slice area deficit |
| auto25g.py | stepped extrusion: levels along an axis, bisected boundaries, scale-relative tolerance |
| autorev.py | turned envelope (revolved radial profile) |
| features.py / featmap.py | connected feature patches -> plane / cylinder (hole or boss), half-patches merged |
| autorev_cut4.py | turned envelope minus flats, floor-bounded slots, holes |
| autoblock2.py | multi-axis block: silhouette base minus holes/slots/floors (in progress) |
| recon.sh | router: DeepSeek vision category + deterministic tests, FreeCAD validation, best build |
| freecad_check.py | FreeCAD round-trip validity check (snap FreeCAD needs files under ~/snap/freecad/common) |

Vision model: `opencode run --pure -m deepseek/deepseek-v4-flash-vision-exp "<question>" -f <image>` (question before -f).
Solved STEP outputs are kept in out/ (git-ignored by *.step).
