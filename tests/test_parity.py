"""Parity oracle: mesh2step v2 must reproduce the stl2step reference engine.

This suite is the ORACLE for the v2 work and is deliberately written against the CLI's
``RESULT {json}`` contract rather than the Python API -- the internals are being
restructured heavily, and a harness that moves with them proves nothing.

Golden fixtures live in ``tests/data/reference/`` and are produced by
``tools/capture_reference.py`` from the reference binary in ``refs/stl2step/``.
Regenerating them is a deliberate, reviewed act: a green run after silently
re-capturing the oracle is not evidence of anything.

Two levels of check, per fixture and engine mode:

1. **Invariant parity** -- the RESULT payload must agree field-for-field.
2. **Geometric overlay** -- where a golden ``.step`` was small enough to keep, no volume may
   lie in exactly one of the two solids. That empty symmetric difference IS the "100%
   overlay" requirement, stated so that it is measurable. See ``SYMDIFF_MAX``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "data" / "corpus"
REFERENCE = ROOT / "tests" / "data" / "reference"

# Volume agreement. The two engines integrate the same triangles with the same kernel,
# so the only legitimate difference is floating-point summation order.
VOLUME_REL_TOL = 1e-9

# "100% overlay", measured as an EMPTY SYMMETRIC DIFFERENCE:
#
#     ( V(ours \ theirs) + V(theirs \ ours) ) / max(V) == 0
#
# Two solids that each contain nothing the other lacks ARE the same solid. This is a
# stronger claim than any intersection ratio, and unlike a ratio it needs no per-fixture
# calibration, because the instrument reads exactly zero on the identity case.
#
# It replaces two earlier attempts, both defeated by OCCT's boolean operators rather than
# by any converter defect. Measured on the golden solids:
#
#   fixture                  V(A and B)/V   symdiff(self)   symdiff(0.999x)   symdiff(box)
#   cube.verbatim             1.000000000     0.000000000       0.002997001    0.875000000
#   S09.verbatim              0.999998713     0.000000000       0.033568619    0.996158008
#   S09.trueform              0.999999643     0.000000000       0.033597041    0.996158008
#   handle-lock.verbatim      0.997808706     0.000000000       0.971330551    1.007793570
#   handle-lock.trueform      0.999999999     0.000000000       0.088333556    1.007877076
#   nonprismatic.trueform     1.000000000     0.000000000       0.003757740    0.997519843
#
# The first gate was V(A and B)/V(A or B) >= 1-1e-9; BRepAlgoAPI_Fuse of handle-lock's
# 194-face solid WITH ITSELF returns an empty compound, so the denominator was zero and no
# implementation could pass. The second self-calibrated against the intersection ratio,
# which the middle column shows is neither 1.0 nor reproducible: S09 scores 0.999999643
# comparing the golden to a second read of itself, and 0.999998713 for a solid whose two
# set differences are both exactly zero -- provably the same solid, 9.3e-7 apart under an
# operator asked the same question twice.
#
# The symmetric difference has none of that scatter: exact zero on every fixture including
# the one where Fuse degenerates, and six orders of separation from a 0.1%-scaled copy.
SYMDIFF_MAX = 1e-9

# Fields whose agreement IS the parity claim. Compared with ==, no slack.
EXACT_FIELDS = (
    "triangles",
    "vertices",
    "components",
    "solids",
    "openShells",
    "facesBeforeUnify",
    "facesAfterUnify",
    "watertight",
)

# TrueForm-only. Includes the *reverted* counters on purpose: matching stl2step means
# declining on the same bodies it declines on, not inventing geometry where it does not.
SMOOTH_FIELDS = (
    "smoothPlanes",
    "smoothCylinders",
    "smoothFillets",
    "smoothDistinctRadii",
    "smoothRejected",
    "smoothFacetFaces",
    "facesAfterSmooth",
    "smoothSkippedComponents",
    "smoothBuiltPlanes",
    "smoothBuiltCylinders",
    "smoothBuiltFillets",
    "smoothBuiltComponents",
    "smoothRevertedComponents",
)


def _references() -> list[Path]:
    return sorted(REFERENCE.glob("*.json"))


def _case_id(path: Path) -> str:
    return path.stem  # "<fixture>.<mode>"


REFERENCE_CASES = _references()

pytestmark = pytest.mark.skipif(
    not REFERENCE_CASES,
    reason=f"no golden fixtures in {REFERENCE}; run tools/capture_reference.py",
)


def read_shape(path: Path):
    reader = STEPControl_Reader()
    assert reader.ReadFile(str(path)) == IFSelect_RetDone, f"cannot read {path}"
    reader.TransferRoots()
    shape = reader.OneShape()
    assert not shape.IsNull(), f"{path} read back as a null shape"
    return shape


def volume(shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _cut_volume(a, b) -> float:
    """Volume of a minus b."""
    cut = BRepAlgoAPI_Cut(a, b)
    cut.Build()
    assert cut.IsDone(), "boolean cut failed"
    return abs(volume(cut.Shape()))


def symmetric_difference(a, b) -> float:
    """Volume in exactly one of the two solids, as a fraction of the larger. 0 == identical."""
    denominator = max(volume(a), volume(b))
    assert denominator > 0, "both solids have no volume"
    return (_cut_volume(a, b) + _cut_volume(b, a)) / denominator


def run_mesh2step(stl: Path, out: Path, mode: str, unify_angle: float) -> tuple[dict, int]:
    """Drive the CLI exactly as tools/capture_reference.py drives the reference engine."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mesh2step.cli",
            str(stl),
            "-o",
            str(out),
            "--engine",
            mode,
            "--unify-angle",
            str(unify_angle),
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    match = re.search(r"RESULT (\{.*\})", proc.stdout)
    assert match, (
        f"mesh2step emitted no RESULT line for {stl.name}/{mode}\n"
        f"stdout: {proc.stdout[-1500:]}\nstderr: {proc.stderr[-1500:]}"
    )
    return json.loads(match.group(1)), proc.returncode


