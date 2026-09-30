# Docker

Builds the webapp with its native `stl2step` engine compiled from source
(github.com/BlinkingSun/stl2step @ 7cf77a2), so the image is self-contained —
no `MESH2STEP_NATIVE` mount needed at runtime.

```sh
docker build -f docker/Dockerfile -t mesh2step .
docker run --rm -p 8000:8000 mesh2step
```

Open http://localhost:8000.

## Untested build — what to check if it fails

This was written against the exact recipe in `docs/reference-engine.md` and
Debian bookworm's `libocct-*-dev` packages, but it has not been run through an
actual `docker build` (no Docker daemon in the environment this was authored
in). Likely failure points, in order:

- **CMake can't find OpenCASCADE** — Debian's package may not ship a
  `find_package(OpenCASCADE)` config at the path CMake expects. Check the
  `cmake -S . -B build` step's output.
- **`libTK*.so` glob picks up the wrong/missing libs** — if linking fails with
  undefined references, list `/usr/lib/x86_64-linux-gnu/libTK*.so` in the
  build log and compare against what `src/main.cpp` actually needs.
- **`stl2step_core` isn't the real target name** at commit `7cf77a2` — if
  `cmake --build` errors on the target, run `cmake --build build --target
  help` to list what the pinned commit actually exposes.

## Useful env vars (see webapp/server.py)

- `MESH2STEP_SLOTS` — concurrent conversions (default 2; sized for the
  reference host's CPU/RAM, tune per container).
- `MESH2STEP_ADMIN_TOKEN` — enables `/api/admin/stats` and `/monitor`.
- `MESH2STEP_FEATURE`, `MESH2STEP_EDGEBUILD`, `MESH2STEP_RECON` — optional
  reconstruction passes; `MESH2STEP_RECON=1` calls a paid model and needs its
  API key in the environment too.
