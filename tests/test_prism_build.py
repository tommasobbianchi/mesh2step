"""Fail-to-Pass oracle for route P construction (``build_prism_solid`` + census).

The Python port must reproduce the reference engine's ``DIAG_PRISMBUILD`` output
for the handle-lock fixture exactly. Ground truth was measured from the reference
binary and committed as ``tests/data/reference/handle-lock.prismbuild.txt`` — the
test parses that file and never retypes its numbers.

Drives the same path as ``test_prism.py`` / ``test_profile.py`` (weld/split ->
``build_mesh_view`` -> ``segment``), then runs ``try_stage_p`` (detect -> slice ->
fit -> build -> fuse -> unify -> census). Integer fields (face/plane/cylinder
counts, ``valid``/``watertight``/``reverted``/``G2``/``G4``/``cond``, ``nAdj``/
``nExact``) must match exactly; volumes and tolerances compare at ``rel=1e-6``.

The two residual distances ``|s-Vref|`` and ``|s-mesh|`` are ``|vol - ref|``, so
their error bar equals the built volume's own error (~2.4e-5 mm^3, a relative
~1.5e-9 of the 15868 mm^3 solid — the segment cylinder-radius precision carried
into the fitted profile). They are asserted at that absolute scale
(``abs=5e-5``) rather than at ``rel=1e-6`` of their own far smaller magnitude,
which no volume's precision could satisfy.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from mesh2step import io_mesh, split
from mesh2step.refit import (
    SegmentParams,
    build_mesh_view,
    segment,
    try_stage_p,
)

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "data" / "corpus"
GOLDEN = ROOT / "tests" / "data" / "reference" / "handle-lock.prismbuild.txt"

VOL_REL = 1e-6
RESID_ABS = 5e-5  # |s-Vref| / |s-mesh| — the built volume's own absolute precision


def _sew_tolerance(verts) -> float:
    lo = verts.min(axis=0)
    hi = verts.max(axis=0)
    diag = float(np.sqrt(((hi - lo) ** 2).sum()))
    return min(max(1e-6, diag * 1e-5), 0.5)


def _build_result():
    """(result) for the prismatic handle-lock component via try_stage_p."""
    verts, tris = io_mesh.load_mesh(CORPUS / "handle-lock.stl")
    sr = split.weld_and_split(verts, tris)
    lo = sr.verts.min(axis=0)
    hi = sr.verts.max(axis=0)
    diag = float(np.sqrt(((hi - lo) ** 2).sum()))
    sew_tol = _sew_tolerance(sr.verts)
    for comp in sr.components:
        if not comp.is_clean:
            continue
        mv = build_mesh_view(comp, diag, weld_tol=0.0, sew_tol=sew_tol)
        rs = segment(mv, SegmentParams())
        assert rs is not None, "segmentation returned None"
        res = try_stage_p(mv, rs)
        if res.ok:
            return res
    pytest.fail("handle-lock has no prismatic component")


def _parse_golden():
    """Parse the 9 DIAG_PRISMBUILD lines into named numeric fields."""
    out = {}
    for line in GOLDEN.read_text().splitlines():
        if "slab=" in line and "fuse" not in line:
            m = re.search(r"slab=(\d+) faces=(\d+) vol=([0-9.eE+-]+) valid=(\d+)", line)
            out.setdefault("slabs", []).append(
                (int(m.group(2)), float(m.group(3)), int(m.group(4)))
            )
        elif "fuse-k=" in line:
            m = re.search(r"fuse-k=(\d+) faces=(\d+)", line)
            out.setdefault("fuses", []).append((int(m.group(1)), int(m.group(2))))
        elif "usd-try" in line:
            m = re.search(
                r"P=(\d+)->(\d+) C=(\d+)->(\d+) V=([0-9.eE+-]+)->([0-9.eE+-]+)", line
            )
            out["usd_try"] = (
                int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)),
                float(m.group(5)), float(m.group(6)),
            )
        elif "plane-adj" in line:
            m = re.search(r"nAdj=(\d+) nExact=(\d+) nPlanes=(\d+)", line)
            out["plane_adj"] = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif "unify faces=" in line:
            m = re.search(
                r"unify faces=(\d+) G1=(\d+) G2=(\d+) G4=(\d+) "
                r"V_before=([0-9.eE+-]+) V_after=([0-9.eE+-]+) "
                r"planes=(\d+)->(\d+) cyls=(\d+)->(\d+)",
                line,
            )
            out["unify"] = (
                int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)),
                float(m.group(5)), float(m.group(6)),
                int(m.group(7)), int(m.group(8)), int(m.group(9)), int(m.group(10)),
            )
        elif " vol D_signed=" in line or "D_signed=" in line:
            m = re.search(
                r"D_signed=([0-9.eE+-]+) D_abs=([0-9.eE+-]+) V_ref=([0-9.eE+-]+) "
                r"budget=([0-9.eE+-]+) envelope=([0-9.eE+-]+) "
                r"\|s-Vref\|=([0-9.eE+-]+) \|s-mesh\|=([0-9.eE+-]+) "
                r"cond1=(\d+) cond2=(\d+)",
                line,
            )
            out["vol_gate"] = (
                float(m.group(1)), float(m.group(2)), float(m.group(3)),
                float(m.group(4)), float(m.group(5)), float(m.group(6)),
                float(m.group(7)), int(m.group(8)), int(m.group(9)),
            )
        elif line.startswith("DIAG_PRISMBUILD G1="):
            m = re.search(
                r"G1=(\d+) G2=(\d+) G3_planes=(\d+) G4=(\d+) "
                r"cyls=(\d+)->(\d+) V_before=([0-9.eE+-]+) V_after=([0-9.eE+-]+)",
                line,
            )
            out["g_line"] = (
                int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)),
                int(m.group(5)), int(m.group(6)), float(m.group(7)), float(m.group(8)),
            )
        elif "comp=" in line:
            m = re.search(
                r"comp=(\d+) slabs=(\d+) faces=(\d+) planes=(\d+) cyls=(\d+) "
                r"vol=([0-9.eE+-]+) watertight=(\d+) valid=(\d+) reverted=(\d+)",
                line,
            )
            out["census"] = (
                int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)),
                int(m.group(5)), float(m.group(6)), int(m.group(7)), int(m.group(8)),
                int(m.group(9)),
            )
    return out


def test_handle_lock_prism_build():
    res = _build_result()
    assert res.ok
    d = res.pb.diag
    g = _parse_golden()

    # slab / fuse face counts (exact) and volumes (rel).
    assert len(d.slabs) == len(g["slabs"])
    for (faces, vol, valid), (gf, gv, gval) in zip(d.slabs, g["slabs"], strict=True):
        assert faces == gf
        assert valid == gval
        assert vol == pytest.approx(gv, rel=VOL_REL)

    assert [(k, f) for k, f in d.fuses] == g["fuses"]

    p0, p1, c0, c1, v0, v1 = d.usd_try
    gp0, gp1, gc0, gc1, gv0, gv1 = g["usd_try"]
    assert (p0, p1, c0, c1) == (gp0, gp1, gc0, gc1)
    assert v0 == pytest.approx(gv0, rel=VOL_REL)
    assert v1 == pytest.approx(gv1, rel=VOL_REL)

    assert d.plane_adj == g["plane_adj"]

    (uf, ug1, ug2, ug4, uvb, uva, up0, up1, uc0, uc1) = d.unify
    (gf_, gg1, gg2, gg4, gvb, gva, gp0_, gp1_, gc0_, gc1_) = g["unify"]
    assert (uf, ug1, ug2, ug4) == (gf_, gg1, gg2, gg4)
    assert (up0, up1, uc0, uc1) == (gp0_, gp1_, gc0_, gc1_)
    assert uvb == pytest.approx(gvb, rel=VOL_REL)
    assert uva == pytest.approx(gva, rel=VOL_REL)

    (ds, da, vr, bud, env, svr, sm, c1_, c2_) = d.vol_gate
    (gds, gda, gvr, gbud, genv, gsvr, gsm, gc1, gc2) = g["vol_gate"]
    assert ds == pytest.approx(gds, rel=VOL_REL)
    assert da == pytest.approx(gda, rel=VOL_REL)
    assert vr == pytest.approx(gvr, rel=VOL_REL)
    assert bud == pytest.approx(gbud, rel=VOL_REL)
    assert env == pytest.approx(genv, rel=VOL_REL)
    assert svr == pytest.approx(gsvr, rel=VOL_REL, abs=RESID_ABS)
    assert sm == pytest.approx(gsm, rel=VOL_REL, abs=RESID_ABS)
    assert (c1_, c2_) == (gc1, gc2)

    (gg1_, gg2_, gg3, gg4_, gc0__, gc1__, gvb_, gva_) = d.g_line
    (h1, h2, h3, h4, hc0, hc1, hvb, hva) = g["g_line"]
    assert (gg1_, gg2_, gg3, gg4_) == (h1, h2, h3, h4)
    assert (gc0__, gc1__) == (hc0, hc1)
    assert gvb_ == pytest.approx(hvb, rel=VOL_REL)
    assert gva_ == pytest.approx(hva, rel=VOL_REL)

    (cc, cs, cf, cp, ccy, cv, cw, cva, cr) = d.census
    (hc, hs, hf, hp, hcy, hv, hw, hva2, hr) = g["census"]
    assert (cc, cs, cf, cp, ccy) == (hc, hs, hf, hp, hcy)
    assert cv == pytest.approx(hv, rel=VOL_REL)
    assert (cw, cva, cr) == (hw, hva2, hr)
