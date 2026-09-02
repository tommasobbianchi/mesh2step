#!/usr/bin/env python3
"""Capture the stl2step reference engine's output over the corpus as golden fixtures.

This is the ORACLE for the v2 parity work: mesh2step must reproduce what this records.
It is deliberately a separate, hand-run tool rather than part of the test suite -- the
reference binary needs OCCT from the FreeCAD snap (see refs/stl2step/BUILD-NOTES.md)
and must not be a test-time dependency.

    python3 tools/capture_reference.py            # refresh every fixture, both engines
    python3 tools/capture_reference.py cube S09   # refresh a subset

Writes, per fixture and engine mode:
  tests/data/reference/<name>.<mode>.json   the RESULT payload (always)
  tests/data/reference/<name>.<mode>.step   the solid itself (small fixtures only)

A faceted STEP of a 62k-triangle mesh is ~149 MB, so the .step golden is kept only for
fixtures under GOLDEN_STEP_MAX_TRIS. Above that the JSON invariants are the contract and
the geometric overlay check is skipped -- tests/test_parity.py reports which is which
rather than silently weakening.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "data" / "corpus"
REFERENCE = ROOT / "tests" / "data" / "reference"
ENGINE = ROOT / "refs" / "stl2step" / "RUN.sh"

# Above this the golden .step is too large to keep in git; JSON invariants carry the contract.
GOLDEN_STEP_MAX_TRIS = 1000

MODES = ("verbatim", "trueform")

# stl2step defaults to --unify-angle 0.001; mesh2step's --merge-coplanar defaults to 5deg.
# The parity suite drives both at 5deg, which is where the two engines were measured to
# agree exactly (632 == 632 faces on bucket, 718 == 718 on the bottom bracket).
UNIFY_ANGLE_DEG = "5"


def capture(stl: Path, mode: str) -> dict:
    """Run the reference engine once and return its RESULT payload, enriched."""
    name = stl.stem
    step_out = REFERENCE / f"{name}.{mode}.step"
    cmd = [
        str(ENGINE),
        str(stl),
        "-o",
        str(step_out),
        "--engine",
        mode,
        "--unify-angle",
        UNIFY_ANGLE_DEG,
        "--quiet",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    match = re.search(r"RESULT (\{.*\})", proc.stdout)
    if not match:
        raise RuntimeError(f"{name}/{mode}: no RESULT line\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}")
    result = json.loads(match.group(1))

    # Absolute paths are this host's; the contract is the geometry, not where it lived.
    for key in ("input", "output"):
        result[key] = Path(result[key]).name
    result["_reference"] = {
        "engine": "stl2step 1.1.0 (BlinkingSun @ 7cf77a2)",
        "mode": mode,
        "unify_angle_deg": float(UNIFY_ANGLE_DEG),
        "exit_code": proc.returncode,
    }

    keep_step = result["triangles"] <= GOLDEN_STEP_MAX_TRIS
    result["_reference"]["golden_step"] = keep_step
    if not keep_step and step_out.exists():
        step_out.unlink()
    return result


def main(argv: list[str]) -> int:
    if not ENGINE.exists():
        print(f"reference engine missing: {ENGINE}\nsee refs/stl2step/BUILD-NOTES.md", file=sys.stderr)
        return 1
    REFERENCE.mkdir(parents=True, exist_ok=True)

    wanted = set(argv[1:])
    fixtures = sorted(p for p in CORPUS.glob("*.stl") if not wanted or p.stem in wanted)
    if not fixtures:
        print(f"no fixtures matched {wanted or 'ANY'} in {CORPUS}", file=sys.stderr)
        return 1

    failures = 0
    for stl in fixtures:
        for mode in MODES:
            try:
                result = capture(stl, mode)
            except Exception as exc:  # noqa: BLE001 - a tool, not a library: report and continue
                print(f"FAIL {stl.stem}/{mode}: {exc}", file=sys.stderr)
                failures += 1
                continue
            out = REFERENCE / f"{stl.stem}.{mode}.json"
            out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
            print(
                f"{stl.stem:24s} {mode:9s} solids={result['solids']} "
                f"faces={result['facesBeforeUnify']}->{result['facesAfterUnify']} "
                f"wt={result['watertight']} step={'yes' if result['_reference']['golden_step'] else 'no'}"
            )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
