import argparse
import sys
import tempfile
import time
from pathlib import Path

import trimesh

from .cut import apply_cuts, load_cut_ops
from .io_mesh import SUPPORTED_EXTENSIONS, load_mesh
from .native import convert_native
from .result import ParityResult, emit_result

DEFAULT_MERGE_ANGLE_DEG = 5.0


def _fmt_bool(b) -> str:
    return "yes" if b else "no"


def _log_verbatim(res, file=sys.stdout) -> None:
    if not res.ok:
        print(f"  FAILED: {res.error}", file=file)
        return
    print(f"  {res.input}", file=file)
    print(
        f"    triangles={res.triangles:,} vertices={res.vertices:,} "
        f"components={res.components} solids={res.solids} open_shells={res.open_shells}",
        file=file,
    )
    print(
        f"    faces {res.faces_before_unify:,} -> {res.faces_after_unify:,} "
        f"watertight={_fmt_bool(res.watertight)} volume={res.mesh_volume_mm3:.6f}mm^3",
        file=file,
    )
    print(f"    wrote {res.output} ({res.seconds:.2f}s)", file=file)


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
        "--repair",
        choices=["weld", "fill", "solidify"],
        default=None,
        help=(
            'off by default. "weld" = merge coincident vertices + drop duplicate faces '
            '+ fix winding; "fill" = also fill holes (best-effort); '
            '"solidify" = pymeshfix reconstruction (requires pymeshfix). '
            "Runs as mesh preprocessing before the native conversion."
        ),
    )
    p.add_argument(
        "--cut-largest",
        action="store_true",
        help="keep only the largest connected component of the mesh",
    )
    p.add_argument(
        "--cut-json",
        type=Path,
        default=None,
        metavar="PATH",
        help="path to a JSON file containing a list of cut operations",
    )
    p.add_argument(
        "--engine",
        choices=["verbatim", "trueform"],
        default="verbatim",
        help="conversion engine: verbatim (default) or trueform (analytic planar refit)",
    )
    p.add_argument(
        "--format",
        choices=["ap203", "ap214", "ap242"],
        default="ap214",
        help="STEP schema (default: ap214)",
    )
    p.add_argument(
        "--unify-angle",
        type=float,
        default=None,
        metavar="DEG",
        help="coplanar-merge angle in degrees (off by default)",
    )
    p.add_argument(
        "--merge-coplanar",
        nargs="?",
        type=float,
        const=DEFAULT_MERGE_ANGLE_DEG,
        default=None,
        metavar="ANGLE_DEG",
        help=(
            "alias of --unify-angle: merge adjacent co-planar triangles into single "
            f"faces using this angular tolerance in degrees (default if no value given: "
            f"{DEFAULT_MERGE_ANGLE_DEG})."
        ),
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="suppress the human-readable stats block; print only the RESULT line",
    )
    return p


def _iter_batch_inputs(input_dir: Path):
    for path in sorted(input_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def _convert(
    input_path,
    output_path,
    *,
    engine: str,
    schema: str,
    unify_angle: float | None,
    repair: str | None = None,
    cuts: list | None = None,
) -> ParityResult:
    """Preprocess (load/cut/repair) then convert through the native binary.

    The native binary takes STL only and rejects zero-normal STLs, so every input
    is normalised through our own loader and re-exported, exactly like the webapp.
    """
    verts, tris = load_mesh(input_path)
    if cuts:
        cr = apply_cuts(verts, tris, cuts)
        verts, tris = cr.verts, cr.tris
        if len(tris) == 0:
            return ParityResult(
                ok=False,
                input=str(Path(input_path).resolve()),
                output=str(Path(output_path).resolve()),
                error="cut operations removed all triangles",
            )
    if repair is not None:
        from . import repair as _repair

        rr = _repair.repair_mesh(verts, tris, level=repair)
        verts, tris = rr.verts, rr.tris
    with tempfile.TemporaryDirectory() as td:
        stl_path = Path(td) / "native_input.stl"
        trimesh.Trimesh(vertices=verts, faces=tris, process=False).export(str(stl_path))
        res = convert_native(
            stl_path,
            output_path,
            engine=engine,
            schema=schema,
            unify_angle=unify_angle,
            no_unify=(unify_angle is None),
        )
    parity = ParityResult.from_native(res)
    parity.input = str(Path(input_path).resolve())
    parity.output = str(Path(output_path).resolve())
    return parity


def _build_cut_ops(args):
    ops = []
    if args.cut_json:
        ops.extend(load_cut_ops(args.cut_json))
    if args.cut_largest:
        ops.append({"type": "largest"})
    return ops or None


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    output_dir = Path(args.output_dir) if args.output_dir else None
    native_engine = "trueform" if args.engine == "trueform" else "verbatim"
    merge_angle = args.unify_angle if args.unify_angle is not None else args.merge_coplanar

    if not input_path.exists():
        print(f"error: {input_path} does not exist", file=sys.stderr)
        return 1

    if input_path.is_dir():
        ops = _build_cut_ops(args)
        files = list(_iter_batch_inputs(input_path))
        if not files:
            print(f"error: no supported mesh files ({sorted(SUPPORTED_EXTENSIONS)}) in {input_path}", file=sys.stderr)
            return 1
        print(f"batch mode: {len(files)} file(s) in {input_path}")
        t_batch = time.perf_counter()
        n_ok = n_fail = 0
        for f in files:
            out = _default_output(f, output_dir)
            res = _convert(
                f,
                out,
                engine=native_engine,
                schema=args.format,
                unify_angle=merge_angle,
                repair=args.repair,
                cuts=ops,
            )
            _log_verbatim(res)
            if res.ok:
                n_ok += 1
            else:
                n_fail += 1
        print(f"batch done: {n_ok} ok, {n_fail} failed, {time.perf_counter() - t_batch:.2f}s total")
        return 1 if n_fail else 0

    output_path = Path(args.output) if args.output else _default_output(input_path, output_dir)
    res = _convert(
        input_path,
        output_path,
        engine=native_engine,
        schema=args.format,
        unify_angle=merge_angle,
    )
    if not args.quiet:
        _log_verbatim(res)
    emit_result(res)
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
