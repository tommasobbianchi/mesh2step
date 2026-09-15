"""probe.classify: every builder outcome maps to the failure class that picks its retry ladder, and only a build that
meets the webapp gate is "pass"."""
import importlib.util
from pathlib import Path

PROBE = Path(__file__).resolve().parents[1] / "tools" / "feature_recon" / "probe.py"
spec = importlib.util.spec_from_file_location("probe", PROBE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

GOOD = {"solids": 1, "faces": 22, "free_edges": 0, "valid": True, "cylinders": 8, "planes": 13, "volume": 1.0,
        "mesh_volume": 1.0, "dv_pct": 0.00256, "dist_p95": 0.0, "diag": 171.07498}


def result(**over):
    return f"RESULT {dict(GOOD, **over)} radii [4.826, 6.35]\n"


def test_pass_and_unsound():
    assert probe.classify(0, result())[0] == "pass"
    assert probe.classify(0, result(valid=False))[0] == "unsound"
    assert probe.classify(0, result(free_edges=1))[0] == "unsound"
    assert probe.classify(0, result(dv_pct=1.5))[0] == "unsound"
    assert probe.classify(0, result(dist_p95=0.01 * 171.07498))[0] == "unsound"


def test_failure_classes():
    cases = {
        "FAIL mesh is open or non-manifold": "open",
        "FAIL 2 corners where the fitted surfaces do not meet (worst residual 6.18e-04)": "corners",
        "FAIL chain 0 between torus and plane: the surfaces do not meet there (residual 4.82e-03)": "chain",
        "FAIL 16 triangles lie on no fitted surface (freeform or unrecognised)": "unlabelled",
        "FAIL 3 free edges after sewing": "unsound",
    }
    for line, cls in cases.items():
        assert probe.classify(3, line + "\n")[0] == cls, line
    assert probe.classify(None, "")[0] == "timeout"


def test_every_ladder_class_is_reachable():
    assert set(probe.LADDERS) == {"open", "corners", "chain", "unlabelled", "unsound"}
