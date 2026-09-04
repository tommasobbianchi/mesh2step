"""Single-file conversion orchestration + structured stats for logging."""
import math
import os
import sys as _sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepLib import BRepLib
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.gp import gp_Pnt
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.Precision import Precision
from OCP.Standard import Standard_Failure
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Shape, TopoDS_Shell

from . import brep_build, cut, dedup, io_mesh, merge_coplanar, result, sew, split, step_export
from .refit import (
    PrismTols,
    SegmentParams,
    build_faces,
    build_mesh_view,
    detect_prismatic,
    fit_profile,
    segment,
    slice_profiles,
    write_profile_dxf,
)
from .refit import try_stage_p as _try_stage_p
from .refit.stats import RefitStats


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


# --- TrueForm (analytic planar refit) --------------------------------------------


def convert_trueform(
    input_path,
    output_path,
    *,
    unify_angle: float | None = None,
    schema: str = "ap214",
    dxf_dir: Path | None = None,
) -> result.ParityResult:
    """TrueForm conversion: planar segmentation + analytic Geom_Plane faces per
    clean component, with the closed/valid/volume accept probe and per-component
    revert to the faceted build (port of stl2step.cpp's smooth path)."""
    t_start = time.perf_counter()
    out = result.ParityResult(
        input=str(Path(input_path).resolve()),
        output=str(Path(output_path).resolve()),
        smooth=True,
    )
    try:
        _convert_trueform_impl(out, input_path, output_path, unify_angle, schema, dxf_dir)
    except (ValueError, RuntimeError, Standard_Failure) as exc:
        out.ok = False
        out.error = str(exc)
    out.seconds = time.perf_counter() - t_start
    return out


def _count_cylindrical_faces(shape) -> int:
    n = 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        if BRepAdaptor_Surface(TopoDS.Face_s(exp.Current()), False).GetType() == GeomAbs_Cylinder:
            n += 1
        exp.Next()
    return n


def _segment_summary_stderr(root, rs) -> None:
    """Port of ``segmentSummaryStderr`` (stl2step.cpp:503), gated on
    MESH2STEP_SEGMENT_SUMMARY exactly as the reference gates on
    STL2STEP_SEGMENT_SUMMARY.

    The reference's most useful diagnostic, and the one we lacked: every
    per-component question -- which component got a plan, which used the refit,
    where the region counts diverge -- is answerable in one run with it and
    guesswork without it. Same line format, so the two can be diffed directly.
    """
    from .refit.segment import SurfType

    ty_of = {
        SurfType.PLANE: "plane",
        SurfType.CYLINDER: "cylinder",
        SurfType.CONE: "cone",
        SurfType.SPHERE: "sphere",
        SurfType.TORUS: "torus",
    }
    st = rs.stats
    print(
        f"engine segment root={root} regions={len(rs.regions)} "
        f"rejected={len(rs.rejected)} planes={st.planes} cylinders={st.cylinders} "
        f"fillets={st.fillets} facetIslands={st.facet_islands}",
        file=_sys.stderr,
    )
    for r in rs.regions:
        print(
            f"  id={r.id} type={ty_of.get(r.type, 'plane')} tris={len(r.tris)} "
            f"radius={r.radius:.6g} closed360={1 if r.closed360 else 0}",
            file=_sys.stderr,
        )


