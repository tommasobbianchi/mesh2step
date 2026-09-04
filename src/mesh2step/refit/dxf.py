"""DXF R12 serializer for a fitted 2D profile — port of
``refs/stl2step/src/dxf_export.cpp`` (P4). Write-only; never consulted by the
engine; no geometry decisions.

This is a TRANSCRIPTION, not a reimplementation: every helper carries the
``dxf_export.cpp`` line it was copied from. Float formatting is part of the
contract — ``fmtG16`` is C++ ``setprecision(16)`` defaultfloat, which is Python
``format(v, ".16g")`` (verified byte-identical on the golden corpus). Do not
substitute Python defaults or ``repr``.

2D points are ``numpy`` shape-(2,) float64 arrays (``ProfSeg.a/b/center``), the
axis is a shape-(3,) float64 array (``PrismLevels.axis``), matching ``profile.py``
/ ``prism.py`` conventions.
"""
from __future__ import annotations

import math

_K_PI = math.acos(-1.0)  # dxf_export.cpp:18  acos(-1.0)
_K_TWO_PI = 2.0 * _K_PI  # dxf_export.cpp:20  twoPi()


def _fmt_g16(v: float) -> str:  # fmtG16 (dxf_export.cpp:40)
    return format(v, ".16g")


def _append_line(s: list, t: str) -> None:  # appendLine (dxf_export.cpp:44)
    s.append(t)
    s.append("\n")


def _append_int(s: list, v: int) -> None:  # appendInt (dxf_export.cpp:48)
    _append_line(s, str(v))


def _append_num(s: list, v: float) -> None:  # appendNum (dxf_export.cpp:53)
    if v == 0.0:
        _append_line(s, "0")
        return
    t = _fmt_g16(v)
    if t == "-0" or t == "-0.0":
        _append_line(s, "0")
        return
    _append_line(s, t)


def _pair_s(s: list, code: int, val: str) -> None:  # pairS (dxf_export.cpp:63)
    _append_int(s, code)
    _append_line(s, val)


def _pair_i(s: list, code: int, val: int) -> None:  # pairI (dxf_export.cpp:67)
    _append_int(s, code)
    _append_int(s, val)


def _pair_d(s: list, code: int, val: float) -> None:  # pairD (dxf_export.cpp:71)
    _append_int(s, code)
    _append_num(s, val)


def _layer_for(loop, seg) -> str:  # layerFor (dxf_export.cpp:76)
    if seg.declined_ambiguous:
        return "DECLINED"
    if loop.outer:
        return "OUTER"
    return "HOLES"


def _emit_line(s: list, layer: str, x0, y0, x1, y1) -> None:  # emitLine (dxf_export.cpp:83)
    _pair_s(s, 0, "LINE")
    _pair_s(s, 8, layer)
    _pair_d(s, 10, x0)
    _pair_d(s, 20, y0)
    _pair_d(s, 30, 0.0)
    _pair_d(s, 11, x1)
    _pair_d(s, 21, y1)
    _pair_d(s, 31, 0.0)


def _emit_circle(s: list, layer: str, cx, cy, r) -> None:  # emitCircle (dxf_export.cpp:92)
    _pair_s(s, 0, "CIRCLE")
    _pair_s(s, 8, layer)
    _pair_d(s, 10, cx)
    _pair_d(s, 20, cy)
    _pair_d(s, 30, 0.0)
    _pair_d(s, 40, r)


def _rad_to_dxf_deg(rad: float) -> float:  # radToDxfDeg (dxf_export.cpp:24)
    return rad * (180.0 / _K_PI)


def _wrap_dxf_deg(deg: float) -> float:  # wrapDxfDeg (dxf_export.cpp:29)
    turn = 360.0
    deg = math.fmod(deg, turn)
    if deg < 0.0:
        deg += turn
    return deg


def _is_full_turn(phi: float) -> bool:  # isFullTurn (dxf_export.cpp:36)
    t = _K_TWO_PI
    bound = 1e-12 * t
    ap = math.fabs(phi)
    return math.fabs(ap - t) <= bound or ap >= t - bound


