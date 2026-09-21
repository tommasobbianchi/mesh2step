"""Acceptance tests for the resumable corpus driver. Run: python3 -m pytest -q tests/test_driver.py

Contract (see driver-resume.md), all in corpus_summary.py, importable without side effects:
  part_status(workdir, part) -> "done" | "failed" | "not_run"
      done    : workdir/recon2_<part>/best.json exists
      failed  : workdir/recon2_<part>/ exists without best.json
      not_run : no workdir/recon2_<part>/ at all
  parts_to_run(workdir, parts) -> the parts whose status is not "done", order preserved
  tally(rows) -> {"better", "worse", "same", "failed", "not_run"}
      rows: dicts {"part", "live", "loop", "status"}; better/worse/same compare the NUMBERS loop vs
      live for status "done"; a "failed" part counts in "failed" AND in "worse" when live > 0
      (a failure is a failure); "not_run" counts only in "not_run".
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import corpus_summary as cs  # noqa: E402  (must not run the summary on import)


def test_part_status_and_resume(tmp_path):
    (tmp_path / "recon2_1").mkdir(); (tmp_path / "recon2_1" / "best.json").write_text(json.dumps({}))
    (tmp_path / "recon2_2").mkdir()
    assert cs.part_status(tmp_path, "1") == "done"
    assert cs.part_status(tmp_path, "2") == "failed"
    assert cs.part_status(tmp_path, "3") == "not_run"
    assert cs.parts_to_run(tmp_path, ["1", "2", "3", "hotend"]) == ["2", "3", "hotend"]


def test_tally_counts_numbers_not_strings():
    rows = [{"part": "6", "live": 14, "loop": 49, "status": "done"},
            {"part": "17", "live": 50, "loop": 31, "status": "done"},
            {"part": "1", "live": 40, "loop": 40, "status": "done"},
            {"part": "21", "live": 7, "loop": 0, "status": "failed"},
            {"part": "22", "live": 6, "loop": 0, "status": "not_run"}]
    assert cs.tally(rows) == {"better": 1, "worse": 2, "same": 1, "failed": 1, "not_run": 1}
