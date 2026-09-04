"""Fail-to-Pass for the seamed 360° cylinder constructor (M6a).

Drives the same MeshView + RegionSet path the conversion pipeline uses
(convert.py `_convert_trueform_impl`), then calls `build_faces` directly and
asserts the construction verdict the reference produces on
`nonprismatic-control`:

    DIAG_COLLAPSE mix=0 none=0 fail=0 ok=4 total=4 recover=0 rounds=0

The reference's RESULT still reverts this fixture to faceted because of the
per-region volume-residual gate (DIAG_CASCADE, M6b) -- out of scope here -- so
this suite is written against `build_faces`, not `convert_trueform`.
"""
from __future__ import annotations

from pathlib import Path

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.gp import gp_Pnt
from OCP.TopoDS import TopoDS_Shell

from mesh2step import io_mesh, split
from mesh2step.refit import SegmentParams, build_faces, build_mesh_view, segment
from mesh2step.refit.segment import BuiltAs, SurfType

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "data" / "corpus"
FIXTURE = CORPUS / "nonprismatic-control.stl"

EXPECTED_DIAG = "DIAG_COLLAPSE mix=0 none=0 fail=0 ok=4 total=4 recover=0 rounds=0"


def _segment_fixture():
    verts, tris = io_mesh.load_mesh(FIXTURE)
    sr = split.weld_and_split(verts, tris)
    assert sr.n_components == 1
    comp = sr.components[0]
    assert comp.is_clean

    lo = sr.verts.min(axis=0)
    hi = sr.verts.max(axis=0)
    diag = float(((hi - lo) ** 2).sum() ** 0.5)
    sew_tol = min(max(1e-6, diag * 1e-5), 0.5)

    mv = build_mesh_view(comp, diag, weld_tol=0.0, sew_tol=sew_tol)
    rs = segment(mv, SegmentParams())
    assert rs is not None
    return mv, rs


def _build_verts(mv):
    verts = []
    for i in range(mv.n_vtx):
        p = mv.pts[int(mv.comp_vtx[i])]
        verts.append(
            BRepBuilderAPI_MakeVertex(gp_Pnt(float(p[0]), float(p[1]), float(p[2]))).Vertex()
        )
    return verts


def _shell_closed(faces) -> bool:
    builder = BRep_Builder()
    shell = TopoDS_Shell()
    builder.MakeShell(shell)
    for f in faces:
        builder.Add(shell, f)
    return bool(BRep_Tool.IsClosed_s(shell))


def test_seamed360_cylinders_built_and_shell_closed(monkeypatch, capsys):
    mv, rs = _segment_fixture()
    verts = _build_verts(mv)

    monkeypatch.setenv("MESH2STEP_COLLAPSE_DIAG", "1")
    ok, faces = build_faces(mv, rs, verts)

    cylinders = [r for r in rs.regions if r.type == SurfType.CYLINDER]
    assert len(cylinders) == 2
    assert all(r.closed360 for r in cylinders)

    # Assertion 1: both closed360 cylinders end as SEAMED360 (today: EXPLODED).
    for r in cylinders:
        assert r.built_as == BuiltAs.SEAMED360, (
            f"cylinder rid={r.id} built_as={r.built_as}, expected SEAMED360"
        )

    # Assertion 2: no region is exploded.
    assert all(r.built_as != BuiltAs.EXPLODED_TO_FACETS for r in rs.regions)

    # Assertion 3: the assembled analytic shell is closed (J6 does not fire).
    assert ok, "build_faces declined"
    assert faces, "build_faces returned no faces"
    assert _shell_closed(faces), "analytic shell is not closed"

    # Assertion 4: the DIAG_COLLAPSE line matches the reference.
    err = capsys.readouterr().err
    diag_lines = [ln for ln in err.splitlines() if ln.startswith("DIAG_COLLAPSE ")]
    assert diag_lines, f"no DIAG_COLLAPSE line emitted; stderr:\n{err}"
    assert EXPECTED_DIAG in diag_lines, (
        f"DIAG_COLLAPSE mismatch.\nours:   {diag_lines}\nref:    {EXPECTED_DIAG}"
    )