def _emit_arc(s: list, layer: str, seg) -> None:  # emitArc (dxf_export.cpp:103)
    cx = seg.center[0]
    cy = seg.center[1]
    ang_a = math.atan2(seg.a[1] - cy, seg.a[0] - cx)
    start = _rad_to_dxf_deg(ang_a)
    sweep = _rad_to_dxf_deg(math.fabs(seg.phi))
    if not seg.ccw:
        sweep = -sweep
    end = start + sweep
    # DXF ARC is always CCW from 50 to 51; a CW segment swaps the group-50/51 ends.
    if not seg.ccw:
        start, end = end, start
    _pair_s(s, 0, "ARC")
    _pair_s(s, 8, layer)
    _pair_d(s, 10, cx)
    _pair_d(s, 20, cy)
    _pair_d(s, 30, 0.0)
    _pair_d(s, 40, seg.r)
    _pair_d(s, 50, _wrap_dxf_deg(start))
    _pair_d(s, 51, _wrap_dxf_deg(end))


def _emit_layer(s: list, name: str, color: int) -> None:  # emitLayer (dxf_export.cpp:121)
    _pair_s(s, 0, "LAYER")
    _pair_s(s, 2, name)
    _pair_i(s, 70, 0)
    _pair_i(s, 62, color)
    _pair_s(s, 6, "CONTINUOUS")


def _count_declined(profile) -> int:  # countDeclined (dxf_export.cpp:130)
    n = 0
    for loop in profile.loops:
        for seg in loop.segs:
            if seg.declined_ambiguous:
                n += 1
    return n


def _build_dxf(profile, lv) -> str:  # buildDxf (dxf_export.cpp:139)
    y0 = 0.0
    y1 = 0.0
    if profile.slab >= 0 and profile.slab + 1 < len(lv.y):
        y0 = lv.y[profile.slab]
        y1 = lv.y[profile.slab + 1]
    n_dec = _count_declined(profile)

    s = []
    _pair_s(s, 0, "SECTION")
    _pair_s(s, 2, "HEADER")
    _pair_s(s, 9, "$ACADVER")
    _pair_s(s, 1, "AC1009")
    _pair_s(s, 9, "$INSUNITS")
    _pair_i(s, 70, 4)  # millimetres
    _pair_s(s, 9, "$PROJECTNAME")
    _pair_s(s, 1, f"slab={profile.slab} y0={_fmt_g16(y0)} y1={_fmt_g16(y1)}")
    _pair_s(s, 0, "ENDSEC")

    _pair_s(s, 999, "stl2step profile dxf")
    _pair_s(s, 999, f"declined={n_dec}")
    _pair_s(
        s,
        999,
        f"axis={_fmt_g16(lv.axis[0])},{_fmt_g16(lv.axis[1])},{_fmt_g16(lv.axis[2])}",
    )

    _pair_s(s, 0, "SECTION")
    _pair_s(s, 2, "TABLES")
    _pair_s(s, 0, "TABLE")
    _pair_s(s, 2, "LAYER")
    _pair_i(s, 70, 3)
    _emit_layer(s, "OUTER", 7)
    _emit_layer(s, "HOLES", 1)
    _emit_layer(s, "DECLINED", 2)
    _pair_s(s, 0, "ENDTAB")
    _pair_s(s, 0, "ENDSEC")

    _pair_s(s, 0, "SECTION")
    _pair_s(s, 2, "ENTITIES")
    for loop in profile.loops:
        for seg in loop.segs:
            layer = _layer_for(loop, seg)
            if seg.declined_ambiguous or not seg.is_arc:
                _emit_line(s, layer, seg.a[0], seg.a[1], seg.b[0], seg.b[1])
                continue
            if _is_full_turn(seg.phi):
                _emit_circle(s, layer, seg.center[0], seg.center[1], seg.r)
                continue
            _emit_arc(s, layer, seg)
    _pair_s(s, 0, "ENDSEC")
    _pair_s(s, 0, "EOF")
    return "".join(s)


def write_profile_dxf(profile, lv, path: str) -> bool:  # writeProfileDxf (dxf_export.cpp:230)
    """Serialize one fitted profile to a DXF R12 file. Returns ``False`` when
    ``path`` is empty; otherwise writes the body as ASCII bytes and returns
    ``True`` (the reference discards the stream state, so any non-empty path is
    a successful write)."""
    if not path:
        return False
    body = _build_dxf(profile, lv)
    with open(path, "wb") as f:
        f.write(body.encode("ascii"))
    return True
