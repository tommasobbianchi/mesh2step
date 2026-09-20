"""The engine must say what it detected and did not build (guideline 2.1), and not lie about it.

The numbers are the real ones from the hotend assembly a user uploaded on 2026-09-21, including
the trap: `smooth_reverted_components` reads 1 while `smooth_reverted_true` reads 0, because the
counter increments on a path that is not the true revert. The component was ADOPTED and built
nothing. An attribution that keys on the revert counter sends the next session after a revert
that never happened.
"""
from mesh2step.attribution import engine_analytic_loss_note

HOTEND = {
    "smooth_cylinders": 36, "smooth_fillets": 126, "smooth_planes": 1424,
    "smooth_built_cylinders": 0, "smooth_built_fillets": 0, "smooth_built_planes": 0,
    "smooth_reverted_components": 1, "smooth_reverted_true": 0,
    "warnings": ["smooth: IntAna cyl|cyl empty/same - keeping mesh polyline"] * 43 + [
        "J6: shell not closed freeEdges=41 faces=12782 recover=0",
        "B-Rep invalid after build -- no ShapeFix rewrite on smooth runs",
        "no analytic band survived to measure it"],
}


def test_a_conversion_that_built_what_it_found_says_nothing():
    assert engine_analytic_loss_note({"smooth_cylinders": 7, "smooth_built_cylinders": 7}) is None
    assert engine_analytic_loss_note({}) is None


def test_the_loss_is_named_with_its_inventory():
    note = engine_analytic_loss_note(HOTEND)
    assert "AC-B2/engine" in note
    assert "detected cylinders=36 fillets=126" in note
    assert "built cylinders=0" in note and "lost 162" in note


def test_the_first_cause_in_causal_order_wins_not_its_symptom():
    """Failed analytic intersections are why the shell will not close, not the other way round."""
    assert "cause=analytic-intersection-empty" in engine_analytic_loss_note(HOTEND)


def test_a_revert_counter_contradicted_by_reverted_true_is_flagged():
    assert "is NOT a revert" in engine_analytic_loss_note(HOTEND)


def test_a_real_revert_is_reported_as_one():
    note = engine_analytic_loss_note({"smoothCylinders": 9, "smoothBuiltCylinders": 0,
                                      "smoothRevertedComponents": 2, "smoothRevertedTrue": 2,
                                      "warnings": ["B-Rep invalid after build"]})
    assert "revertedComponents=2" in note and "is NOT a revert" not in note
    assert "cause=brep-invalid" in note


def test_a_partial_loss_counts_only_what_was_lost():
    note = engine_analytic_loss_note({"smoothCylinders": 10, "smoothBuiltCylinders": 4,
                                      "smoothFillets": 3, "smoothBuiltFillets": 3})
    assert "lost 6" in note and "cause=unnamed" in note
