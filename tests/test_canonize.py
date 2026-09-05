"""The detector that finds circles a faceted STEP lost."""

import pytest
import trimesh

from mesh2step.canonize import find_circles
from mesh2step.native import convert_native


@pytest.fixture(scope="module")
def cyl96_step(tmp_path_factory):
    # 96 segments -> 3.75 deg between facets, under the engine's 5 deg cylinder
    # seed band, so trueform emits 96 planar strips and loses both rims.
    d = tmp_path_factory.mktemp("canon")
    stl = d / "cyl96.stl"
    trimesh.creation.cylinder(radius=10, height=20, sections=96).export(str(stl))
    step = d / "cyl96.step"
    res = convert_native(stl, step, engine="trueform")
    assert res["smoothCylinders"] == 0, "fixture must be the LOST case"
    return step


def test_finds_both_rims_of_a_lost_cylinder(cyl96_step):
    circles = find_circles(cyl96_step)
    assert len(circles) == 2, [c.radius for c in circles]
    for c in circles:
        assert abs(c.radius - 10.0) < 1e-3
        assert c.segments >= 90
        assert c.max_residual_mm < 1e-3
    assert abs(abs(circles[0].centre[2] - circles[1].centre[2]) - 20.0) < 1e-6


def test_a_cube_has_no_circles(tmp_path):
    stl = tmp_path / "cube.stl"
    trimesh.creation.box((10, 10, 10)).export(str(stl))
    step = tmp_path / "cube.step"
    convert_native(stl, step, engine="trueform")
    assert find_circles(step) == []


def test_tolerance_rejects_a_coarse_polygon(tmp_path):
    # An 8-sided prism is a design, not a lost circle: its radial residual against
    # the best-fit circle is large, so a tight tolerance must refuse it.
    stl = tmp_path / "oct.stl"
    trimesh.creation.cylinder(radius=10, height=20, sections=8).export(str(stl))
    step = tmp_path / "oct.step"
    convert_native(stl, step, engine="trueform", no_unify=True)
    assert find_circles(step, tol_mm=0.05) == []
