"""Repairs for a candidate SOLID that was rejected for how it is built, not for what it found.

The feature pass discards a whole candidate when the solid around its cylinders is wrong
(Acilindria `AC-B2`): `L08_angle_bracket`'s `turned` and `block` builders each recovered 4 of 4
cylinders and were thrown away for `solids=4` and `solids=2`. These functions attempt the one
repair the named clause asks for and hand the result back to the SAME unchanged gate.

They may only change the carrier. They never add a face, never fit a surface and never touch
`MIN_SUPPORT` or the mesh-backed-radius test: a repaired candidate earns its cylinders by being
a better solid, never by a lower bar (guideline 0.3.2, 4.B.3).

Every entry point returns True only when it wrote a file; an OCCT throw costs the repair and
nothing else.
"""
from __future__ import annotations

from pathlib import Path


def _read(step: Path):
    from OCP.STEPControl import STEPControl_Reader

    r = STEPControl_Reader()
    if r.ReadFile(str(step)) != 1:
        return None
    r.TransferRoots()
    sh = r.OneShape()
    return None if sh.IsNull() else sh


def _write(shape, out: Path) -> bool:
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    w = STEPControl_Writer()
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    w.Transfer(shape, STEPControl_AsIs)
    return w.Write(str(out)) == 1


def largest_solid(step_in: Path, step_out: Path) -> bool:
    """Keep the biggest solid and drop the debris around it (clause `solids`).

    A builder that cuts a pocket with a slightly short tool leaves the offcut behind as a second
    solid; the part is the big one. This is a selection, not a repair of geometry: nothing is
    moved, fitted or added, so a cylinder that survives was already built exactly as measured.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    sh = _read(step_in)
    if sh is None:
        return False
    sm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(sh, TopAbs_SOLID, sm)
    if sm.Extent() < 2:
        return False
    best, bestv = None, 0.0
    for i in range(1, sm.Extent() + 1):
        s = TopoDS.Solid_s(sm.FindKey(i))
        g = GProp_GProps()
        BRepGProp.VolumeProperties_s(s, g)
        if abs(g.Mass()) > bestv:
            best, bestv = s, abs(g.Mass())
    return bool(best is not None and _write(best, step_out))


def sew_fix(step_in: Path, step_out: Path, tol: float = 1e-3) -> bool:
    """Re-sew the faces and run ShapeFix (clauses `valid`, `free_edges`).

    The builders write faces that are geometrically coincident and topologically unshared, which
    is what a free edge IS. Sewing shares them; ShapeFix repairs wire order and orientation. The
    face set is unchanged, so this cannot invent a cylinder -- only make the shell that carries
    the ones already built into a closed solid.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Shape
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    sh = _read(step_in)
    if sh is None:
        return False
    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(sh, TopAbs_FACE, fm)
    sew = BRepBuilderAPI_Sewing(tol)
    for i in range(1, fm.Extent() + 1):
        sew.Add(fm.FindKey(i))
    sew.Perform()
    sewn = sew.SewedShape()
    shells = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(sewn, TopAbs_SHELL, shells)
    if shells.Extent() != 1:
        return False
    mk = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(shells.FindKey(1)))
    if not mk.IsDone():
        return False
    fix = ShapeFix_Shape(mk.Solid())
    fix.SetPrecision(tol)
    fix.Perform()
    return _write(fix.Shape(), step_out)
