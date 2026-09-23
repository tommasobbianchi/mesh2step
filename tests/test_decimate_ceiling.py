"""A reduction the user asked for must land under the ceiling, or it is a dead end.

Before this, "planar" on a scanned surface removed 2 triangles out of 327,680 and handed the
user back a mesh Convert still refused, with nothing left in the panel to try.
"""
import numpy as np
import pytest
import trimesh

from mesh2step.decimate import decimate_mesh

CEILING = 20_000        # the real one is 118k; a small one keeps the test quick and says the same thing


@pytest.fixture(scope="module")
def scan_like():
    """Jittered sphere: nothing is coplanar, so the planar arm cannot help -- a real 3D scan."""
    rng = np.random.default_rng(0)
    m = trimesh.creation.icosphere(subdivisions=5, radius=10.0)
    return np.asarray(m.vertices) + rng.normal(0, 0.02, (len(m.vertices), 3)), np.asarray(m.faces)


def test_planar_alone_cannot_promise_a_count(scan_like):
    v, t = scan_like
    assert decimate_mesh(v, t, mode="planar").n_faces_after > CEILING


# keep=0.99 matters: a ratio the user set too gently must still be finished off by the ceiling.
@pytest.mark.parametrize("mode,keep", [("planar", 0.25), ("ratio", 0.99)])
def test_a_requested_reduction_lands_under_the_ceiling(scan_like, mode, keep):
    v, t = scan_like
    r = decimate_mesh(v, t, mode=mode, keep=keep, max_tris=CEILING)
    assert r.n_faces_after <= CEILING, f"{mode} returned {r.n_faces_after}"
    assert r.fit_passes >= 1                       # it took the extra collapse, and says so
    assert abs(r.dv_pct) < 5.0, r.dv_pct           # still the same object, not a blob


def test_a_mesh_already_under_the_ceiling_is_untouched(scan_like):
    v, t = scan_like
    plain = decimate_mesh(v, t, mode="ratio", keep=0.05)
    capped = decimate_mesh(v, t, mode="ratio", keep=0.05, max_tris=CEILING)
    assert plain.n_faces_after == capped.n_faces_after <= CEILING
    assert capped.fit_passes == 0                  # no second pass when the first one sufficed
