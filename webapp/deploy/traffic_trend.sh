#!/usr/bin/env bash
# Request trend for mesh2step, straight from the journal. No service change: the
# service already prints SRVREQ (every upload request) and SRVCONV (every
# conversion, with its triangle count), so the rate is derivable and nothing new
# has to be instrumented or kept in memory.
#
# Use during a traffic surge to decide whether to offload: the numbers that
# matter are conversions STARTED per hour against the 6 slots, and the share of
# requests refused with 429 -- a rising 429 share is the queue saying it is full
# before any human notices.
#
#   traffic_trend.sh            last 6 hours, hourly buckets
#   traffic_trend.sh 24         last 24 hours
#
# ponytail: journal grep, not a metrics endpoint. Add /metrics if this is ever
# scraped by something rather than read by a person.
set -uo pipefail
HOURS="${1:-6}"

journalctl --user -u mesh2step.service --since "-${HOURS}h" --no-pager -o short-iso 2>/dev/null \
| awk '
  /SRVREQ/  { split($1,t,"T"); split(t[2],hm,":"); b=t[1]" "hm[1]"h"
              req[b]++; if ($0 ~ / 429 /) r429[b]++; if ($0 ~ / 5[0-9][0-9] /) r5xx[b]++ }
  /SRVCONV/ { split($1,t,"T"); split(t[2],hm,":"); b=t[1]" "hm[1]"h"
              conv[b]++; for (i=1;i<=NF;i++) if ($i ~ /^SRVCONV$/) s=$(i+1)
              tot[b]+=s; if (s>mx[b]) mx[b]=s }
  END {
    printf "%-14s %7s %7s %7s %7s %9s %9s\n","hour","reqs","convs","429","5xx","mean_s","max_s"
    printf "%s\n","--------------------------------------------------------------------------"
    n=asorti(req,idx); split("",seen)
    for (b in conv) req[b]=req[b]  # ensure conv-only buckets appear
    n=asorti(req,idx)
    for (i=1;i<=n;i++) { b=idx[i]
      m=(conv[b]?tot[b]/conv[b]:0)
      printf "%-14s %7d %7d %7d %7d %9.1f %9.1f\n", b, req[b], conv[b]+0, r429[b]+0, r5xx[b]+0, m, mx[b]+0 }
  }' 2>/dev/null || echo "awk lacks asorti (use gawk); falling back:"

echo
echo "slots=$(systemctl --user show mesh2step.service -p Environment --value | tr ' ' '\n' | grep MESH2STEP_SLOTS || echo 'MESH2STEP_SLOTS=2 (default)')"
echo "cgroup mem now: $(systemctl --user show mesh2step.service -p MemoryCurrent --value | awk '{printf "%.2f GB",$1/1073741824}')"
echo
echo "OFFLOAD SIGNAL: sustained convs/hour near 6*3600/mean_s, or a 429 column that stops being 0."
