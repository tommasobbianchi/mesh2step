#!/bin/bash
# one part: facts (auto axis) -> reflective loop, $RECON_ROUNDS (5) rounds max. $1 = part name
#   an existing recon2_<p>/history.json is resumed: its rounds count toward the max
#   numbered parts come from ~/corpora/mechparts; anything else from $WD/uploads/<name>.stl
SD="$(cd "$(dirname "$0")" && pwd)"                       # the scripts
WD="${RECON_WORKDIR:-$SD/runs}"; mkdir -p "$WD"; cd "$WD"; p=$1
case $p in [0-9]*) f=/home/tommaso/corpora/mechparts/$p.stl;; *) f=$WD/uploads/$p.stl;; esac
python3 "$SD/facts.py" "$f" facts2_$p.json auto > facts2_$p.log 2>&1 || { echo "$p FACTS FAILED"; exit 0; }
R=${RECON_ROUNDS:-5}; H=recon2_$p/history.json
if [ -f "$H" ]; then export RESUME=$WD/$H; R=$((R - $(python3 -c "import json;print(len(json.load(open('$H'))))"))); fi
[ "$R" -gt 0 ] || { echo "$p done rc=0 (rounds exhausted)"; exit 0; }
timeout 7200 python3 "$SD/recon_loop.py" "$f" facts2_$p.json vis/$p recon2_$p "${RECON_MODEL:-opus}" $R >> recon2_$p.log 2>&1
echo "$p done rc=$?"
