"""Grouping rims into the cylinder bands a rebuild can replace."""

import numpy as np
import trimesh

from mesh2step.native import convert_native
from mesh2step.rebuild import find_bands


def _faceted(mesh, tmp_path, name):
    stl = tmp_path / f"{name}.stl"
    mesh.export(str(stl))
    step = tmp_path / f"{name}.step"
    convert_native(stl, step, engine="verbatim", no_unify=True)
    return step


def test_one_cylinder_is_one_band(tmp_path):
    step = _faceted(trimesh.creation.cylinder(radius=8, height=15, sections=96),
                    tmp_path, "cyl")
    bands = find_bands(step)
    assert len(bands) == 1, [(b.radius, b.height) for b in bands]
    b = bands[0]
    assert abs(b.radius - 8.0) < 1e-3
    assert abs(b.height - 15.0) < 1e-3
    assert abs(abs(b.axis[2]) - 1.0) < 1e-6
    assert len(b.face_indices) >= 90


def test_collinear_holes_in_opposite_walls_are_not_one_cylinder(tmp_path):
    """The trap from a real lid: a hole through one wall and a hole through the
    opposite wall share an axis and a radius exactly. Coaxial, equal radius, rims
    facing each other -- and nothing but air in between."""
    box = trimesh.creation.box((40, 20, 20))
    drill = trimesh.creation.cylinder(radius=2.5, height=80, sections=96)
    drill.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    part = trimesh.boolean.difference([box, drill])          # one bore, two walls
    step = _faceted(part, tmp_path, "walls")

    bands = find_bands(step)
    # the bore is a single continuous cylinder 40mm long; there must be no band
    # claiming a 40mm cylinder made of two 0-thickness walls with a gap between
    for b in bands:
        spanned = max(z for z in [b.height])
        assert spanned <= 40.0 + 1e-6
        assert len(b.face_indices) >= 8, f"band with too few faces: {b}"


def test_a_box_has_no_bands(tmp_path):
    step = _faceted(trimesh.creation.box((10, 10, 10)), tmp_path, "box")
    assert find_bands(step) == []
