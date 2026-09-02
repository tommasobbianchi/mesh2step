"""Single-file conversion orchestration + structured stats for logging."""
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.GeomAbs import GeomAbs_Plane
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.Precision import Precision
from OCP.Standard import Standard_Failure
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Shape

from . import brep_build, cut, dedup, io_mesh, merge_coplanar, result, sew, split, step_export


@dataclass
class ConvertStats:
    input_path: str
    output_path: str
    tolerance: float | str
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

    n_cut_tris_before: int | None = None
    n_cut_tris_after: int | None = None
    t_cut_s: float = 0.0

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
    tolerance: float | str = 0.01,
    merge_coplanar_angle: float | None = None,
    merge_coplanar_linear_tol: float | None = None,
    schema: str = "ap214",
    repair: str | None = None,
    cuts: list | None = None,
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

    if cuts:
        t0 = time.perf_counter()
        cr = cut.apply_cuts(verts, tris, cuts)
        verts, tris = cr.verts, cr.tris
        stats.n_cut_tris_before = cr.n_tris_before
        stats.n_cut_tris_after = cr.n_tris_after
        stats.t_cut_s = time.perf_counter() - t0

        if len(tris) == 0:
            stats.error = "cut operations removed all triangles"
            stats.t_total_s = time.perf_counter() - t_start
            return stats

    if tolerance == "auto":
        tolerance = dedup.smart_tolerance(verts)
        stats.tolerance = tolerance

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


def _count_faces(shape) -> int:
    n = 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        n += 1
        exp.Next()
    return n


def _shape_volume(shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _sew_tolerance(verts) -> float:
    lo = verts.min(axis=0)
    hi = verts.max(axis=0)
    diag = float(np.sqrt(((hi - lo) ** 2).sum()))
    return min(max(1e-6, diag * 1e-5), 0.5)


def _make_compound(parts) -> TopoDS_Shape:
    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    for p in parts:
        builder.Add(comp, p)
    return comp


def _read_step_volume(path) -> float:
    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        return 0.0
    reader.TransferRoots()
    shape = reader.OneShape()
    if shape.IsNull():
        return 0.0
    return _shape_volume(shape)


def _fit_planar_tolerances(shape) -> None:
    """Raise vertex/edge tolerances to the true deviation from each merged planar
    face. STL facet normals carry float32 noise, so a coplanar merge leaves boundary
    vertices sitting off the plane by more than OCCT's default 1e-7; without raising
    the stored tolerance the shape fails boolean overlays. No-op on exact geometry."""
    builder = BRep_Builder()
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        surf = BRepAdaptor_Surface(face, False)
        if surf.GetType() != GeomAbs_Plane:
            exp.Next()
            continue
        plane = surf.Plane()
        vexp = TopExp_Explorer(face, TopAbs_VERTEX)
        while vexp.More():
            vert = TopoDS.Vertex_s(vexp.Current())
            d = plane.Distance(BRep_Tool.Pnt_s(vert))
            if d > BRep_Tool.Tolerance_s(vert):
                builder.UpdateVertex(vert, d * 1.001 + Precision.Confusion_s())
            vexp.Next()
        eexp = TopExp_Explorer(face, TopAbs_EDGE)
        while eexp.More():
            edge = TopoDS.Edge_s(eexp.Current())
            d = 0.0
            ee = TopExp_Explorer(edge, TopAbs_VERTEX)
            while ee.More():
                d = max(d, plane.Distance(BRep_Tool.Pnt_s(TopoDS.Vertex_s(ee.Current()))))
                ee.Next()
            if d > BRep_Tool.Tolerance_s(edge):
                builder.UpdateEdge(edge, d * 1.001 + Precision.Confusion_s())
            eexp.Next()
        exp.Next()


def convert_verbatim(
    input_path,
    output_path,
    *,
    unify_angle: float | None = None,
    schema: str = "ap214",
) -> result.ParityResult:
    """Reference-engine-faithful verbatim conversion: exact weld, manifold component
    split, per-component solid build, coplanar merge, and a RESULT payload."""
    t_start = time.perf_counter()
    out = result.ParityResult(
        input=str(Path(input_path).resolve()),
        output=str(Path(output_path).resolve()),
    )
    try:
        _convert_verbatim_impl(out, input_path, output_path, unify_angle, schema)
    except (ValueError, RuntimeError, Standard_Failure) as exc:
        out.ok = False
        out.error = str(exc)
    out.seconds = time.perf_counter() - t_start
    return out


def _convert_verbatim_impl(out, input_path, output_path, unify_angle, schema):
    verts, tris = io_mesh.load_mesh(input_path)
    out.triangles = len(tris)

    sr = split.weld_and_split(verts, tris)
    out.vertices = sr.n_unique_verts
    out.components = sr.n_components
    out.watertight = sr.watertight
    out.mesh_volume_mm3 = sr.mesh_volume

    parts = []
    solids = 0
    open_shells = 0
    sew_tol = _sew_tolerance(sr.verts)
    for comp in sr.components:
        br = brep_build.build_faceted_shape(comp.verts, comp.tris)
        if comp.is_clean:
            if br.is_solid:
                solids += 1
            else:
                open_shells += 1
            parts.append(br.shape)
            continue
        faces = []
        exp = TopExp_Explorer(br.shape, TopAbs_FACE)
        while exp.More():
            faces.append(TopoDS.Face_s(exp.Current()))
            exp.Next()
        for sh in sew.repair_faces(faces, sew_tol):
            wrapped = brep_build.shell_to_solid(sh)
            if wrapped.ShapeType() == TopAbs_SOLID:
                solids += 1
            else:
                open_shells += 1
            parts.append(wrapped)
    out.solids = solids
    out.open_shells = open_shells

    if not parts:
        out.ok = False
        out.error = "no usable geometry"
        return

    shape = parts[0] if len(parts) == 1 else _make_compound(parts)
    out.faces_before_unify = _count_faces(shape)
    out.faces_after_unify = out.faces_before_unify

    if unify_angle is not None:
        shape, _, n_after = merge_coplanar.merge_coplanar(shape, unify_angle, 1e-7)
        out.faces_after_unify = n_after

    _fit_planar_tolerances(shape)

    brep_volume = _shape_volume(shape)
    if out.watertight and out.mesh_volume_mm3 > 0:
        if abs(brep_volume - out.mesh_volume_mm3) / out.mesh_volume_mm3 > 1e-4:
            out.warnings.append(
                "B-Rep volume differs from mesh volume by more than 0.01% -- inspect the result"
            )

    step_export.write_step(shape, output_path, schema=schema)

    out.step_volume_mm3 = _read_step_volume(output_path)
    if brep_volume != 0:
        out.volume_delta_pct = (
            abs(out.step_volume_mm3 - brep_volume) / abs(brep_volume) * 100.0
        )
    out.ok = True
