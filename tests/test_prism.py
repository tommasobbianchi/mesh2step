"""Fail-to-Pass oracle for ``detect_prismatic`` (Stage P, RULE 5.1).

The Python port must reproduce the reference engine's ``DIAG_PRISM`` verdict
exactly on every in-scope corpus fixture. Ground truth was measured from the
reference binary on 2026-09-04 and is regenerable with::

    STL2STEP_PRISM_DIAG=1 refs/stl2step/RUN.sh tests/data/corpus/<F>.stl \\
        -o /tmp/ref_<F>.step --smooth --unify-angle 5 --quiet 2>&1 | grep DIAG_PRISM

The test drives the SAME segmentation path ``convert.py`` uses for trueform
(weld/split -> ``build_mesh_view`` -> ``segment``), calls ``detect_prismatic`` per
clean component, and asserts every column of the measured table. Integer fields
(``ok``, ``failed_cond``, the five counts, ``cap_region``) must match exactly;
``tau_ax``/``tau_lvl`` and the level ``y`` values compare at ``rel=1e-3`` because
the reference prints them to 4 and 6 significant figures respectively.

Body11 and Body28 are deliberately excluded (30-60 min each, neither prismatic).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mesh2step import io_mesh, split
from mesh2step.refit import SegmentParams, build_mesh_view, detect_prismatic, segment

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "data" / "corpus"


def _sew_tolerance(verts) -> float:
    lo = verts.min(axis=0)
    hi = verts.max(axis=0)
    diag = float(np.sqrt(((hi - lo) ** 2).sum()))
    return min(max(1e-6, diag * 1e-5), 0.5)


def _prism_results(name: str):
    """Segment every clean component of ``name`` exactly as ``convert.py`` does and
    run ``detect_prismatic`` on each, in the deterministic (tri-count desc) order."""
    verts, tris = io_mesh.load_mesh(CORPUS / f"{name}.stl")
    sr = split.weld_and_split(verts, tris)
    lo = sr.verts.min(axis=0)
    hi = sr.verts.max(axis=0)
    diag = float(np.sqrt(((hi - lo) ** 2).sum()))
    sew_tol = _sew_tolerance(sr.verts)
    results = []
    for comp in sr.components:
        if not comp.is_clean:
            continue
        mv = build_mesh_view(comp, diag, weld_tol=0.0, sew_tol=sew_tol)
        rs = segment(mv, SegmentParams())
        assert rs is not None, f"{name}: segmentation returned None"
        results.append(detect_prismatic(mv, rs))
    return results


def _assert_verdict(lv, *, ok, failed_cond, n_cyl, n_plane, n_cap, n_lat, n_oblique,
                    tau_ax, tau_lvl):
    assert lv.ok == ok
    assert lv.failed_cond == failed_cond
    assert lv.n_cyl == n_cyl
    assert lv.n_plane == n_plane
    assert lv.n_cap == n_cap
    assert lv.n_lat == n_lat
    assert lv.n_oblique == n_oblique
    assert lv.tau_ax == pytest.approx(tau_ax, rel=1e-3)
    assert lv.tau_lvl == pytest.approx(tau_lvl, rel=1e-3)


def test_cube_prism():
    lv = _prism_results("cube")
    assert len(lv) == 1
    _assert_verdict(
        lv[0],
        ok=0, failed_cond=1, n_cyl=0, n_plane=6, n_cap=0, n_lat=0, n_oblique=0,
        tau_ax=1.000e-06, tau_lvl=5.000e-05,
    )
    assert lv[0].y == []
    assert lv[0].cap_region == []


def test_s09_prism():
    lv = _prism_results("S09")
    assert len(lv) == 2
    # The reference emits one DIAG_PRISM per component; the two S09 bodies are
    # distinguishable only by nPlane (6 vs 22), so match as a multiset.
    planes = sorted(r.n_plane for r in lv)
    assert planes == [6, 22]
    for r in lv:
        _assert_verdict(
            r,
            ok=0, failed_cond=1, n_cyl=0, n_plane=r.n_plane, n_cap=0, n_lat=0, n_oblique=0,
            tau_ax=1.000e-06, tau_lvl=7.297e-05,
        )
        assert r.y == []
        assert r.cap_region == []


def test_nonprismatic_control_prism():
    lv = _prism_results("nonprismatic-control")
    assert len(lv) == 1
    _assert_verdict(
        lv[0],
        ok=0, failed_cond=3, n_cyl=2, n_plane=2, n_cap=1, n_lat=0, n_oblique=1,
        tau_ax=1.111e-05, tau_lvl=5.000e-05,
    )
    assert lv[0].y == []
    assert lv[0].cap_region == []


def test_handle_lock_prism():
    lv = _prism_results("handle-lock")
    assert len(lv) == 1
    r = lv[0]
    _assert_verdict(
        r,
        ok=1, failed_cond=0, n_cyl=15, n_plane=13, n_cap=3, n_lat=10, n_oblique=0,
        tau_ax=5.536e-05, tau_lvl=7.820e-05,
    )
    assert r.cap_region == [0, 1, 2]
    assert len(r.y) == 3
    assert r.y == pytest.approx([-288.825734, -280.450731, -277.625728], rel=1e-3)