def _convert_trueform_impl(out, input_path, output_path, unify_angle, schema, dxf_dir=None):
    verts, tris = io_mesh.load_mesh(input_path)
    out.triangles = len(tris)

    sr = split.weld_and_split(verts, tris)
    out.vertices = sr.n_unique_verts
    out.components = sr.n_components
    out.watertight = sr.watertight
    out.mesh_volume_mm3 = sr.mesh_volume

    if dxf_dir is not None:
        dxf_dir = Path(dxf_dir)
        dxf_dir.mkdir(parents=True, exist_ok=True)
    dxf_stem = Path(input_path).stem if dxf_dir is not None else None

    lo = sr.verts.min(axis=0)
    hi = sr.verts.max(axis=0)
    diag = float(np.sqrt(((hi - lo) ** 2).sum()))
    sew_tol = _sew_tolerance(sr.verts)

    # Stage 3.5: TrueForm segment on each clean component (serial; the harness
    # does not measure time and threads would only add nondeterminism).
    plans = {}
    smooth_skipped = 0
    for idx, comp in enumerate(sr.components):
        if not comp.is_clean:
            smooth_skipped += 1
            continue
        mv = build_mesh_view(comp, diag, weld_tol=0.0, sew_tol=sew_tol)
        rs = segment(mv, SegmentParams())
        if rs is not None:
            plans[idx] = (mv, rs)
    out.smooth_skipped_components = smooth_skipped

    parts = []
    solids = 0
    open_shells = 0
    refit_totals = RefitStats()
    dvol_pred_abs = 0.0
    any_refit_used = False
    # Per-component build reports for the smoothBuilt* census (reference counts
    # cylinders from the built shape; planes/cylinders/fillets from the stats).
    comp_reports = []
    for idx, comp in enumerate(sr.components):
        used_refit = False
        refit_st = None
        n_cyls = 0
        shape = None
        plan = plans.get(idx)
        if plan is not None:
            mv, rs = plan
            ok, faces = _try_refit_component(mv, rs, comp, out, dxf_dir, dxf_stem)
            if ok:
                used_refit = True
                any_refit_used = True
                shape = brep_build.shell_to_solid(_faces_to_shell(faces))
                refit_st = rs.stats
                dvol_pred_abs += sum(abs(r.dvol_predicted) for r in rs.regions)
                n_cyls = _count_cylindrical_faces(shape)
        if shape is None:
            br = brep_build.build_faceted_shape(comp.verts, comp.tris)
            if comp.is_clean:
                shape = br.shape
                if br.is_solid:
                    solids += 1
                else:
                    open_shells += 1
            else:
                faces = []
                exp = TopExp_Explorer(br.shape, TopAbs_FACE)
                while exp.More():
                    faces.append(TopoDS.Face_s(exp.Current()))
                    exp.Next()
                shape = None
                for sh in sew.repair_faces(faces, sew_tol):
                    wrapped = brep_build.shell_to_solid(sh)
                    if wrapped.ShapeType() == TopAbs_SOLID:
                        solids += 1
                    else:
                        open_shells += 1
                    if shape is None:
                        shape = wrapped
                    else:
                        shape = _make_compound([shape, wrapped])
        _sum_on = os.environ.get("MESH2STEP_SEGMENT_SUMMARY", "") not in ("", "0")
        if plan is not None and _sum_on:
            _segment_summary_stderr(idx, plan[1])
            print(f"  usedRefit={1 if used_refit else 0}", file=_sys.stderr)
        if used_refit:
            # Accepted analytic shells are closed by the probe; count as solids
            # exactly like the faceted path does.
            if shape.ShapeType() == TopAbs_SOLID:
                solids += 1
            else:
                open_shells += 1
            refit_totals.absorb(refit_st)
        parts.append(shape)
        comp_reports.append((plan is not None, used_refit, refit_st, n_cyls))
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
        # TrueForm-only: mesh-jitter-aware flat consolidation on faceted islands
        # (coarse band only; verbatim defaults stay untouched).
        if 500 <= out.triangles <= 1200:
            seg_max_dev = refit_totals.max_vertex_dev
            for _mv, rs in plans.values():
                seg_max_dev = max(seg_max_dev, rs.stats.max_vertex_dev)
            eps_mesh = max(0.0, 1e-4 * diag, 1e-3)
            dev = max(seg_max_dev, eps_mesh)
            length = max(diag, dev)
            smooth_flat_deg = max(0.01, dev / length * (180.0 / math.pi))
            if smooth_flat_deg > unify_angle:
                shape, _, n_after = merge_coplanar.merge_coplanar(shape, smooth_flat_deg, 1e-7)
                out.faces_after_unify = n_after

    out.faces_after_smooth = out.faces_after_unify

    refit_faces = refit_totals.planes + refit_totals.cylinders + refit_totals.fillets
    if any_refit_used and refit_faces > 0:
        BRepLib.EncodeRegularity_s(shape, Precision.Angular_s())

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

    # smoothBuilt* census (stl2step.cpp): reverted components count against
    # smoothRevertedComponents; only accepted components contribute stats.
    built_pl = built_fi = built_co = rev_co = 0
    # builtCy counts cylinder faces on the FINAL unified shape (stl2step.cpp
    # counts each component's post-unify faces; reverted components are faceted
    # with no cylinders, so the whole-shape total is identical).
    built_cy = _count_cylindrical_faces(shape)
    for had_plan, used_refit, refit_st, n_cyls in comp_reports:
        if not used_refit:
            if had_plan:
                rev_co += 1
            continue
        if n_cyls > 0 or (refit_st.cylinders == 0 and refit_st.planes > 0):
            built_co += 1
            built_pl += refit_st.planes
            built_fi += refit_st.fillets
        else:
            rev_co += 1

    out.smooth_planes = refit_totals.planes
    out.smooth_cylinders = refit_totals.cylinders
    out.smooth_fillets = refit_totals.fillets
    out.smooth_distinct_radii = refit_totals.distinct_radii
    out.smooth_rejected = refit_totals.rejected
    out.smooth_facet_faces = refit_totals.facet_triangles
    out.smooth_max_dev_mm = refit_totals.max_vertex_dev
    out.smooth_max_edge_tol_mm = refit_totals.max_edge_tol
    out.smooth_vol_predicted_mm3 = refit_totals.dvol_predicted
    out.smooth_built_planes = built_pl
    out.smooth_built_cylinders = built_cy
    out.smooth_built_fillets = built_fi
    out.smooth_built_components = built_co
    out.smooth_reverted_components = rev_co


