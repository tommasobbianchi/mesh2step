"""A volume move no analytic rebuild accounts for is a state-2 case.

P48 measured it: L07_flanged_bushing_recon emits 258 faces, ALL planes, against a truth
holding 32 non-planar faces, and 245 of those planes absorb mesh facets deviating up to
1.99 degrees -- pressed against the engine's absolute 2.0 degree near-flat gate. Surface
area barely moves (8.5595 -> 8.5548) while VOLUME moves 1.70 %: facets re-projected onto a
fitted plane. Silent. The state-2 contract covers flattened cones exactly as it covers
designed octagons: keep what the engine produced, and say what happened with the numbers.
"""

import json
import pathlib
import subprocess

import pytest
from conftest import deployed_engine

CORPUS = pathlib.Path("/tmp/awk/cadbench")
ENGINE = deployed_engine()


def _convert(stl, out):
    p = subprocess.run([ENGINE, str(stl), "-o", str(out), "--engine", "trueform"],
                       capture_output=True, text=True, timeout=900)
    res = [x for x in p.stdout.splitlines() if x.startswith("RESULT")]
    assert res, p.stdout[-2000:]
    return json.loads(res[-1][7:])


@pytest.mark.skipif(not (CORPUS / "L07_flanged_bushing_recon_normal.stl").exists(),
                    reason="corpus not present")
def test_flattened_curvature_is_reported_with_its_numbers(tmp_path):
    from mesh2step.intent import unaccounted_volume_move

    stl = CORPUS / "L07_flanged_bushing_recon_normal.stl"
    step = tmp_path / "bushing.step"
    stats = _convert(stl, step)

    finding = unaccounted_volume_move(stl, step, stats)
    assert finding is not None, "a 1.7% move with zero rebuilt cylinders must be reported"
    assert finding.volume_delta_pct == pytest.approx(1.7021, abs=0.05), finding
    assert finding.explained_by_rebuild == pytest.approx(0.0, abs=1e-9), finding
    text = finding.message.lower()
    assert "1.7" in finding.message, finding.message
    assert "no analytic rebuild" in text or "flatten" in text, finding.message


@pytest.mark.skipif(not (CORPUS / "L06_adapter_plate_normal.stl").exists(),
                    reason="corpus not present")
def test_a_legitimate_rebuild_delta_is_not_reported(tmp_path):
    """Control: adapter_plate's whole move IS accounted for by its 14 rebuilt cylinders."""
    from mesh2step.intent import unaccounted_volume_move

    stl = CORPUS / "L06_adapter_plate_normal.stl"
    step = tmp_path / "plate.step"
    stats = _convert(stl, step)
    assert unaccounted_volume_move(stl, step, stats) is None


@pytest.mark.skipif(not (CORPUS / "L07_flanged_bushing_recon_normal.stl").exists(),
                    reason="corpus not present")
def test_flattening_is_reported_even_when_the_volume_stays_silent(tmp_path):
    """The shape line, beside the volume line.

    A conical seat rebuilt as forty planes has very nearly the right VOLUME and the wrong
    SHAPE. P50 measured 18 corpus models flattening curvature, of which twelve move the
    volume by ~0 -- so a volume test alone covers the harm, not the phenomenon. This
    reports planar faces that absorbed facets whose normal spread is comparable to the
    model's own tessellation angle.
    """
    from mesh2step.intent import flattening_suspected

    stl = CORPUS / "L07_flanged_bushing_recon_normal.stl"
    step = tmp_path / "bushing_shape.step"
    _convert(stl, step)

    f = flattening_suspected(stl, step)
    assert f is not None, "258 planes absorbing facets up to 1.99 deg must be reported"
    assert f.faces_absorbing >= 100, f
    assert f.max_absorbed_deg == pytest.approx(2.0, abs=0.1), f
    assert "flatten" in f.message.lower(), f.message


@pytest.mark.skipif(not (CORPUS / "L06_adapter_plate_normal.stl").exists(),
                    reason="corpus not present")
def test_a_genuinely_planar_model_is_not_reported_as_flattened(tmp_path):
    """Control: adapter_plate's planes are planes, and its curvature IS rebuilt."""
    from mesh2step.intent import flattening_suspected

    stl = CORPUS / "L06_adapter_plate_normal.stl"
    step = tmp_path / "plate_shape.step"
    _convert(stl, step)
    assert flattening_suspected(stl, step) is None
