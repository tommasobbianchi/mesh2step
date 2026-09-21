#!/bin/bash
# one part: facts (auto axis) -> reflective loop, 5 rounds max. $1 = part name
#   numbered parts come from ~/corpora/mechparts; anything else from $WD/uploads/<name>.stl
SD="$(cd "$(dirname "$0")" && pwd)"                       # the scripts
WD="${RECON_WORKDIR:-$SD/runs}"; mkdir -p "$WD"; cd "$WD"; p=$1
case $p in [0-9]*) f=/home/tommaso/corpora/mechparts/$p.stl;; *) f=$WD/uploads/$p.stl;; esac
python3 "$SD/facts.py" "$f" facts2_$p.json auto > facts2_$p.log 2>&1 || { echo "$p FACTS FAILED"; exit 0; }
timeout 7200 python3 "$SD/recon_loop.py" "$f" facts2_$p.json vis/$p recon2_$p "${RECON_MODEL:-opus}" 5 > recon2_$p.log 2>&1
echo "$p done rc=$?"