@pytest.fixture(scope="module")
def _cases():
    return {p.stem: json.loads(p.read_text()) for p in REFERENCE_CASES}


@pytest.mark.parametrize("ref_path", REFERENCE_CASES, ids=_case_id)
def test_result_invariants_match_reference(ref_path, tmp_path):
    """Every RESULT field that defines the geometry must agree with stl2step exactly."""
    ref = json.loads(ref_path.read_text())
    fixture, mode = ref_path.stem.rsplit(".", 1)
    stl = CORPUS / f"{fixture}.stl"
    assert stl.exists(), f"corpus fixture missing: {stl}"

    got, _exit = run_mesh2step(
        stl, tmp_path / "out.step", mode, ref["_reference"]["unify_angle_deg"]
    )

    mismatched = {f: (ref[f], got.get(f)) for f in EXACT_FIELDS if ref[f] != got.get(f)}
    if mode == "trueform":
        mismatched |= {
            f: (ref[f], got.get(f))
            for f in SMOOTH_FIELDS
            if f in ref and ref[f] != got.get(f)
        }
    assert not mismatched, f"{fixture}/{mode} diverges from stl2step: {mismatched}"

    assert got["meshVolumeMM3"] == pytest.approx(ref["meshVolumeMM3"], rel=VOLUME_REL_TOL)


@pytest.mark.parametrize("ref_path", REFERENCE_CASES, ids=_case_id)
def test_exit_code_matches_reference(ref_path, tmp_path):
    """0 clean / 2 written-with-warnings / 1 failed -- the same verdict on the same mesh."""
    ref = json.loads(ref_path.read_text())
    fixture, mode = ref_path.stem.rsplit(".", 1)
    _got, exit_code = run_mesh2step(
        CORPUS / f"{fixture}.stl",
        tmp_path / "out.step",
        mode,
        ref["_reference"]["unify_angle_deg"],
    )
    assert exit_code == ref["_reference"]["exit_code"]


@pytest.mark.parametrize(
    "ref_path",
    [p for p in REFERENCE_CASES if json.loads(p.read_text())["_reference"]["golden_step"]],
    ids=_case_id,
)
def test_geometric_overlay_is_total(ref_path, tmp_path):
    """The 100% overlay requirement, made measurable as a boolean volume ratio."""
    ref = json.loads(ref_path.read_text())
    fixture, mode = ref_path.stem.rsplit(".", 1)
    golden = REFERENCE / f"{fixture}.{mode}.step"
    assert golden.exists(), f"golden step missing: {golden}"

    out = tmp_path / "out.step"
    run_mesh2step(CORPUS / f"{fixture}.stl", out, mode, ref["_reference"]["unify_angle_deg"])

    ours, theirs = read_shape(out), read_shape(golden)
    v_ours, v_theirs = volume(ours), volume(theirs)
    assert v_ours == pytest.approx(v_theirs, rel=VOLUME_REL_TOL), (
        f"{fixture}/{mode}: volume {v_ours} vs reference {v_theirs}"
    )

    # Instrument check first: the golden against a second read of itself must read exactly
    # zero. If it does not, the boolean operator is broken on this fixture and the test says
    # so rather than passing -- or failing -- vacuously.
    identity = symmetric_difference(theirs, read_shape(golden))
    assert identity <= SYMDIFF_MAX, (
        f"{fixture}/{mode}: the golden scores {identity:.12f} against ITSELF, so the boolean "
        f"operator cannot measure this fixture at all"
    )

    symdiff = symmetric_difference(ours, theirs)
    assert symdiff <= SYMDIFF_MAX, (
        f"{fixture}/{mode}: {symdiff:.12f} of the volume lies in exactly one of the two "
        f"solids -- ours and the reference do not occupy the same space"
    )
