"""Single-file conversion orchestration + structured stats for logging."""
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import brep_build, dedup, io_mesh, merge_coplanar, step_export


@dataclass
class ConvertStats:
    input_path: str
    output_path: str
    tolerance: float
    schema: str
    merge_coplanar_angle_deg: float | None = None

    n_input_verts: int = 0
    n_input_tris: int = 0
    n_unique_verts: int = 0
    n_degenerate_collapsed: int = 0
    n_degenerate_zero_area: int = 0
    n_kept_tris: int = 0

    n_faces_built: int = 0
    n_faces_failed: int = 0
    n_boundary_edges: int = 0
    n_nonmanifold_edges: int = 0
    watertight: bool = False
    is_solid: bool = False
    volume: float | None = None

    n_faces_before_merge: int | None = None
    n_faces_after_merge: int | None = None

    repair_level: str | None = None
    n_repair_faces_before: int | None = None
    n_repair_faces_after: int | None = None
    repair_holes_filled: bool | None = None
    repair_watertight_after: bool | None = None
    t_repair_s: float = 0.0

    output_size_bytes: int = 0

    t_load_s: float = 0.0
    t_dedup_s: float = 0.0
    t_build_s: float = 0.0
    t_merge_s: float = 0.0
    t_write_s: float = 0.0
    t_total_s: float = 0.0

    error: str | None = None

    def as_dict(self):
        return asdict(self)


def convert_file(
    input_path,
    output_path,
    tolerance: float = 0.01,
    merge_coplanar_angle: float | None = None,
    merge_coplanar_linear_tol: float | None = None,
    schema: str = "ap214",
    repair: str | None = None,
) -> ConvertStats:
    input_path = Path(input_path)
    output_path = Path(output_path)
    t_start = time.perf_counter()

    stats = ConvertStats(
        input_path=str(input_path),
        output_path=str(output_path),
        tolerance=tolerance,
        schema=schema,
        merge_coplanar_angle_deg=merge_coplanar_angle,
    )

    t0 = time.perf_counter()
    verts, tris = io_mesh.load_mesh(input_path)
    stats.n_input_verts = len(verts)
    stats.n_input_tris = len(tris)
    stats.t_load_s = time.perf_counter() - t0

    if repair is not None:
        from . import repair as _repair

        t0 = time.perf_counter()
        rr = _repair.repair_mesh(verts, tris, level=repair)
        verts, tris = rr.verts, rr.tris
        stats.repair_level = repair
        stats.n_repair_faces_before = rr.n_faces_before
        stats.n_repair_faces_after = rr.n_faces_after
        stats.repair_holes_filled = rr.holes_filled
        stats.repair_watertight_after = rr.watertight_after
        stats.t_repair_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    dd = dedup.dedup_and_clean(verts, tris, tolerance)
    stats.n_unique_verts = dd.n_unique_verts
    stats.n_degenerate_collapsed = dd.n_degenerate_collapsed
    stats.n_degenerate_zero_area = dd.n_degenerate_zero_area
    stats.n_kept_tris = dd.n_kept_tris
    stats.t_dedup_s = time.perf_counter() - t0

    if dd.n_kept_tris == 0:
        stats.error = "no triangles survived dedup/degenerate filtering"
        stats.t_total_s = time.perf_counter() - t_start
        return stats

    t0 = time.perf_counter()
    build = brep_build.build_faceted_shape(dd.verts, dd.tris)
    stats.n_faces_built = build.n_faces_built
    stats.n_faces_failed = build.n_faces_failed
    stats.n_boundary_edges = build.n_boundary_edges
    stats.n_nonmanifold_edges = build.n_nonmanifold_edges
    stats.watertight = build.watertight
    stats.is_solid = build.is_solid
    stats.volume = build.volume
    stats.t_build_s = time.perf_counter() - t0

    shape = build.shape
    if merge_coplanar_angle is not None:
        t0 = time.perf_counter()
        lin_tol = merge_coplanar_linear_tol if merge_coplanar_linear_tol is not None else tolerance
        shape, n_before, n_after = merge_coplanar.merge_coplanar(shape, merge_coplanar_angle, lin_tol)
        stats.n_faces_before_merge = n_before
        stats.n_faces_after_merge = n_after
        stats.t_merge_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    step_export.write_step(shape, output_path, schema=schema)
    stats.output_size_bytes = output_path.stat().st_size
    stats.t_write_s = time.perf_counter() - t0

    stats.t_total_s = time.perf_counter() - t_start
    return stats
