"""Sewing + ShapeFix repair for components that do not close from shared topology.

A component with open / conflicting / non-manifold edges cannot be wrapped as a
solid by construction. Its faces are sewn at the given tolerance, then each
resulting shell is run through ShapeFix_Shell. Closed shells become solids
upstream; the rest are reported as open shells -- never wrapped as fake solids.
"""
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
from OCP.ShapeFix import ShapeFix_Shell
from OCP.Standard import Standard_Failure
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shell


def repair_faces(faces, tolerance: float) -> list:
    """Sew a set of faces into shells, ShapeFix each, return the shells in order."""
    sewing = BRepBuilderAPI_Sewing(tolerance)
    for f in faces:
        sewing.Add(f)
    sewing.Perform()
    sewed = sewing.SewedShape()

    shells: list = []
    exp = TopExp_Explorer(sewed, TopAbs_SHELL)
    while exp.More():
        shell = TopoDS.Shell_s(exp.Current())
        try:
            fix = ShapeFix_Shell(shell)
            fix.Perform()
            fix_exp = TopExp_Explorer(fix.Shape(), TopAbs_SHELL)
            while fix_exp.More():
                shells.append(TopoDS.Shell_s(fix_exp.Current()))
                fix_exp.Next()
        except Standard_Failure:
            shells.append(shell)
        exp.Next()

    builder = BRep_Builder()
    leftover = TopoDS_Shell()
    builder.MakeShell(leftover)
    n_leftover = 0
    left_exp = TopExp_Explorer(sewed, TopAbs_FACE, TopAbs_SHELL)
    while left_exp.More():
        builder.Add(leftover, left_exp.Current())
        n_leftover += 1
        left_exp.Next()
    if n_leftover:
        shells.append(leftover)

    return shells
