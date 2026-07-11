# Benchmark results

Run on nativedev (no GPU used -- this is a pure-CPU, per-triangle Python+OCCT
construction path; see SELECTION.md for why GPU wasn't pursued). Command:
`python3 benchmark/run_benchmark.py <mesh>`.

`FreeCAD-equivalent` = `benchmark/freecad_equivalent.py`, a from-source
reimplementation of FreeCAD's `makeShapeFromMesh` construction strategy on the same
OCCT kernel this project uses -- **not** the FreeCAD application itself (unavailable
on this host: no conda for `pythonocc-core`, no passwordless `sudo` for
`apt install freecad`). See SELECTION.md and `freecad_equivalent.py`'s docstring.

| mesh | triangles | mesh2step build | mesh2step total (+write) | FC-equiv build | FC-equiv sew | FC-equiv total | volumes match | speedup |
|---|---:|---:|---:|---:|---:|---:|:---:|---:|
| `bucket.stl` | 11,286 | 1.67s | 4.44s | 1.46s | 2.84s | 4.30s | yes (221405.2541 both) | 2.58x |
| `real_mesh_bottom_bracket.stl` | 62,028 | 9.34s | 25.42s | 8.32s | 19.43s | 27.75s | yes (33253.3756 both) | 2.97x |
| `z carriage front.stl` | 331,660 | 50.22s | 140.88s | 45.68s | 114.92s | 160.60s | yes (79731.4264 both) | 3.20x |

("speedup" = FC-equivalent total (build+sew) / mesh2step build-only -- the fair
comparison for the architectural claim: shared-topology construction reaches an
equivalent watertight solid without ever needing a sewing pass at all. mesh2step's
own *total* column additionally includes writing the STEP file, which the
FreeCAD-equivalent column deliberately excludes for a build-time-only comparison --
see `run_benchmark.py`.)

## What this shows

- **Correctness parity**: both approaches produce the same watertight solid with
  identical (to 4 decimal places) integrated volume on all three meshes, including
  the 331,660-triangle case -- the two constructions are not just architecturally
  different, they're geometrically equivalent when they succeed.
- **The gap widens with scale**: FreeCAD-equivalent's raw per-triangle face
  construction is actually *slightly faster* than mesh2step's (mesh2step pays a
  Python dict-cache-lookup cost per edge/vertex that the naive approach skips) --
  but the mandatory sewing pass it then needs to reconstruct shared topology grows
  from 2.84s (11k tri) to 19.43s (62k tri, 6.8x for 5.5x triangles) to 114.92s (332k
  tri, 5.9x for 5.4x more triangles) -- consistently super-linear, and by the
  332k-triangle mesh it is more than double mesh2step's entire build time. This is
  the concrete cost of the anti-pattern SELECTION.md calls out in `OCC-CSG` and
  FreeCAD's own core routine: paying at sew time for topology sharing that
  construction-time caching gets for free.
- **Robustness at 100k+ triangles, honestly reported**: 331,660 triangles converted
  and wrote a valid 149+ MB STEP file without choking, in 140.88s wall-clock. See
  README's "Known limits" for the corresponding finding that *reading* dense faceted
  STEP output back (as any downstream CAD tool would) is far slower than writing it
  -- a real, load-bearing limitation of the faceted approach at this scale, not
  hidden in this benchmark.
- `faces_built` differed by 32 on the 331,660-triangle mesh (331,628 for mesh2step
  vs. 331,660 for FreeCAD-equivalent, which does no degenerate-triangle filtering at
  all) -- and the two volumes still matched to 4 decimal places, a real-data
  confirmation that the 32 rejected triangles were genuinely negligible.
