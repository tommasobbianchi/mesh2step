import argparse
import sys
import time
from pathlib import Path

from .convert import convert_file
from .io_mesh import SUPPORTED_EXTENSIONS

DEFAULT_MERGE_ANGLE_DEG = 5.0


def _fmt_bool(b) -> str:
    return "yes" if b else "no"


def _log_stats(stats, file=sys.stdout) -> None:
    degenerate = stats.n_degenerate_collapsed + stats.n_degenerate_zero_area
    print(f"  {stats.input_path}", file=file)
    if stats.error:
        print(f"    FAILED: {stats.error}  ({stats.t_total_s:.2f}s)", file=file)
        return
    print(
        f"    triangles in={stats.n_input_tris:,} kept={stats.n_kept_tris:,} "
        f"degenerate_skipped={degenerate:,}  verts in={stats.n_input_verts:,} "
        f"unique={stats.n_unique_verts:,}",
        file=file,
    )
    print(
        f"    faces_built={stats.n_faces_built:,} faces_failed={stats.n_faces_failed:,} "
        f"boundary_edges={stats.n_boundary_edges:,} nonmanifold_edges={stats.n_nonmanifold_edges:,}",
        file=file,
    )
    solid_note = f" volume={stats.volume:.6g}" if stats.volume is not None else ""
    print(
        f"    watertight={_fmt_bool(stats.watertight)} solid={_fmt_bool(stats.is_solid)}{solid_note}",
        file=file,
    )
    if stats.n_faces_after_merge is not None:
        print(
            f"    merge-coplanar: {stats.n_faces_before_merge:,} -> {stats.n_faces_after_merge:,} faces "
            f"(angle={stats.merge_coplanar_angle_deg}deg)",
            file=file,
        )
    print(
        f"    wrote {stats.output_path} ({stats.output_size_bytes:,} bytes, schema={stats.schema})",
        file=file,
    )
    print(
        f"    time: load={stats.t_load_s:.2f}s dedup={stats.t_dedup_s:.2f}s "
        f"build={stats.t_build_s:.2f}s merge={stats.t_merge_s:.2f}s write={stats.t_write_s:.2f}s "
        f"total={stats.t_total_s:.2f}s",
        file=file,
    )


def _default_output(input_path: Path, output_dir: Path | None) -> Path:
    stem = input_path.with_suffix(".step").name
    return (output_dir / stem) if output_dir else input_path.with_suffix(".step")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mesh2step",
        description="Convert a triangle mesh (STL/OBJ/3MF/PLY) to a faceted B-Rep STEP file.",
    )
    p.add_argument("input", help="input mesh file, or a directory for batch mode")
    p.add_argument("-o", "--output", help="output .step path (single-file mode only)")
    p.add_argument(
        "--output-dir",
        help="directory to write outputs into (batch mode, or single-file with -o omitted)",
    )
    p.add_argument(
        "--tolerance",
        type=float,
        default=0.01,
        help="vertex dedup / degenerate-triangle quantization tolerance, in input units (default: 0.01)",
    )
    p.add_argument(
        "--merge-coplanar",
        nargs="?",
        type=float,
        const=DEFAULT_MERGE_ANGLE_DEG,
        default=None,
        metavar="ANGLE_DEG",
        help=(
            "off by default. When given, merges adjacent co-planar triangles into single "
            f"faces using this angular tolerance in degrees (default if no value given: "
            f"{DEFAULT_MERGE_ANGLE_DEG})."
        ),
    )
    p.add_argument(
        "--merge-coplanar-linear-tol",
        type=float,
        default=None,
        metavar="TOL",
        help="linear tolerance for --merge-coplanar; defaults to --tolerance (see README)",
    )
    p.add_argument(
        "--format",
        choices=["ap203", "ap214", "ap242"],
        default="ap214",
        help="STEP schema (default: ap214)",
    )
    return p


def _iter_batch_inputs(input_dir: Path):
    for path in sorted(input_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    output_dir = Path(args.output_dir) if args.output_dir else None

    if not input_path.exists():
        print(f"error: {input_path} does not exist", file=sys.stderr)
        return 1

    if input_path.is_dir():
        files = list(_iter_batch_inputs(input_path))
        if not files:
            print(f"error: no supported mesh files ({sorted(SUPPORTED_EXTENSIONS)}) in {input_path}", file=sys.stderr)
            return 1
        print(f"batch mode: {len(files)} file(s) in {input_path}")
        t_batch = time.perf_counter()
        n_ok = n_fail = 0
        for f in files:
            out = _default_output(f, output_dir)
            stats = convert_file(
                f,
                out,
                tolerance=args.tolerance,
                merge_coplanar_angle=args.merge_coplanar,
                merge_coplanar_linear_tol=args.merge_coplanar_linear_tol,
                schema=args.format,
            )
            _log_stats(stats)
            if stats.error:
                n_fail += 1
            else:
                n_ok += 1
        print(f"batch done: {n_ok} ok, {n_fail} failed, {time.perf_counter() - t_batch:.2f}s total")
        return 1 if n_fail else 0

    output_path = Path(args.output) if args.output else _default_output(input_path, output_dir)
    stats = convert_file(
        input_path,
        output_path,
        tolerance=args.tolerance,
        merge_coplanar_angle=args.merge_coplanar,
        merge_coplanar_linear_tol=args.merge_coplanar_linear_tol,
        schema=args.format,
    )
    _log_stats(stats)
    return 1 if stats.error else 0


if __name__ == "__main__":
    sys.exit(main())
