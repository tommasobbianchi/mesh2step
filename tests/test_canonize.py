"""The detector that finds circles a faceted STEP lost."""

import math

import numpy as np
import pytest
import trimesh

from mesh2step.canonize import _fit_circle, find_circles
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


def _ring(n, radius, wobble=0.0, phase_bunch=0.0):
    """n points on a circle. `wobble` alternates the radius; `phase_bunch` crowds
    them to one side, so the chords stop being uniform."""
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        t += phase_bunch * math.sin(t)
        r = radius + (wobble if i % 2 else -wobble)
        pts.append([r * math.cos(t), r * math.sin(t), 0.0])
    return np.array(pts)


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


def test_small_radii_fit_as_well_as_large_ones(tmp_path):
    # The planarity gate is an absolute distance, not a ratio: a 1.2mm rim and a
    # 24.65mm rim must both be recognised at the same tolerance. The ratio form
    # rejected the small one and cost four bolt-hole rims on a real lid.
    for radius in (1.2, 24.65):
        stl = tmp_path / f"c{radius}.stl"
        trimesh.creation.cylinder(radius=radius, height=6, sections=96).export(str(stl))
        step = tmp_path / f"c{radius}.step"
        convert_native(stl, step, engine="verbatim", no_unify=True)
        got = [c.radius for c in find_circles(step)]
        assert got, f"r={radius} rims not found"
        assert any(abs(g - radius) < 0.01 for g in got), f"r={radius} mis-fitted: {got}"


def test_fit_accepts_a_tessellated_circle():
    fit = _fit_circle(_ring(96, 12.0), 0.05)
    assert fit is not None
    radius, _centre, _axis, residual, _span = fit
    assert abs(radius - 12.0) < 1e-6 and residual < 1e-9


def test_fit_accepts_wobble_that_stays_inside_tolerance():
    # A ring wobbling +-0.04mm IS a circle to a 0.05mm tolerance; refusing it would
    # make the tolerance argument meaningless. It is not one at 0.01mm.
    assert _fit_circle(_ring(48, 12.0, wobble=0.04), 0.05) is not None
    assert _fit_circle(_ring(48, 12.0, wobble=0.04), 0.01) is None


def test_fit_rejects_a_ring_whose_points_are_bunched():
    # Every point sits exactly on the circle, so the residual is zero and residual
    # alone accepts it. A tessellated circle also has near-equal chords and a
    # near-constant turn; this does not. Measured on 57 real CAD parts, that
    # distinction cut spurious loops from 61 to 45 with no loss of recall.
    assert _fit_circle(_ring(64, 12.0, phase_bunch=0.9), 0.05) is None
