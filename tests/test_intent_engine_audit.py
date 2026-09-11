"""Class (a) lives in the C++, not here -- so audit what the engine already rebuilt.

P1/P2 (spec 0) established that a coarse prism is turned into a cylinder by the
native engine's Phase-B seed band before any Python sees it: an 8-gon r=20 h=20
comes back as smoothCylinders=1 with the volume of its circumscribed cylinder,
x1.1107, and neither --smooth-tol nor --smooth-angle changes that. The facets are
gone from the STEP, so `rebuild.py` cannot decline what it never sees.

What IS still available after a conversion is the pair (mesh, STEP). This module
compares them: every cylindrical face the engine emitted is measured back against
the facets it came from. Correcting it needs a fork change (see
.claude/loopspec/n5-seed-exclusion.spec.md); until then the contract is state 2 --
keep exactly what the engine emitted, and say what happened with the numbers.
"""

import pytest
import trimesh

from mesh2step.native import convert_native


def _convert(mesh, tmp_path, name, engine="trueform"):
    stl = tmp_path / f"{name}.stl"
    mesh.export(str(stl))
    step = tmp_path / f"{name}.step"
    stats = convert_native(stl, step, engine=engine)
    return stl, step, stats


def test_the_projects_ccf_octagon_is_flagged_with_its_numbers(tmp_path):
    """The archetype: +11.07% and no warning. r=20 h=20, 8 sides, 45 degrees/facet.

    Measured (P0): mesh 22627.417 = 2*sqrt(2)*400*20, STEP 25132.741 = pi*400*20,
    ratio 1.110721 = 2*pi/(8*sin 45). The corpus's real tessellated bands top out at
    theta = 13.85 degrees, so 45 degrees is not a tessellation at any tolerance the
    ground truth contains.
    """
    from mesh2step.intent import audit_engine_cylinders

    mesh = trimesh.creation.cylinder(radius=20.0, height=20.0, sections=8)
    stl, step, stats = _convert(mesh, tmp_path, "ccf_octagon")
    assert stats.get("smoothCylinders", stats.get("smooth_cylinders", 0)) >= 1, stats

    findings = [r for r in audit_engine_cylinders(stl, step) if r.flagged]
    assert findings, "the octagon must not pass silently"
    text = " ".join(f.message for f in findings)
    assert "8" in text, text
    assert "45" in text, text            # degrees per facet
    assert "20.00" in text or "20.0" in text, text
    assert "11" in text, text            # the volume delta, in percent


def test_a_real_tessellation_inside_the_seed_band_is_reported_but_not_flagged(tmp_path):
    """Control against crying wolf.

    The audit's domain is exactly the engine's seed band, theta in [5, 60] degrees: a
    96-facet cylinder is theta=3.75, BELOW the seed, so the engine leaves it faceted
    and there is no cylinder to audit at all (P1: 96-gon -> smoothCylinders = 0). The
    honest control is a band the engine really does rebuild and that really is a
    tessellation: 40 facets, theta=9, inside the corpus's real range (max 13.85).
    """
    from mesh2step.intent import audit_engine_cylinders

    mesh = trimesh.creation.cylinder(radius=20.0, height=20.0, sections=40)
    stl, step, _stats = _convert(mesh, tmp_path, "seeded_tessellation")

    rows = audit_engine_cylinders(stl, step)
    assert len(rows) == 1, [r.message for r in rows]
    assert rows[0].flagged is False, rows[0]
    assert rows[0].undecidable is False, rows[0]
    assert rows[0].sides == 40, rows[0]
    assert rows[0].turn_deg == pytest.approx(9.0, abs=0.3), rows[0]


def test_the_finding_carries_the_measured_volume_delta(tmp_path):
    """A warning without the number is not actionable; this pins the number."""
    from mesh2step.intent import audit_engine_cylinders

    mesh = trimesh.creation.cylinder(radius=20.0, height=20.0, sections=8)
    stl, step, _stats = _convert(mesh, tmp_path, "ccf_delta")

    findings = audit_engine_cylinders(stl, step)
    assert len(findings) == 1, [f.message for f in findings]
    f = findings[0]
    assert f.flagged is True, f
    assert f.sides == 8, f
    assert f.turn_deg == pytest.approx(45.0, abs=0.5), f
    assert f.radius == pytest.approx(20.0, rel=1e-3), f
    # 2*pi/(8*sin45) - 1
    assert f.volume_delta_pct == pytest.approx(11.0721, abs=0.05), f


def test_a_designed_prism_beside_a_real_cylinder_is_still_flagged(tmp_path):
    """With a second band present the model fingerprint is determined, and the
    prism violates it as well as the absolute bound -- both routes must agree."""
    from mesh2step.intent import audit_engine_cylinders

    # 200 facets would be theta=1.8deg, BELOW the 5deg seed band -- the engine would
    # never rebuild it and the audit would see one cylinder, not two. 40 facets is
    # theta=9deg: seeded, and inside the corpus's real tessellated range (max 13.85).
    prism = trimesh.creation.cylinder(radius=12.3, height=10.0, sections=8)
    prism.apply_translation([60, 0, 0])
    cyl = trimesh.creation.cylinder(radius=8.0, height=10.0, sections=40)
    both = trimesh.util.concatenate([prism, cyl])
    stl, step, _stats = _convert(both, tmp_path, "mixed")

    rows = audit_engine_cylinders(stl, step)
    assert len(rows) == 2, [r.message for r in rows]      # a row for BOTH bands
    flagged_radii = sorted(round(r.radius, 1) for r in rows if r.flagged)
    assert 12.3 in flagged_radii, [r.message for r in rows]
    assert 8.0 not in flagged_radii, [r.message for r in rows]


def test_a_24gon_is_reported_as_undecidable_not_silently_accepted(tmp_path):
    """The case no rule can settle, and therefore the case the user must see.

    A 24-gon turns 15 degrees per facet. The corpus's real tessellated bands run to
    13.85 degrees, so 15 is outside the observed range but not far outside it, and a
    lone band gives the fingerprint nothing to calibrate against. The engine rebuilds
    it as a cylinder (+1.15% volume, measured as P1). It must appear with its numbers
    and be named undecidable -- not flagged as a prism, and above all not omitted.
    """
    from mesh2step.intent import audit_engine_cylinders

    mesh = trimesh.creation.cylinder(radius=20.0, height=20.0, sections=24)
    stl, step, _stats = _convert(mesh, tmp_path, "gon24")

    rows = audit_engine_cylinders(stl, step)
    assert len(rows) == 1, [r.message for r in rows]
    row = rows[0]
    assert row.sides == 24, row
    assert row.turn_deg == pytest.approx(15.0, abs=0.5), row
    assert row.undecidable is True, row
    assert row.volume_delta_pct == pytest.approx(1.1517, abs=0.05), row
    assert "undecidable" in row.message.lower(), row.message
