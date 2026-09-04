"""Fail-to-Pass oracle for ``write_profile_dxf`` + the ``--dxf <dir>`` CLI flag.

The Python port must reproduce the reference engine's DXF emission byte-for-byte.
Ground truth is the two committed goldens (``tests/data/reference/handle-lock-comp0-*.dxf``),
captured from the reference binary and verified byte-identical across two runs::

    refs/stl2step/RUN.sh tests/data/corpus/handle-lock.stl -o /tmp/ref.step \
        --smooth --unify-angle 5 --dxf <outdir> --quiet

handle-lock is the only prismatic fixture in the corpus, so it is the whole F2P set
(Body11/Body28 are excluded -- 30-60 min each, neither prismatic).

The comparison is a byte comparison (``filecmp.cmp(shallow=False)``): the DXF header
carries the axis and the cap levels at full float precision, and the entities carry
every fitted coordinate at 16 significant figures, so the format -- not just the
geometry -- is part of the contract. On mismatch the test reports the first differing
line number and both lines, because a bare ``a == b`` on 3686 bytes is undebuggable.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "data" / "corpus"
REFERENCE = ROOT / "tests" / "data" / "reference"

STL = CORPUS / "handle-lock.stl"
GOLDENS = (
    REFERENCE / "handle-lock-comp0-slab0.dxf",
    REFERENCE / "handle-lock-comp0-slab1.dxf",
)


def _first_diff_line(want: bytes, got: bytes) -> str:
    want_lines = want.split(b"\n")
    got_lines = got.split(b"\n")
    for i, (w, g) in enumerate(zip(want_lines, got_lines, strict=False), start=1):
        if w != g:
            return f"line {i}:\n  reference: {w!r}\n  ours:      {g!r}"
    if len(want_lines) != len(got_lines):
        return f"line count differs: reference {len(want_lines)} vs ours {len(got_lines)}"
    return ""


def test_dxf_byte_identical(tmp_path):
    dxf_dir = tmp_path / "dxf"
    out = dxf_dir / "out.step"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mesh2step.cli",
            str(STL),
            "-o",
            str(out),
            "--engine",
            "trueform",
            "--unify-angle",
            "5",
            "--dxf",
            str(dxf_dir),
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    match = re.search(r"RESULT (\{.*\})", proc.stdout)
    assert match, (
        f"mesh2step emitted no RESULT line for {STL.name}\n"
        f"stdout: {proc.stdout[-1500:]}\nstderr: {proc.stderr[-1500:]}"
    )

    for golden in GOLDENS:
        produced = dxf_dir / golden.name
        assert produced.exists(), (
            f"--dxf did not produce {golden.name}; "
            f"dir has {sorted(p.name for p in dxf_dir.iterdir())}"
        )
        want = golden.read_bytes()
        got = produced.read_bytes()
        assert got == want, (
            f"{golden.name} is not byte-identical to the reference:\n"
            f"{_first_diff_line(want, got)}"
        )
