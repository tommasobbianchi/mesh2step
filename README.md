# mesh2step

Live web app: **https://mesh2step.nativemedica.it/**
(origin: https://nativedev.tail7d3518.ts.net/mesh2step/ — see `webapp/deploy/README.md`)

Convert a triangle mesh (STL / OBJ / 3MF / PLY) into a B-Rep solid, exported as STEP
(AP203/AP214/AP242). Conversion runs through the native **stl2step** C++ engine (see
`refs/stl2step/`); the default **verbatim** mode builds one planar B-Rep face per
input triangle, with topology (vertices, edges) genuinely shared across triangles from
the moment they're built -- not reconstructed afterward by a sewing pass. The optional
`--engine trueform` mode recovers planes and cylinders analytically. Both are
geometry-preserving: no primitive recognition beyond what trueform does, exact fidelity
to the input mesh.

See [`SELECTION.md`](SELECTION.md) for the comparison of four reference
implementations this design is synthesized from, and why. tl;dr: none of the four
references could be extended cleanly -- one can't emit solids at all, one can't emit
pure faceted output, one wastes its own indexed mesh data on a build-then-sew
anti-pattern, and FreeCAD's own core routine is the origin of a well-documented
tolerance-confusion bug (issue #20455) this design sidesteps by construction.

## Install

```sh
pip install -e ".[test]"
```

Kernel: [`cadquery-ocp`](https://pypi.org/project/cadquery-ocp/) (`OCP`), a
pip-installable OCCT 7.8 binding, substituted for `pythonocc-core` (`OCC.Core`) which
has no PyPI wheel and requires conda -- see SELECTION.md. The two bindings wrap the
same OpenCASCADE kernel with near-identical class names.

## Usage

```sh
mesh2step part.stl                              # -> part.step, faceted, AP214
mesh2step part.stl --engine trueform            # analytic plane/cylinder recovery
mesh2step part.stl --repair solidify            # pymeshfix reconstruction (mesh preprocessing)
mesh2step part.stl --merge-coplanar             # merge co-planar faces, default 5deg
mesh2step part.stl --merge-coplanar 1.0         # explicit angular tolerance
mesh2step part.stl --format ap242
mesh2step ./parts_dir/ --output-dir ./step_out/  # batch mode: every supported file in a folder
```

The native engine does its own vertex welding (exact-duplicate weld plus an optional
coplanar merge via `--unify-angle` / `--merge-coplanar`), so the Python pipeline's
`--tolerance` dedup flag no longer exists. Every run prints the engine's structured
result; pass `--quiet` for just the `RESULT {json}` line.

## The tolerance model

The native engine has no per-cell dedup tolerance. Vertices are welded exactly, and
coplanar merging is governed solely by `--unify-angle` (alias `--merge-coplanar`, in
degrees); with no angle given the verbatim output keeps one face per triangle.

## Watertight vs. open, honestly

Building the edge cache costs nothing extra to also count edge usage: every shared
mesh edge is touched by exactly the triangles that reference it. Once all faces are
built:

- every edge used by **exactly 2** triangles, and `BRepBuilderAPI_MakeSolid` produces
  a shape with a computable, non-zero volume ⇒ **`TopoDS_Solid`**
- otherwise ⇒ **`TopoDS_Shell`**, reported with boundary-edge and non-manifold-edge
  counts so the *reason* it isn't a solid is visible, not just the fact.

This tool never wraps a non-watertight shell as a fake solid to make the output look
cleaner than the input actually is.

## `--merge-coplanar`

Off by default. Faceted mode (default) is exact and geometry-preserving: face count
equals surviving triangle count. `--merge-coplanar [ANGLE_DEG]` runs
`ShapeUpgrade_UnifySameDomain` as a distinct, explicit post-process stage that merges
adjacent co-planar triangles into single faces, trading exactness for a much smaller
face count (a 12-triangle cube collapses to 6 faces). The two modes are never
conflated -- see SELECTION.md's critique of `2STEP-Converter`, which always applies
this step and has no pure-faceted mode at all.

## Mesh repair

Off by default. `--repair weld` runs a trimesh-backed surgery pass before vertex
dedup: it merges coincident/split vertices, drops duplicate faces, and fixes
inconsistent winding. `--repair fill` additionally attempts to close holes
(`trimesh.fill_holes`, best-effort). `--repair solidify` uses
[pymeshfix](https://github.com/pyamg/pymeshfix) to reconstruct a watertight
manifold when weld/fill cannot -- this is reconstructive (geometry may change)
and requires the optional `[repair]` extra (`pip install mesh2step[repair]`).
Like `--merge-coplanar`, repair is an explicit opt-in stage and runs after load
but before dedup, so dedup's canonical `round(v/tol)` merge still applies
afterward. The result is reported honestly: if the mesh remains non-watertight
after repair, it is exported as an open shell like any other non-watertight
input.

## Select &amp; cut

Off by default. Cuts are centroid-mask based (no new vertices, exact faceted
fidelity preserved) and applied before repair in the pipeline order:
load &#8594; cut &#8594; repair &#8594; dedup &#8594; build &#8594; write.
Available operations:

- **box**: keep (or discard) triangles whose centroids fall inside a min/max box.
- **plane**: keep triangles on one side of an axis-aligned plane.
- **lasso**: freehand selection in the web viewer via a projector matrix.
- **largest**: retain only the largest connected component.
- **component**: interactive component picker (web UI only) — split into connected
  components, click a colored part to select it, then Delete selected or Keep only
  selected. Replaces auto keep-largest in the web UI.

CLI: `--cut-largest` or `--cut-json path/to/ops.json`. In the web UI, use the
Select &amp; cut panel; each cut can be previewed before conversion with
`/api/edit` (returns the cut mesh as STL).

## Scope limits

- One input file = one output body (one shell/solid). Multiple disconnected islands
  within a single file are not detected or split; see `brep_build._count_connected_shells`.
- No hole-filling, no self-intersection repair, no color/material/assembly-hierarchy
  handling -- same limits every reference tool in SELECTION.md documents for itself.
- Large STEP writes are dominated by OCCT's own `STEPControl_Writer`/AP214 entity
  serialization, not by this tool's own logic; see `benchmark/`.
- **Faceted output does not read back fast at high triangle counts.** A real
  62,028-triangle mesh built and wrote its STEP file in 26s (9.4s build + 16.5s
  write, 149 MB), but re-parsing that same file with OCCT's `STEPControl_Reader`
  had not completed after 300s in isolated testing. Faceted mode is one
  `ADVANCED_FACE` (+ its own `PLANE`, edges, curves) per surviving triangle by
  design -- that's the whole point of "exact, no fitting" -- but it means the
  *reader* side (this tool's own writer is fine; any downstream CAD tool opening the
  file pays this cost) scales far worse than the writer for dense faceted meshes.
  `--merge-coplanar`, or decimating the mesh before conversion, are the mitigations
  if the output needs to be reopened quickly. `tests/test_real_scan.py` documents
  this and skips the read-back round trip above 20,000 faces accordingly.

## Tests

```sh
pytest tests/ -v
```

`tests/test_native.py` -- the native engine contract: verbatim/trueform conversion,
the CLI `RESULT` line and exit codes, and a guard that `import mesh2step` no longer
pulls in the deleted Python refit engine.

`tests/test_real_scan.py` -- two real, dense meshes (see `tests/data/README.md`):
`bucket.stl` (11,286 triangles) and `real_mesh_bottom_bracket.stl` (62,028 triangles,
a real mechanical CAD part). Same round-trip volume check at a looser (1e-3) relative
tolerance appropriate for a much larger entity count.

## Benchmark

```sh
python3 benchmark/run_benchmark.py
```

Compares this tool's shared-topology-by-construction build path against
`benchmark/freecad_equivalent.py`, a from-source reimplementation of FreeCAD's
`Part.Shape.makeShapeFromMesh` construction strategy (fresh per-triangle vertices +
`BRepBuilderAPI_Sewing`) on the **same OCCT kernel**, so the comparison isolates the
one architectural difference this project claims to fix rather than conflating it
with an OCCT-version or binding difference. This host has no `conda`/`mamba` (no pip
wheel for `pythonocc-core`) and no passwordless `sudo` (no `apt install freecad`), so
a real FreeCAD comparison wasn't available -- see `benchmark/freecad_equivalent.py`'s
docstring and SELECTION.md for the full reasoning. Treat the benchmark as measuring
"shared-construction vs. build-then-sew," not as an authoritative FreeCAD-the-app
number.

Results across 11k / 62k / 332k-triangle real meshes (the last comfortably inside the
task's 100k-1M range) are recorded in [`benchmark/results.md`](benchmark/results.md):
2.6x-3.2x faster than the sew-based approach at reaching an equivalent watertight
solid, with the gap widening super-linearly as triangle count grows, and identical
(to 4 decimal places) integrated volume on every mesh tested.

## License

MIT — see [`LICENSE`](LICENSE).

The two test meshes in `tests/data/` are third-party material and keep their own
terms; see [`tests/data/README.md`](tests/data/README.md) for provenance. The
optional `[repair]` extra pulls in `pymeshfix` (GPL), which is imported lazily and
never distributed with this package — the core install has no copyleft dependency.
