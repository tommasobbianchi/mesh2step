# Decimation algorithms vs. mesh2step (study, 2026-09-13)

Question (Tommaso): can decimation, and the recursive merging of planar triangles into ever larger
polygons, cut large mechanical STLs by ~10^3 and help recognition?

## The families

| family | how it works | keeps exact geometry? |
|---|---|---|
| Vertex removal (Schroeder, Zarge, Lorensen 1992; vtkDecimatePro) | repeated passes, remove a vertex whose distance to its neighbours' average plane is below a limit, re-triangulate the star-shaped hole by recursive loop splitting; feature angle marks edges/corners that must stay | yes at error 0 on planar regions |
| Edge collapse, QEM (Garland-Heckbert 1997) | per-vertex quadric = sum of squared distances to incident planes; collapse the cheapest edge, place the vertex at the quadric minimum; boundary kept with perpendicular penalty planes | no: an error budget moves vertices |
| Edge collapse, Lindstrom-Turk (CGAL default) | memoryless: placement solves 3 constraints in priority order (boundary shape, total volume, local volume) | no |
| Vertex clustering (Rossignac-Borrel) | grid cells collapse to one vertex | no, topology breaks |
| VSA (Cohen-Steiner, Alliez, Desbrun 2004; CGAL Surface_mesh_approximation) | k planar proxies; Lloyd loop: assign faces to nearest proxy (L2,1 = normal deviation), refit proxies; seeding adds proxies where error is largest; merge/split/teleport; output mesh from region anchors + recursive chord subdivision | approximates by design |
| Hybrid VSA (Wu, Kobbelt 2005) | VSA with plane, sphere, cylinder and rolling-ball-blend proxies | a CAD primitive partition |
| Hierarchical fitting primitives (Attene, Falcidieno, Spagnuolo 2006; EfPiSoft) | every triangle starts as a cluster; repeatedly merge the adjacent pair best fitted by a plane, sphere or cylinder; builds a binary tree, 100k faces in ~8 s | a CAD primitive partition |

## Measured on the user's parts (tools/feature_recon/decimate_probe.py)

exact-planar = vtkDecimatePro, absolute error 1e-6 x diagonal, topology + boundaries preserved (the
planar recursive merge). qem-10% = fast_simplification (Garland-Heckbert) to 10%.
quad-cyl = cylinders quads.py still finds.

| part | input tris / quad-cyl | exact-planar | qem-10% |
|---|---|---|---|
| 9 | 46,104 / 77 | 44,658 (-3.1%) / 70 | 22,228 / 60, dV -0.79% |
| 32 | 65,468 / 19 | 63,510 (-3.0%) / 19 | 6,546 / **2** |
| 33 | 105,434 / 121 | 94,204 (-10.7%) / 110 | 12,362 / 52, dV -0.69% |
| 12 | 164,996 / 30 | 150,610 (-8.7%) / 31 | 16,498 / 28, invents a R~4.75 series |

## Findings

1. CAD exporters already triangulate planar faces minimally. The triangles are in the curved strips,
   so exact planar merging removes 3-11%, not 10^3.
2. Error-budget decimation (QEM) destroys exactly what recognition needs: cylinder strips collapse
   into facets (p32 19 -> 2) or re-tessellate into false radii (p12).
3. Even error ~0 vertex removal disturbs rim vertices and costs a few quad cylinders (p9 77 -> 70):
   decimation must never run before recognition.
4. The 10^3 reduction is real, but it comes from representing a region by its primitive, not by
   fewer triangles: the verified feature builds are p32 65,468 tris -> 18 faces (3,637x),
   p33 3,195x, p12 2,230x, median 344x over 29 parts.
5. The recursive-merge idea is exactly right as a CLUSTERING procedure: Attene's hierarchical fitting
   primitives IS recursive merging of adjacent regions, generalised from planes to spheres and
   cylinders, with the fitting error deciding each merge. VSA/hybrid VSA is the global-optimisation
   variant.

## What to take into mesh2step

- Recursive planar merging as REGION GROWING on the mesh (no vertex removed): merge adjacent
  coplanar triangles, then adjacent regions, ordered by fit error. Output = planar regions with
  their boundary loops, which become planar B-rep faces directly.
- Same loop for curved regions with a primitive fit per merge (Attene): quads.py already supplies
  the seeds (quad strips, normal-line axis/centre). A merge is accepted if the union still fits
  one plane / cylinder / cone / sphere / torus within the mesh deflection.
- Use the region partition (not a decimated mesh) as the recognition input and as the support
  signal for the feature builders.
- Keep QEM only for previews/rendering, never on the conversion path.

## Sources

- Schroeder, Zarge, Lorensen, "Decimation of triangle meshes", SIGGRAPH 1992 — https://dl.acm.org/doi/10.1145/133994.134010
- Garland, Heckbert, "Surface simplification using quadric error metrics", 1997 — https://www.researchgate.net/publication/2417323_Surface_Simplification_Using_Quadric_Error_Metrics
- CGAL Triangulated Surface Mesh Simplification — https://doc.cgal.org/latest/Surface_mesh_simplification/index.html
- CGAL Triangulated Surface Mesh Approximation (VSA) — https://doc.cgal.org/latest/Surface_mesh_approximation/index.html
- Wu, Kobbelt, "Structure recovery via hybrid variational surface approximation", CGF 2005 — https://onlinelibrary.wiley.com/doi/10.1111/j.1467-8659.2005.00852.x
- Attene, Falcidieno, Spagnuolo, "Hierarchical mesh segmentation based on fitting primitives", Visual Computer 2006 — https://link.springer.com/article/10.1007/s00371-006-0375-x
- EfPiSoft — https://efpisoft.sourceforge.net/
