"""Acceptance check for scanbuild.py on the owner's mechpart scan. Exit 0 = pass.

pass = one VALID closed solid, 0 free edges, volume within 2 % of the mesh, and at least 30 analytic faces
(plane faces made of a single triangle do not count: faceting every region would pass the other gates)."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE.parents[1] / "runs" / "scan"
out = subprocess.run([sys.executable, str(HERE / "scanbuild.py"), str(RUNS / "mechpart.clean.stl"),
                      str(RUNS / "mechpart.labels.npz"), str(RUNS / "mechpart.check.step")],
                     capture_output=True, text=True, timeout=1800)
line = next((ln for ln in out.stdout.splitlines() if ln.startswith("RESULT ")), None)
if line is None:
    print("FAIL: no RESULT line\n" + out.stderr[-3000:]); sys.exit(1)
r = json.loads(line[7:])
analytic = sum(v for k, v in r["kinds"].items() if k != "plane") + int(r.get("analytic_planes", 0))
dv = abs(abs(r["volume"]) - r["mesh_volume"]) / r["mesh_volume"]
gates = {"solid": r["solid"], "valid": r["valid"], "free_edges_0": r["free_edges"] == 0, "volume_within_2pct": dv < 0.02,
         "analytic_faces_ge_30": analytic >= 30}
print(json.dumps({"gates": gates, "dv": round(dv, 4), "analytic": analytic, "result": r})[:3000])
sys.exit(0 if all(gates.values()) else 1)
