"""A waiting user is told which step the conversion is on, and when it will stop by itself.

No duration is predicted anywhere: over 351 logged conversions the same mesh at the same
triangle count ran anywhere from 3 s to 900 s. What IS knowable is the step (the candidate
list is fixed) and the ceiling (the two timeouts), so those are what the pipeline must carry
from the builder loop all the way to /api/job.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mesh2step import feature  # noqa: E402
from webapp import server  # noqa: E402


def test_phase_lines_are_written_and_are_parsable(tmp_path, monkeypatch):
    log = tmp_path / "phases.jsonl"
    monkeypatch.setenv("MESH2STEP_PHASE_LOG", str(log))
    feature._phase(3, 7, "stepped", "start")
    feature._phase(3, 7, "stepped", "done", 12.5)
    recs = [json.loads(l) for l in log.read_text().splitlines()]
    assert [r["state"] for r in recs] == ["start", "done"]
    assert recs[1]["seconds"] == 12.5 and recs[1]["i"] == 3 and recs[1]["n"] == 7


def test_phase_logging_never_costs_the_conversion(tmp_path, monkeypatch):
    # an unwritable path must not raise into the builder loop
    monkeypatch.setenv("MESH2STEP_PHASE_LOG", str(tmp_path / "no" / "such" / "dir" / "p.jsonl"))
    feature._phase(1, 7, "extrude-x", "start")  # must not raise
    monkeypatch.delenv("MESH2STEP_PHASE_LOG")
    feature._phase(1, 7, "extrude-x", "start")  # unset: also a no-op


def test_a_finished_phase_points_at_the_one_now_running(tmp_path):
    log = tmp_path / "phases.jsonl"
    log.write_text(json.dumps({"i": 2, "n": 7, "label": "extrude-y", "state": "done",
                               "t": 0, "seconds": 3.0}) + "\n")
    p = server._read_progress({"phase_file": str(log)})
    assert p["phase_i"] == 4, "step 1 is the engine, so candidate 3 is step 4"
    assert p["phase_n"] == 8
    assert p["ceiling_s"] == server.NATIVE_TIMEOUT_S + server.FEATURE_TIMEOUT_S

    log.write_text(json.dumps({"i": 7, "n": 7, "label": "block", "state": "done", "t": 0}) + "\n")
    assert server._read_progress({"phase_file": str(log)})["phase_i"] == 8, "never past the last"


def test_progress_is_absent_rather_than_wrong(tmp_path):
    assert server._read_progress(None) == {}
    assert server._read_progress({}) == {}
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n")
    assert server._read_progress({"phase_file": str(bad)}) == {}


def test_every_pre_feature_stage_says_what_it_is(tmp_path):
    """Measured on bucket.stl: the engine finished in seconds and the edge rebuild then ran
    13+ minutes. Reporting that as "engine" is the longest stage lying about itself."""
    for stage in ("prepare", "engine", "retry", "edgebuild"):
        p = server._read_progress({"stage": stage})
        assert p["phase"] == stage and p["phase_i"] == 1, stage
    # the child's file exists but is still empty: the pre-feature label must win, not "engine"
    empty = tmp_path / "phases.jsonl"
    empty.write_text("")
    assert server._read_progress({"stage": "edgebuild",
                                  "phase_file": str(empty)})["phase"] == "edgebuild"


def test_the_engine_stage_is_step_one(tmp_path):
    """The longest waits are spent in the engine, before any candidate exists. A run that
    reported nothing until the feature pass would stay silent through exactly those."""
    p = server._read_progress({"stage": "engine"})
    assert p["phase"] == "engine" and p["phase_i"] == 1
    assert p["phase_n"] == server._n_phases() == 8
    # the phase file is created by the child; until it has a line, we are still on the engine
    empty = tmp_path / "phases.jsonl"
    empty.write_text("")
    assert server._read_progress({"stage": "engine", "phase_file": str(empty)})["phase_i"] == 1
    assert server._read_progress({"phase_file": str(tmp_path / "gone.jsonl")}) == {}


def test_job_endpoint_carries_the_phase(tmp_path):
    from fastapi.testclient import TestClient

    class Unfinished:
        def done(self):
            return False

    log = tmp_path / "phases.jsonl"
    log.write_text(json.dumps({"i": 4, "n": 7, "label": "stepped", "state": "start", "t": 0}) + "\n")
    server._PENDING["tok"] = {"future": Unfinished(), "ts": 0.0, "name": "x.step",
                              "progress": {"phase_file": str(log)}}
    try:
        body = TestClient(server.app).get("/api/job/tok").json()
    finally:
        server._PENDING.pop("tok", None)
    assert body["pending"] and body["phase"] == "stepped"
    assert body["phase_i"] == 5 and body["phase_n"] == 8 and body["ceiling_s"] > 0


def test_every_candidate_has_words_for_the_user():
    # the labels the builder loop emits must all be nameable in the UI, or a waiting user
    # sees a raw internal identifier at exactly the moment they are least patient
    app_js = (Path(__file__).resolve().parents[1] / "webapp" / "static" / "app.js").read_text()
    labels = ["prepare", "engine", "retry", "edgebuild"] + [c[0] for c in feature._candidates(Path("x.stl"), Path(os.sep + "tmp"))]
    missing = [l for l in labels if f"'{l}'" not in app_js and f"\n  {l}:" not in app_js]
    assert not missing, f"no user-facing wording for {missing}"


def test_a_qualifying_build_carries_its_phase_profile(tmp_path, monkeypatch):
    """The whole point of the timings is to survive into the result, where a fitted ETA
    can read them back. Drive the real loop with one trivial builder: a box STEP that
    matches a box mesh."""
    import trimesh

    # a cylinder, not a box: the gate only keeps a build that recognises MORE cylindrical faces
    # than the engine did, so a prismatic shape can never qualify and would test nothing
    mesh = trimesh.creation.cylinder(radius=10.0, height=20.0, sections=256)
    stl = tmp_path / "cyl.stl"
    mesh.export(str(stl))

    step_src = (
        "from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder\n"
        "from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt\n"
        "from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer\n"
        "import sys\n"
        "ax = gp_Ax2(gp_Pnt(0, 0, -10), gp_Dir(0, 0, 1))\n"
        "w = STEPControl_Writer()\n"
        "w.Transfer(BRepPrimAPI_MakeCylinder(ax, 10.0, 20.0).Shape(), STEPControl_AsIs)\n"
        "w.Write(sys.argv[1])\n"
    )
    monkeypatch.setattr(feature, "_candidates", lambda stl_, wd: [
        ("block", [sys.executable, "-c", step_src, str(wd / "E.step")], {}, wd / "E.step")])
    log = tmp_path / "phases.jsonl"
    monkeypatch.setenv("MESH2STEP_PHASE_LOG", str(log))

    best = feature.reconstruct(stl, tmp_path / "out.step")
    assert best, "the cylinder build should qualify"
    assert [p[0] for p in best["phases"]] == ["block"]
    assert best["phases"][0][1] > 0 and best["phases"][0][2] == "done"
    assert feature.native_payload(best, stl, tmp_path / "out.step", 1.0)["featurePhases"] \
        == best["phases"], "the profile must reach the payload every caller renders"
    assert log.read_text().count("\n") == 2, "one start line and one done line"


def test_a_timed_out_candidate_is_recorded_as_such(tmp_path, monkeypatch):
    """A phase that ran out of time is still a measured phase -- it held the user's clock."""
    monkeypatch.setattr(feature, "_candidates", lambda stl_, wd: [
        ("block", [sys.executable, "-c", "import time; time.sleep(30)"], {}, wd / "E.step")])
    log = tmp_path / "phases.jsonl"
    monkeypatch.setenv("MESH2STEP_PHASE_LOG", str(log))
    import trimesh

    stl = tmp_path / "box.stl"
    trimesh.creation.box(extents=(10, 10, 10)).export(str(stl))

    assert feature.reconstruct(stl, tmp_path / "out.step", timeout=1.0) is None
    recs = [json.loads(l) for l in log.read_text().splitlines()]
    assert recs[-1]["state"] == "timeout" and recs[-1]["seconds"] >= 1.0
