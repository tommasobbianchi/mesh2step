"""Fail-to-Pass oracle for ``slice_profiles`` + ``fit_profile`` (Stage P2).

The Python port must reproduce the reference engine's ``DIAG_PROFILE`` output for
the handle-lock fixture exactly. Ground truth was measured from the reference
binary and committed as ``tests/data/reference/handle-lock.profile.txt`` — the test
parses that file and never retypes its numbers.

Drives the same segmentation path as ``test_prism.py`` (weld/split ->
``build_mesh_view`` -> ``segment`` -> ``detect_prismatic``), then slices and fits
each slab and asserts every column of the measured table. Integer fields
(``outer``/``nSeg``/``nLine``/``nArc``/``nDecl``, ``kind``/``decl``) must match
exactly; ``area``/``R``/``phi`` compare at ``rel=1e-6`` with an ``abs=5e-7`` floor (the golden's own 6-decimal resolution)
because the reference prints six decimals — a six-decimal rounding (up to 5e-7) is
coarser than ``rel=1e-6`` for sub-unit ``phi`` values (e.g. ``phi=0.174520`` whose
true value is ``0.174520273715``). The floor is exactly the golden's resolution,
never a loosening of the oracle.
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
    detect_prismatic,
    fit_profile,
    segment,
    slice_profiles,
)
from mesh2step.refit.prism import PrismTols

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "data" / "corpus"
GOLDEN = ROOT / "tests" / "data" / "reference" / "handle-lock.profile.txt"

LOOP_RE = re.compile(
    r"slab=(\d+) loop=(\d+) outer=(\d+) nSeg=(\d+) nLine=(\d+) nArc=(\d+) "
    r"nDecl=(\d+) area=([0-9.eE+-]+)"
)
SEG_RE = re.compile(
    r"seg slab=(\d+) loop=(\d+) i=(\d+) kind=(\w+) R=([0-9.eE+-]+) "
    r"phi=([0-9.eE+-]+) decl=(\d+)"
)


def _sew_tolerance(verts) -> float:
    lo = verts.min(axis=0)
    hi = verts.max(axis=0)
    diag = float(np.sqrt(((hi - lo) ** 2).sum()))
    return min(max(1e-6, diag * 1e-5), 0.5)


def _profile_stage():
    """(mv, rs, lv, pt) for the prismatic handle-lock component.

    Mirrors the reference wiring in refit_prism_build.cpp:994-1023: ``detect_prismatic``
    derives its tolerances on an internal copy, while ``slice_profiles``/``fit_profile``
    receive the still-zeroed ``PrismTols``.
    """
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
        pt = PrismTols()
        lv = detect_prismatic(mv, rs, pt)
        if lv.ok:
            return mv, rs, lv, pt
    pytest.fail("handle-lock has no prismatic component")


def _parse_golden():
    loops = []
    cur = None
    segs = []
    for line in GOLDEN.read_text().splitlines():
        if line.startswith("DIAG_PROFILE  seg"):
            m = SEG_RE.search(line)
            segs.append(
                {
                    "i": int(m.group(3)),
                    "kind": m.group(4),
                    "R": float(m.group(5)),
                    "phi": float(m.group(6)),
                    "decl": int(m.group(7)),
                }
            )
        else:
            if cur is not None:
                loops.append((cur, segs))
            m = LOOP_RE.search(line)
            cur = {
                "slab": int(m.group(1)),
                "loop": int(m.group(2)),
                "outer": int(m.group(3)),
                "nSeg": int(m.group(4)),
                "nLine": int(m.group(5)),
                "nArc": int(m.group(6)),
                "nDecl": int(m.group(7)),
                "area": float(m.group(8)),
            }
            segs = []
    if cur is not None:
        loops.append((cur, segs))
    return loops


def test_handle_lock_profile():
    mv, rs, lv, pt = _profile_stage()
    profiles = slice_profiles(mv, rs, lv, pt)
    assert len(profiles) == 2, f"expected 2 slabs, got {len(profiles)}"

    total_decl = 0
    for prof in profiles:
        total_decl += fit_profile(mv, pt, prof)

    golden = _parse_golden()
    flat = [
        (prof.slab, li, loop)
        for prof in profiles
        for li, loop in enumerate(prof.loops)
    ]
    assert len(flat) == len(golden), f"{len(flat)} loops vs {len(golden)} golden"

    golden_total_decl = sum(h["nDecl"] for h, _ in golden)
    assert total_decl == golden_total_decl

    for (slab, li, loop), (hdr, gsegs) in zip(flat, golden, strict=True):
        assert slab == hdr["slab"]
        assert li == hdr["loop"]
        assert int(loop.outer) == hdr["outer"]
        assert len(loop.segs) == hdr["nSeg"]
        n_arc = sum(1 for s in loop.segs if s.is_arc)
        n_line = len(loop.segs) - n_arc
        n_decl = sum(1 for s in loop.segs if s.declined_ambiguous)
        assert n_line == hdr["nLine"]
        assert n_arc == hdr["nArc"]
        assert n_decl == hdr["nDecl"]
        assert loop.area == pytest.approx(hdr["area"], rel=1e-6, abs=5e-7)
        assert len(loop.segs) == len(gsegs)
        for s, g in zip(loop.segs, gsegs, strict=True):
            kind = "arc" if s.is_arc else "line"
            assert kind == g["kind"]
            assert int(s.declined_ambiguous) == g["decl"]
            assert s.r == pytest.approx(g["R"], rel=1e-6, abs=5e-7)
            assert s.phi == pytest.approx(g["phi"], rel=1e-6, abs=5e-7)
