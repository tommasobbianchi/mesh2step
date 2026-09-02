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
2. **Geometric overlay** -- where a golden ``.step`` was small enough to keep, our solid
   must share the golden's volume as completely as the golden shares its own. This is the
   "100% overlay" requirement, made measurable against the instrument's own noise floor
   rather than against an ideal the reference itself cannot reach. See ``OVERLAY_SLACK``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
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

# Boolean-overlay agreement, SELF-CALIBRATED against the identity case.
#
# The first version of this gate was `V(A and B) / V(A or B) >= 1 - 1e-9`, and it was wrong
# twice over. Measured on the golden solids compared with THEMSELVES -- the case that must
# score a perfect 1.0 by construction:
#
#   cube                 fuse    1000.000000   common    1000.000000   V    1000.000000
#   S09                  fuse   32496.957221   common   32496.957221   V   32496.999055
#   nonprismatic-control fuse    2016.000069   common    2016.000069   V    2016.000069
#   handle-lock          fuse       0.000000   common   16003.716329   V   16038.862197
#
# BRepAlgoAPI_Fuse of handle-lock's 194-face merged solid with itself yields an EMPTY
# compound, so the old denominator was zero and the assertion was unreachable by any
# correct implementation, the reference engine included. And S09's identity case already
# deviates by 1.3e-6, three orders above the old epsilon.
#
# Both are properties of OCCT's boolean operators on coincident geometry, not of the
# converter. So the gate now measures us against the instrument's own noise floor on the
# same fixture: our overlay with the golden must be at least as good as the golden's
# overlay with itself. That IS "100% overlay" stated honestly -- indistinguishable from the
# reference under the same measurement. The union is gone; only the intersection is used.
OVERLAY_SLACK = 1e-12

# If the identity case cannot even reach this, the boolean operator is not a usable
# instrument on that fixture and the test says so loudly rather than passing vacuously.
IDENTITY_FLOOR = 0.99

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


def overlay_ratio(a, b) -> float:
    """Shared volume as a fraction of the larger solid: 1.0 means they occupy the same space.

    Intersection only. The union is deliberately not used -- see OVERLAY_SLACK for the
    measurement showing BRepAlgoAPI_Fuse degenerating to an empty compound on coincident
    input.
    """
    common = BRepAlgoAPI_Common(a, b)
    common.Build()
    assert common.IsDone(), "boolean common failed"
    denominator = max(volume(a), volume(b))
    assert denominator > 0, "both solids have no volume"
    return volume(common.Shape()) / denominator


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

    # Calibrate on the identity case first: what does a PERFECT overlay score here?
    identity = overlay_ratio(theirs, read_shape(golden))
    assert identity >= IDENTITY_FLOOR, (
        f"{fixture}/{mode}: the boolean operator scores only {identity:.12f} on the golden "
        f"against itself, so it cannot measure overlay on this fixture at all"
    )

    ratio = overlay_ratio(ours, theirs)
    assert ratio >= identity - OVERLAY_SLACK, (
        f"{fixture}/{mode}: overlay {ratio:.12f} against the reference, but the reference "
        f"scores {identity:.12f} against itself -- short by {identity - ratio:.3e}"
    )