def _faces_to_shell(faces) -> TopoDS_Shape:
    builder = BRep_Builder()
    shell = TopoDS_Shell()
    builder.MakeShell(shell)
    for f in faces:
        builder.Add(shell, f)
    return shell


def _write_dxf_profiles(mv, rs, lv, dxf_dir, dxf_stem) -> None:
    """Emit one DXF per slab for a prismatic component (port of the D8 §3.2 block
    in refit_prism_build.cpp's tryStageP): slice + fit the profiles, then write
    ``<stem>-comp<C>-slab<M>.dxf`` for each. Pure serializer — never consulted by
    the engine, so a write failure is discarded exactly as the reference does."""
    tols = PrismTols()
    profs = slice_profiles(mv, rs, lv, tols)
    for p in profs:
        fit_profile(mv, tols, p)
    comp = rs.comp_root if rs.comp_root >= 0 else 0
    stem = dxf_stem if dxf_stem else "profile"
    for p in profs:
        path = Path(dxf_dir) / f"{stem}-comp{comp}-slab{p.slab}.dxf"
        write_profile_dxf(p, lv, str(path))


def _try_refit_component(mv, rs, comp, out, dxf_dir=None, dxf_stem=None) -> tuple[bool, list]:
    """Build the analytic faces and run the accept probe (stl2step.cpp): the
    probe shell must be closed, BRepCheck-valid, and within the volume budget.
    On any failure the component reverts to the faceted build."""
    # Route P (prismatic): detect -> slice -> fit -> build -> census. On decline
    # or build failure the component falls through to route G byte-identically.
    lv = detect_prismatic(mv, rs)
    if lv.ok:
        if dxf_dir is not None:
            _write_dxf_profiles(mv, rs, lv, dxf_dir, dxf_stem)
        pres = _try_stage_p(mv, rs)
        if pres.ok and pres.faces:
            return True, pres.faces
    verts = []
    for i in range(mv.n_vtx):
        p = mv.pts[int(mv.comp_vtx[i])]
        verts.append(
            BRepBuilderAPI_MakeVertex(gp_Pnt(float(p[0]), float(p[1]), float(p[2]))).Vertex()
        )
    ok, faces = build_faces(mv, rs, verts)
    if not ok or not faces:
        return False, []
    probe = _faces_to_shell(faces)
    try:
        if not BRep_Tool.IsClosed_s(probe):
            return False, []
        if not BRepCheck_Analyzer(probe, True).IsValid():
            return False, []
        dvol_abs = sum(abs(r.dvol_predicted) for r in rs.regions)
        mesh_vol = abs(comp.signed_volume)
        budget = max(1e-4 * mesh_vol, 3.0 * dvol_abs)
        shell_vol = _shape_volume(probe)
        if abs(shell_vol - mesh_vol) > budget:
            return False, []
    except Standard_Failure:
        return False, []
    return True, faces
