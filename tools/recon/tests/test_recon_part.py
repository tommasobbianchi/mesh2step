"""Acceptance tests for recon_part.py (one upload -> render -> facts -> loop over a model cascade).
Run: python3 -m pytest -q tools/recon/tests/test_recon_part.py

Contract (spec recon-part.md):
  recon_part.py <stl> <workdir> --models M1 [M2 ...] [--rounds N] [--timeout S]
    - renders the mesh into <workdir>/vis (deepseek-vision render.py), writes <workdir>/facts.json
      (facts.py, auto axis), then runs recon_loop.py for M1 in <workdir>/m1_<slug>/; if that model's
      best round is not ACCEPTED, M2 in its own subdirectory, and so on (cascade)
    - ACCEPTED = best.json exists, report valid, max p95 <= 0.005 * mesh diagonal, and every mesh
      cylinder patch represented (represent.curved == represent.patches)
    - a model whose loop exits 75 (quota) is skipped, the next one is tried
    - writes <workdir>/recon_result.json:
        {"status": "accepted" | "best_effort" | "failed" | "unavailable",
         "model": <model that produced best_step or null>, "best_step": <abs path or null>,
         "report": {...}, "represent": {...}, "models_tried": [{"model", "exit", "accepted"}],
         "seconds": <float>}
      accepted     -> exit 0 (first accepted model wins, later models are not run)
      best_effort  -> exit 3 (no model accepted; the best valid result across models is kept,
                      ranked by represent.curved then fidelity)
      unavailable  -> exit 75 (every model hit quota)
      failed       -> exit 2 (no valid result at all)
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import trimesh

HERE = Path(__file__).resolve().parents[1]
RP = HERE / "recon_part.py"

FAKE = r'''#!/usr/bin/env python3
import os, re, sys
mode = os.environ.get("FAKE_MODE_" + re.sub(r"[^A-Za-z0-9]", "_", sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else sys.argv[sys.argv.index("-m") + 1]), "ok")
open(os.environ["FAKE_LOG"], "a").write(mode + "\n")
prompt = sys.argv[-1]
if mode == "ok":
    m = re.findall(r"(\S+recon_\d+\.py)", prompt)
    open(m[-1], "w").write('result = cq.Workplane("XY").box(10, 10, 10)\n'); print("done")
elif mode == "quota":
    print("Claude AI usage limit reached"); sys.exit(1)
else:
    print("boom", file=sys.stderr); sys.exit(1)
'''


@pytest.fixture
def case(tmp_path):
    stl = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(stl)
    fake = tmp_path / "fake"; fake.write_text(FAKE); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "log"; log.write_text("")
    return tmp_path, stl, fake, log


def run(case, models, modes):
    tmp, stl, fake, log = case
    env = dict(os.environ, CLAUDE_BIN=str(fake), OPENCODE_BIN=str(fake), FAKE_LOG=str(log),
               RECON_BACKOFF_S="0", RECON_QUOTA_RETRIES="0", RECON_REVERSE="0")
    for m, mode in modes.items():
        env["FAKE_MODE_" + "".join(c if c.isalnum() else "_" for c in m)] = mode
    wd = tmp / "wd"
    p = subprocess.run([sys.executable, str(RP), str(stl), str(wd), "--models", *models, "--rounds", "1"],
                       env=env, capture_output=True, text=True, timeout=1200)
    res = json.loads((wd / "recon_result.json").read_text()) if (wd / "recon_result.json").exists() else None
    return p, res, log.read_text().split()


def test_first_model_accepted_stops_cascade(case):
    p, res, calls = run(case, ["sonnet", "opus"], {"sonnet": "ok", "opus": "ok"})
    assert p.returncode == 0, p.stderr[-2000:]
    assert res["status"] == "accepted" and res["model"] == "sonnet"
    assert calls == ["ok"]                               # opus never called
    assert Path(res["best_step"]).exists()
    assert (Path(res["best_step"]).parent.parent / "vis").is_dir()


def test_failed_model_escalates_to_next(case):
    p, res, calls = run(case, ["sonnet", "opus"], {"sonnet": "error", "opus": "ok"})
    assert p.returncode == 0, p.stderr[-2000:]
    assert res["status"] == "accepted" and res["model"] == "opus"
    assert [t["model"] for t in res["models_tried"]] == ["sonnet", "opus"]


def test_all_quota_is_unavailable(case):
    p, res, calls = run(case, ["sonnet", "opus"], {"sonnet": "quota", "opus": "quota"})
    assert p.returncode == 75, p.stderr[-2000:]
    assert res["status"] == "unavailable" and res["best_step"] is None


def test_the_loop_stops_at_the_acceptance_gate(case, tmp_path):
    """A round that already passes recon_part's gate must end the loop: extra rounds are paid for."""
    tmp, stl, fake, log = case
    # 10 x 10 x 9.9 box: p95 ~0.1 mm, above the loop's default 0.05 mm but within 0.5% of the diagonal
    fake.write_text(FAKE.replace("box(10, 10, 10)", "box(10, 10, 9.9)"))
    env = dict(os.environ, CLAUDE_BIN=str(fake), OPENCODE_BIN=str(fake), FAKE_LOG=str(log),
               RECON_BACKOFF_S="0", RECON_QUOTA_RETRIES="0", RECON_REVERSE="0")
    p = subprocess.run([sys.executable, str(RP), str(stl), str(tmp / "wd"), "--models", "opus", "--rounds", "3"],
                       env=env, capture_output=True, text=True, timeout=1200)
    assert p.returncode == 0, p.stderr[-2000:]
    assert log.read_text().split() == ["ok"]            # one model call, not three
