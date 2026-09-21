#!/bin/bash
# Same loop, same parts, cheaper author models -- serially (opencode agents share one lane).
SD="$(cd "$(dirname "$0")" && pwd)"
PARTS="${BENCH_PARTS:-16 19 6 33 polydryer}"
MODELS="${BENCH_MODELS:-opencode:opencode/muse-spark-1.3-contributor-free opencode:opencode/nemotron-3-ultra-free opencode:deepseek/deepseek-v4-flash-vision-exp}"
for m in $MODELS; do
  slug=$(echo "$m" | sed 's|.*/||; s|[^A-Za-z0-9.-]|_|g')
  W="$SD/runs/bench_$slug"; mkdir -p "$W"
  ln -sfn "$SD/runs/vis" "$W/vis"; ln -sfn "$SD/runs/uploads" "$W/uploads"
  for p in $PARTS; do
    H="$W/recon2_$p/history.json"                       # skip only parts that used all their rounds
    [ -f "$H" ] && [ "$(python3 -c "import json;print(len(json.load(open('$H'))))")" -ge "${RECON_ROUNDS:-3}" ] && continue
    RECON_ROUNDS="${RECON_ROUNDS:-3}" RECON_CALL_TIMEOUT_S="${RECON_CALL_TIMEOUT_S:-900}" RECON_WORKDIR="$W" RECON_MODEL="$m" RECON_BACKOFF_S=300 RECON_QUOTA_RETRIES=6 "$SD/one_part.sh" "$p"
  done
done
