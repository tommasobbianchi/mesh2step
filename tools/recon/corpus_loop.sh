#!/bin/bash
WORKDIR="${RECON_WORKDIR:-$(cd "$(dirname "$0")" && pwd)/runs}"
PARALLEL="${RECON_PARALLEL:-2}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$WORKDIR"
parts="$(ls /home/tommaso/corpora/mechparts/*.stl | xargs -n1 basename | sed 's/.stl//' | sort -n) hotend polydryer"
todo=$(python3 -c "import sys; sys.path.insert(0, '$SCRIPT_DIR'); from corpus_summary import parts_to_run; print(' '.join(parts_to_run('$WORKDIR', '''$parts'''.split())))")
echo "$todo" | tr ' ' '\n' | xargs -P "$PARALLEL" -I{} "$SCRIPT_DIR"/one_part.sh {}
python3 "$SCRIPT_DIR"/corpus_summary.py > corpus_loop_summary.txt 2>&1
