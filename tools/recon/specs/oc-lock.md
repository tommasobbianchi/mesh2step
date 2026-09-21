# oc-lock — the opencode backend must take the machine-wide opencode lane lock

## Context
Concurrent opencode runs on one machine cross-attribute their output through the shared session
store. Every opencode caller on this box (`invoke-oc-acp/scripts/oc_acp.py`, `oc_run.sh`) takes an
exclusive `fcntl.flock` on `~/.local/state/oc-orchestrate/.run.lock`. `tools/recon/recon_loop.py`
calls `opencode run` directly without it, so an AI rebuild in the webapp could run beside a routing
job. It must wait for the lock instead.

## Change ONLY `tools/recon/recon_loop.py`. Do not edit tests.

## Required behaviour (acceptance test: `tools/recon/tests/test_oc_lock.py` — read it first)
1. Lock path: `os.environ.get("RECON_OC_LOCK", os.path.expanduser("~/.local/state/oc-orchestrate/.run.lock"))`;
   create the parent directory if missing.
2. Around every opencode subprocess call (and ONLY the opencode backend, not claude): open the lock
   file, acquire `fcntl.LOCK_EX`, waiting up to `float(os.environ.get("RECON_OC_LOCK_WAIT_S", "1800"))`
   seconds (poll with LOCK_NB every 2 s); run the command; release in a `finally`.
3. If the lock cannot be acquired within the wait, treat the attempt exactly like a usage/rate-limit
   failure (same retry/backoff/exit-75 path), with the text "opencode lane lock busy" as the CLI output.
4. Nothing else changes.

## Check
`cd /home/tommaso/projects/mesh2step && timeout 1200 python3 -m pytest -q tools/recon/tests/` — all pass.
