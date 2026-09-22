#!/usr/bin/env bash
# Provision behemoth (100.103.234.2) as a SECOND mesh2step worker.
#
# Why a second worker at all: the feature pass is what people come for, and it
# costs a ~408 s mean per conversion against 6 slots -- about 50 conversions an
# hour. A creator-driven surge passes that in one evening.
#
# The routing constraint that shapes everything here: server.py keeps _JOBS and
# _PENDING in PROCESS MEMORY, and _JOBS[token]["path"] is a filesystem path on
# the machine that built the STEP. A client that converts on one node and polls
# or downloads from the other gets a 404 -- the file is not there. So the front
# door must pin a client to one node for the life of its job (Caddy
# lb_policy cookie). This script provisions the node; it does NOT touch routing.
#
# Idempotent: re-running it re-syncs the repo and engine and restarts the unit.
set -euo pipefail

HOST="${HOST:-tommaso@100.103.234.2}"
ENGINE="mesh2step-native-v1.8.2-fcaee701f2db"   # pinned: must match nativedev's native.conf exactly
PORT="${PORT:-8000}"
SRC="/home/tommaso/projects/mesh2step"

say() { printf '\n=== %s ===\n' "$*"; }

# The OCCT the service actually runs is 7.9.3, NOT the 7.8.1 that `pip list`
# suggests. Three distributions overlap in one site-packages tree on nativedev
# (cadquery-ocp 7.8.1.1.post1, -novtk 7.9.3.1.1, -proxy 7.9.3.1.1); novtk
# installed over the older wheel -- it owns 643 files under OCP/ against 639 --
# and the loaded OCP.cpython-312...so carries the string 7.9.3. The leftover
# libTK*.so.7.8.1 files belong to the superseded wheel and are not what binds.
# This matters here because -novtk ships a cp314 wheel and cadquery-ocp 7.8.1
# does not: behemoth's stock Python 3.14 can therefore run the SAME OCCT.
say "0. preflight: python 3.12 or 3.14, both of which have 7.9.3 wheels"
ssh -o BatchMode=yes "$HOST" 'python3 -V; nproc; free -g | awk "NR==2{print \"RAM \"\$2\"G\"}"'
PYV=$(ssh -o BatchMode=yes "$HOST" 'python3 -c "import sys;print(\"%d.%d\"%sys.version_info[:2])"')
case "$PYV" in
  3.12|3.13|3.14) echo "python $PYV -- cadquery-ocp-novtk 7.9.3.1.1 has a wheel for it" ;;
  *) echo "FATAL: behemoth runs python $PYV; cadquery-ocp-novtk 7.9.3.1.1 ships cp311-cp314 only."; exit 2 ;;
esac

say "1. repo"
ssh -o BatchMode=yes "$HOST" 'mkdir -p ~/projects'
# tools/recon/runs holds user uploads and model transcripts: never ship them.
rsync -a --delete --exclude .git --exclude '.worktrees' --exclude '__pycache__' \
      --exclude 'tools/recon/runs' \
      "$SRC/" "$HOST:~/projects/mesh2step/"
# No .git on the worker, so _app_version() reads .version -- the only node label a client sees.
# --delete above removes it (nativedev has none), so write it after every sync.
echo "$(git -C "$SRC" describe --tags)-behemoth" | ssh -o BatchMode=yes "$HOST" 'cat > ~/projects/mesh2step/.version'

say "2. native engine ($ENGINE, 59 MB, pinned build)"
ssh -o BatchMode=yes "$HOST" 'mkdir -p ~/.local/share'
rsync -a --delete "$HOME/.local/share/$ENGINE/" "$HOST:~/.local/share/$ENGINE/"
ssh -o BatchMode=yes "$HOST" "chmod +x ~/.local/share/$ENGINE/run.sh ~/.local/share/$ENGINE/stl2step"

say "3. python deps, versions pinned to what nativedev actually runs"
ssh -o BatchMode=yes "$HOST" 'python3 -m pip install --user -q --upgrade pip 2>&1 | tail -2'
# cadquery-ocp-novtk 7.9.3.1.1, NOT cadquery-ocp 7.8.1.1.post1: the former is
# what actually binds on nativedev (see the note in step 0) and it is the only
# one of the two with a cp314 wheel. Pinning the 7.8.1 name here would either
# fail to resolve on 3.14 or install a SECOND, older OCCT over the right one --
# the exact overlap that made nativedev's own version ambiguous.
ssh -o BatchMode=yes "$HOST" 'python3 -m pip install --user -q --break-system-packages \
    cadquery-ocp-novtk==7.9.3.1.1 \
    fastapi==0.129.0 uvicorn==0.40.0 \
    numpy-stl==3.2.0 trimesh==4.11.2 \
    networkx==3.6.1 lxml==6.0.2 shapely==2.1.2 rtree==1.4.1 \
    python-multipart requests 2>&1 | tail -8'
