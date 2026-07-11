"""A faithful, from-source reimplementation of FreeCAD's
`Part.Shape.makeShapeFromMesh(topology, tol)` construction strategy, used as the
benchmark baseline.

Why a reimplementation and not real FreeCAD: this host has no `conda`/`mamba` (so no
pip-installable `pythonocc-core` path either -- see SELECTION.md) and no passwordless
`sudo` to `apt install freecad`. Rather than skip the requested comparison, this
reproduces the actual algorithm FreeCAD's TopoShape::makeShapeFromMesh and
OCC-CSG's importSTL both use -- per-facet `BRepBuilderAPI_MakeVertex` (fresh vertices,
NOT indexed/shared) + face-per-triangle + a single `BRepBuilderAPI_Sewing(tol)` pass to
reconstruct topology -- on the SAME OCCT kernel (OCP) this project's own converter
uses, so the comparison isolates "shared-topology-by-construction vs.
build-then-sew," which is the specific architectural difference this project claims
to fix, rather than conflating it with a difference in OCCT version or binding.

This is clearly NOT the FreeCAD application itself and is labeled as such in the
benchmark report.
"""
import time

from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeSolid,
    BRepBuilderAPI_MakeVertex,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_Sewing,
)
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound


def build_freecad_equivalent(verts, tris, tolerance: float):
    """Mirrors makeShapeFromMesh: fresh (unshared) vertices per triangle corner,
    independent faces, then a single BRepBuilderAPI_Sewing(tolerance) pass."""
    t0 = time.perf_counter()

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)

    n_faces_built = 0
    n_faces_failed = 0
    for tri in tris:
        p0, p1, p2 = verts[tri[0]], verts[tri[1]], verts[tri[2]]
        try:
            v0 = BRepBuilderAPI_MakeVertex(gp_Pnt(float(p0[0]), float(p0[1]), float(p0[2]))).Vertex()
            v1 = BRepBuilderAPI_MakeVertex(gp_Pnt(float(p1[0]), float(p1[1]), float(p1[2]))).Vertex()
            v2 = BRepBuilderAPI_MakeVertex(gp_Pnt(float(p2[0]), float(p2[1]), float(p2[2]))).Vertex()
            wire = BRepBuilderAPI_MakeWire(
                _edge(v0, v1), _edge(v1, v2), _edge(v2, v0)
            ).Wire()
            face_maker = BRepBuilderAPI_MakeFace(wire)
            if not face_maker.IsDone():
                n_faces_failed += 1
                continue
            builder.Add(compound, face_maker.Face())
            n_faces_built += 1
        except Exception:
            n_faces_failed += 1

    t_build = time.perf_counter() - t0

    t0 = time.perf_counter()
    sewer = BRepBuilderAPI_Sewing(tolerance)
    sewer.Add(compound)
    sewer.Perform()
    sewn = sewer.SewedShape()
    t_sew = time.perf_counter() - t0

    n_shells = _count(sewn, TopAbs_SHELL)
    n_faces_after_sew = _count(sewn, TopAbs_FACE)

    shape = sewn
    is_solid = False
    volume = None
    if n_shells == 1:
        exp = TopExp_Explorer(sewn, TopAbs_SHELL)
        shell = TopoDS.Shell_s(exp.Current())
        mk_solid = BRepBuilderAPI_MakeSolid(shell)
        if mk_solid.IsDone():
            solid = mk_solid.Solid()
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(solid, props)
            vol = abs(props.Mass())
            if vol > 0:
                shape = solid
                is_solid = True
                volume = vol

    return {
        "shape": shape,
        "n_faces_built": n_faces_built,
        "n_faces_failed": n_faces_failed,
        "n_faces_after_sew": n_faces_after_sew,
        "n_shells": n_shells,
        "is_solid": is_solid,
        "volume": volume,
        "t_build_s": t_build,
        "t_sew_s": t_sew,
        "t_total_s": t_build + t_sew,
    }


def _edge(v0, v1):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge

    return BRepBuilderAPI_MakeEdge(v0, v1).Edge()


def _count(shape, kind) -> int:
    exp = TopExp_Explorer(shape, kind)
    n = 0
    while exp.More():
        n += 1
        exp.Next()
    return n
