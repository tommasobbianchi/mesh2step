"""Benchmark: mesh2step vs. a FreeCAD-makeShapeFromMesh-equivalent OCCT pipeline
(see freecad_equivalent.py for why it's a reimplementation, not the FreeCAD app).

Usage:
    python3 benchmark/run_benchmark.py [mesh1.stl mesh2.stl ...]

With no arguments, benchmarks the bundled test fixtures plus (if present) a large
real-world mesh from this host, so 100k+ triangle behavior is actually exercised.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mesh2step import io_mesh, dedup, brep_build, step_export  # noqa: E402
from freecad_equivalent import build_freecad_equivalent  # noqa: E402

DEFAULT_MESHES = [
    Path(__file__).parent.parent / "tests" / "data" / "bucket.stl",
    Path(__file__).parent.parent / "tests" / "data" / "real_mesh_bottom_bracket.stl",
]
LARGE_MESH = Path("/home/tommaso/projects/Core-R-Theta-4-Axis-Printer/stl files/z carriage front.stl")


def run_one(path: Path, tolerance: float = 0.01):
    print(f"\n=== {path.name} ===")
    verts, tris = io_mesh.load_mesh(path)
    print(f"input: {len(tris):,} triangles, {len(verts):,} raw vertices")

    # mesh2step
    t0 = time.perf_counter()
    dd = dedup.dedup_and_clean(verts, tris, tolerance)
    build = brep_build.build_faceted_shape(dd.verts, dd.tris)
    t_mesh2step = time.perf_counter() - t0
    out_step = Path("/tmp") / (path.stem + "_mesh2step.step")
    t0 = time.perf_counter()
    step_export.write_step(build.shape, out_step)
    t_mesh2step_write = time.perf_counter() - t0

    # freecad-equivalent
    fc = build_freecad_equivalent(verts, tris, tolerance)

    print(
        f"{'':22s} {'mesh2step (shared-topology)':32s} {'FreeCAD-equivalent (sew-based)':32s}"
    )
    print(
        f"{'faces built':22s} {build.n_faces_built:<32,} {fc['n_faces_built']:<32,}"
    )
    print(
        f"{'faces failed':22s} {build.n_faces_failed:<32,} {fc['n_faces_failed']:<32,}"
    )
    print(
        f"{'watertight/solid':22s} {str(build.is_solid):<32} {str(fc['is_solid']):<32}"
    )
    vol_m2s = f"{build.volume:.4f}" if build.volume else "n/a"
    vol_fc = f"{fc['volume']:.4f}" if fc["volume"] else "n/a"
    print(f"{'volume':22s} {vol_m2s:<32} {vol_fc:<32}")
    print(
        f"{'build time (s)':22s} {t_mesh2step:<32.3f} {fc['t_build_s']:<32.3f}  (+ sew: {fc['t_sew_s']:.3f}s)"
    )
    print(
        f"{'total time (s)':22s} {(t_mesh2step + t_mesh2step_write):<32.3f} {fc['t_total_s']:<32.3f}  "
        f"(mesh2step also wrote STEP; FreeCAD-equivalent build/sew time only, no writer, for a build-time-only comparison)"
    )

    speedup = fc["t_total_s"] / t_mesh2step if t_mesh2step > 0 else float("inf")
    print(f"{'speedup (build)':22s} {speedup:.2f}x")


def main():
    meshes = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else list(DEFAULT_MESHES)
    if not sys.argv[1:] and LARGE_MESH.exists():
        meshes.append(LARGE_MESH)

    for m in meshes:
        if not m.exists():
            print(f"skipping missing file: {m}")
            continue
        run_one(m)


if __name__ == "__main__":
    main()