# networkx/lxml/shapely/rtree: trimesh's optional loaders (3MF needs networkx). Missing on behemoth until
# 2026-09-22, when a 3MF upload there died as a bare 500 -- nativedev had them, so the gate never saw it.
# numpy/scipy/cadquery are deliberately unpinned: 3.14 wheels differ and the
# service imports none of cadquery's own API, only OCP.
# The app does `from mesh2step.cut import ...`, and the package lives under
# src/ -- a src-layout is NOT importable from the repo root. nativedev resolves
# it through an EDITABLE install (__editable__.mesh2step-0.1.0.pth pointing at
# src/mesh2step); without the same install here, uvicorn dies at import with
# ModuleNotFoundError after every other step has already succeeded.
# --no-deps: the dependency set is pinned explicitly above, and letting pip
# resolve pyproject's own pins would drag in the cp312-only cadquery-ocp.
say "3b. editable install of the mesh2step package itself (src-layout)"
ssh -o BatchMode=yes "$HOST" 'cd ~/projects/mesh2step && python3 -m pip install --user -q \
    --break-system-packages --no-deps -e . 2>&1 | tail -3
python3 -c "import mesh2step, os; print(\"mesh2step ->\", os.path.dirname(mesh2step.__file__))"'

ssh -o BatchMode=yes "$HOST" 'python3 -c "
import OCP, fastapi, trimesh, numpy, glob, os
d=os.path.dirname(OCP.__file__)
so=sorted(glob.glob(d+\"/*.so\"), key=os.path.getsize, reverse=True)[0]
print(\"OCP binding:\", os.path.basename(so))
import subprocess
v=subprocess.run([\"strings\",\"-a\",so],capture_output=True,text=True).stdout
import re
print(\"OCCT:\", sorted(set(re.findall(r\"^7\\.[0-9]+\\.[0-9]+$\", v, re.M)))[:3])
print(\"numpy\", numpy.__version__, \"trimesh\", trimesh.__version__)
"'

say "4. engine smoke test on a real part (proves the binary runs HERE, not just exists)"
rsync -a /home/tommaso/corpora/mechparts/15.stl "$HOST:/tmp/m2s-smoke.stl"
ssh -o BatchMode=yes "$HOST" "~/.local/share/$ENGINE/run.sh /tmp/m2s-smoke.stl /tmp/m2s-smoke.step 2>&1 | tail -3; ls -la /tmp/m2s-smoke.step"

say "5. systemd user unit + the SAME drop-ins production runs"
ssh -o BatchMode=yes "$HOST" "mkdir -p ~/.config/systemd/user/mesh2step.service.d"
cat <<UNIT | ssh -o BatchMode=yes "$HOST" "cat > ~/.config/systemd/user/mesh2step.service"
[Unit]
Description=mesh2step web app (uvicorn on :$PORT) -- behemoth worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/projects/mesh2step
ExecStart=/usr/bin/python3 -m uvicorn webapp.server:app --host 0.0.0.0 --port $PORT --log-level warning
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT

# Slots: behemoth has 16 cores / 60 GB against nativedev's measured operating
# point of 6 slots / 24 GB. Same 6 to start -- the 6-slot figure was chosen on
# throughput evidence, not on spare RAM, and a second node should be boring
# before it is clever.
cat <<'DROPIN' | ssh -o BatchMode=yes "$HOST" "cat > ~/.config/systemd/user/mesh2step.service.d/60-capacity.conf"
[Service]
MemoryHigh=infinity
MemoryMax=24G
Environment=MESH2STEP_SLOTS=6
DROPIN

cat <<DROPIN | ssh -o BatchMode=yes "$HOST" "cat > ~/.config/systemd/user/mesh2step.service.d/70-engine.conf"
[Service]
Environment=MESH2STEP_NATIVE=%h/.local/share/$ENGINE/run.sh
Environment=MESH2STEP_FEATURE=1
Environment=MESH2STEP_ENGINE_FALLBACK=1
Environment=MESH2STEP_EDGEBUILD_TIMEOUT_S=900
DROPIN

# The monitoring token is a SECRET: it lives in ~/.secrets/credentials.yaml on the control host, never in the
# repo. Without it a node answers /api/admin/stats with 503, so the page would show that node as unreachable.
say "5b. monitoring token (from ~/.secrets/credentials.yaml)"
TOKEN=$(python3 -c "import yaml,pathlib;print((yaml.safe_load((pathlib.Path.home()/'.secrets/credentials.yaml').read_text()) or {}).get('mesh2step',{}).get('admin_token',''))")
if [ -n "$TOKEN" ]; then
  printf '[Service]\nEnvironment=MESH2STEP_ADMIN_TOKEN=%s\nEnvironment=MESH2STEP_PEERS=http://100.112.35.102:8000\n' "$TOKEN" |
    ssh -o BatchMode=yes "$HOST" "cat > ~/.config/systemd/user/mesh2step.service.d/80-monitor.conf"
  echo "monitoring token installed"
else
  echo "no mesh2step.admin_token in ~/.secrets/credentials.yaml -- monitoring will be off on this node"
fi

# The AI rebuild runs here too (the Claude CLI is installed and logged in on this node). The daily budget is
# SPLIT with nativedev -- both nodes bill the same account -- so each carries half of the ceiling.
say "5c. AI rebuild (Opus), daily budget split with nativedev"
cat <<'RECON' | ssh -o BatchMode=yes "$HOST" "cat > ~/.config/systemd/user/mesh2step.service.d/90-recon.conf"
[Service]
Environment=MESH2STEP_RECON=1
Environment=MESH2STEP_RECON_MODELS=opus
Environment=MESH2STEP_RECON_ROUNDS=5
Environment=MESH2STEP_RECON_TIMEOUT_S=5400
Environment=MESH2STEP_RECON_DAILY_MAX=50
RECON

say "6. enable linger and start"
# Poll for readiness instead of sleeping a fixed interval. uvicorn has to import
# a ~160 MB OCP binding before it binds the port, so a cold start is slow and
# variable; an 8 s sleep returned "activating", which under set -e killed the
# provision after every expensive step had already succeeded.
ssh -o BatchMode=yes "$HOST" 'loginctl enable-linger tommaso 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user restart mesh2step.service
for i in $(seq 1 60); do
    if curl -sf -m 3 http://127.0.0.1:8000/api/limits >/dev/null 2>&1; then
        echo "ready after ${i}s"; break
    fi
    state=$(systemctl --user is-active mesh2step.service)
    if [ "$state" = "failed" ]; then
        echo "FATAL: unit failed while starting"; systemctl --user status mesh2step.service --no-pager | tail -20; exit 3
    fi
    sleep 1
done
curl -sf -m 5 http://127.0.0.1:8000/api/limits >/dev/null || { echo "FATAL: not serving after 60s"; exit 3; }
systemctl --user is-active mesh2step.service'

say "7. prove it SERVES, over the tailnet, not just that the unit is active"
sleep 2
python3 - <<'PY'
import urllib.request, json
u="http://100.103.234.2:8000/api/limits"
try:
    d=json.load(urllib.request.urlopen(u,timeout=20))
    print("behemoth /api/limits ->", d)
except Exception as e:
    print("FATAL: behemoth does not serve:",type(e).__name__,e); raise SystemExit(1)
PY

say "8. EQUIVALENCE GATE -- the same STL must produce the same geometry on both nodes"
# A matching version string is not proof. mesh2step's whole value is geometric
# fidelity, so a second node that silently returns a different STEP for the same
# upload is worse than having no second node: the defect is invisible and
# depends on which machine happened to answer. This gate fails the provision.
python3 - <<'PY'
import json, sys, time, urllib.request, uuid
PART="/home/tommaso/corpora/mechparts/15.stl"      # small, fast, real
data=open(PART,"rb").read()

def convert(base):
    b=uuid.uuid4().hex; body=b""
    for k,v in {"engine":"trueform","feature":"true"}.items():
        body+=(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    body+=(f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"15.stl\"\r\n"
           f"Content-Type: application/octet-stream\r\n\r\n").encode()+data+b"\r\n"
    body+=f"--{b}--\r\n".encode()
    req=urllib.request.Request(base+"/api/convert",data=body,
        headers={"Content-Type":f"multipart/form-data; boundary={b}"})
    d=json.loads(urllib.request.urlopen(req,timeout=1800).read())
    while d.get("pending"):
        time.sleep(5)
        d=json.loads(urllib.request.urlopen(f"{base}/api/job/{d['job']}",timeout=60).read())
    return d.get("stats") or {}

a=convert("http://127.0.0.1:8000")
b=convert("http://100.103.234.2:8000")
keys=("is_solid","free_edges","n_faces_built","volume","feature_method","backend")
print(f"{'key':>16} {'nativedev':>22} {'behemoth':>22}")
bad=[]
for k in keys:
    va,vb=a.get(k),b.get(k)
    same = (abs(va-vb)<=1e-6*max(1,abs(va)) if isinstance(va,float) and isinstance(vb,float) else va==vb)
    if not same: bad.append(k)
    print(f"{k:>16} {str(va):>22} {str(vb):>22} {'' if same else '  <-- DIFFERS'}")
if bad:
    print("\nFATAL: nodes are not geometrically equivalent on", bad)
    print("Do NOT put behemoth behind the load balancer: the same upload would")
    print("return different CAD depending on which node answered.")
    sys.exit(1)
print("\nequivalent on all compared keys")
PY

say "DONE -- worker provisioned and equivalence-gated. Routing is a SEPARATE, deliberate step:"
cat <<'NOTE'
  Do NOT round-robin. server.py holds _JOBS/_PENDING in process memory and
  _JOBS[token]["path"] is a local filesystem path, so a client must stay on the
  node that accepted its upload. In ~/.config/caddy/Caddyfile:

      handle_path /mesh2step/* {
          reverse_proxy 127.0.0.1:8000 100.103.234.2:8000 {
              lb_policy cookie m2s_node
              health_uri /api/limits
              health_interval 10s
              transport http { read_timeout 30m  write_timeout 30m }
          }
      }

  then: caddy reload --config ~/.config/caddy/Caddyfile
NOTE
