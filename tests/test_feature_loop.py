"""IP4 attribution and the repair loop's decision functions.

The loop's value is entirely in WHICH clause it reacts to, so these test the decisions, not the
geometry: a rejection must name one clause, the code must be the Acilindria code a human would
write on the non-conformance record, and `_worth_refining` must refuse anything that is not a
near-miss -- a second attempt on a build that is 500% out on volume buys minutes and no cylinder.
"""
import pytest

from mesh2step.feature import (MAX_DIST_P95_REL, MAX_DV_PCT, _refine_argv, _repair_for,
                               _worth_refining, defect_code, failures)


def m(**kw):
    base = dict(solids=1, valid=True, free_edges=0, dv_pct=0.0, dist_p95=0.0, diag=100.0,
                cylinders=4)
    base.update(kw)
    return base


def test_a_clean_build_fails_nothing():
    assert failures(m(), 0, 1.0) == []


def test_every_clause_is_named_in_severity_order():
    bad = m(solids=3, valid=False, free_edges=2, dv_pct=99.0, dist_p95=9.0, cylinders=0)
    assert failures(bad, 0, 0.0) == ["solids", "valid", "free_edges", "dv_pct", "dist_p95",
                                     "no_gain", "support"]


def test_no_output_is_a_builder_gap_not_a_crash():
    assert defect_code(None, ["no_output"], None, None) == "AC-NOBUILD"


def test_support_failure_with_a_broken_solid_is_coded_by_the_solid():
    """AC-B4 means 'passed every shape gate and invented'. A four-solid build has not."""
    bad = m(solids=4, dv_pct=500.0)
    assert defect_code(bad, failures(bad, 0, 0.1), 0.1, [1.0]) == "AC-B2"


def test_support_alone_is_the_immune_system():
    assert defect_code(m(), ["support"], 0.1, [1.0, 2.0]) == "AC-B4"


def test_support_with_nothing_detected_is_the_blind_spot():
    assert defect_code(m(), ["support"], 0.0, []) == "AC-B5"


def test_a_shape_near_miss_is_b3():
    near = m(dist_p95=0.7 * MAX_DIST_P95_REL * 100.0 * 2)
    assert defect_code(near, ["dist_p95"], 1.0, [1.0]) == "AC-B3"


@pytest.mark.parametrize("fails,name", [(["solids"], "largest"), (["valid"], "sew"),
                                        (["free_edges"], "sew")])
def test_solid_clauses_name_a_repair(fails, name):
    assert _repair_for(fails)[0] == name


@pytest.mark.parametrize("fails", [["dv_pct"], ["dist_p95"], ["support"], ["no_gain"]])
def test_shape_and_immune_clauses_name_no_repair_of_the_solid(fails):
    assert _repair_for(fails) is None


def test_refine_fires_on_a_near_miss_that_recovered_something():
    near = m(dist_p95=1.5 * MAX_DIST_P95_REL * 100.0, dv_pct=0.5 * MAX_DV_PCT)
    assert _worth_refining(near, ["dist_p95"], 0)


def test_refine_refuses_a_build_that_is_simply_wrong():
    wrong = m(dv_pct=503.0, dist_p95=9.0)
    assert not _worth_refining(wrong, ["dv_pct", "dist_p95"], 0)


def test_refine_refuses_a_build_that_recovered_nothing_new():
    near = m(dist_p95=1.5 * MAX_DIST_P95_REL * 100.0, cylinders=4)
    assert not _worth_refining(near, ["dist_p95"], 4)


def test_refine_refuses_an_immune_rejection():
    """Spending minutes on a denser re-run of a build that invents is buying confabulation."""
    near = m(dist_p95=1.5 * MAX_DIST_P95_REL * 100.0)
    assert not _worth_refining(near, ["dist_p95", "support"], 0)


def test_only_builders_with_a_density_knob_are_retried():
    argv = ["py", "auto25g.py", "a.stl", "b.step", "60"]
    assert _refine_argv("stepped", argv, "r.step") == ["py", "auto25g.py", "a.stl", "r.step",
                                                       "180"]
    assert _refine_argv("block", ["py", "autoblock2.py", "a.stl", "b.step"], "r.step") is None


def test_a_refined_build_is_not_refined_again():
    assert _refine_argv("stepped", ["py", "auto25g.py", "a.stl", "b.step", "180"], "r") is None
