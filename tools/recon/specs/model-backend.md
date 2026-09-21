# model-backend — let recon_loop.py drive opencode models as well as Claude

## Context
`tools/recon/recon_loop.py` asks a model to write a CadQuery program each round. Today it only
calls the claude CLI. We want to benchmark cheaper models (free opencode models such as
`opencode/muse-spark-1.3-contributor-free`, `opencode/nemotron-3-ultra-free`, and the cheap
vision model `deepseek/deepseek-v4-flash-vision-exp`) through the same loop and gate.

## Change ONLY `tools/recon/recon_loop.py`. Do not edit anything under `tests/`.

## Required behaviour (acceptance test: `tools/recon/tests/test_backend.py` — read it first)
1. The existing `<model>` argument selects the backend:
   - `opus`, `sonnet`, or `claude:<alias>` → the claude CLI exactly as today (`claude:<alias>` passes
     `<alias>` to `--model`).
   - `opencode:<provider/model>` → run
     `[OPENCODE_BIN, "run", "-m", "<provider/model>", *images, prompt]` with
     `cwd = workdir`, where `OPENCODE_BIN = os.environ.get("OPENCODE_BIN", "opencode")` and
     `images` is `["-f", path]` for every render PNG **only if the model name contains "vision"**.
     The prompt must be the LAST argument. Capture return code and stdout+stderr like the claude
     path, apply the same usage/rate-limit detection and retry, and use the same 1800 s timeout.
2. Prompt differences for opencode:
   - vision model: instead of "use the Read tool on each render", say the renders are attached;
   - text-only model: do not list render paths; say "The renders are unavailable to you; the
     measured facts are complete and are your only input." Keep everything else in the brief the
     same. In both cases the facts file is read from disk by the agent (keep its path in the
     prompt) and the program is written with the agent's file-writing tool to the path named in
     the prompt.
3. Nothing else changes: gate, selection, stop rule, quota handling, exit codes, outputs.

## Check
`cd /home/tommaso/projects/mesh2step && python3 -m pytest -q tools/recon/tests/` — all tests must pass.
