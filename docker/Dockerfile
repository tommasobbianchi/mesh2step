# Build from the repo root: docker build -f docker/Dockerfile -t mesh2step .

# ---- Stage 1: compile the stl2step native engine (required by webapp/server.py) ----
FROM debian:bookworm-slim AS native-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git ca-certificates \
        libocct-foundation-dev libocct-modeling-data-dev libocct-modeling-algorithms-dev \
        libocct-ocaf-dev libocct-data-exchange-dev libocct-visualization-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
# Pinned commit per docs/reference-engine.md (upstream v1.1.0, MIT).
RUN git clone https://github.com/BlinkingSun/stl2step.git . \
    && git checkout 7cf77a2

RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DSTL2STEP_BUILD_TESTS=OFF \
    && cmake --build build -j"$(nproc)" --target stl2step_core

# CLI linked by hand, same recipe as docs/reference-engine.md. That doc's workaround
# (missing freeimage/tbb dev symlinks) was specific to a hand-built /snap/freecad OCCT;
# Debian's libocct-*-dev packages ship correct symlinks, so the plain link works here.
RUN L=/usr/lib/x86_64-linux-gnu && \
    g++ -O2 -std=c++17 -pthread -Iinclude -Isrc -I/usr/include/opencascade \
        src/main.cpp build/libstl2step.a -L"$L" \
        $(cd "$L" && ls libTK*.so | sed 's|^lib|-l|;s|\.so$||' | tr '\n' ' ') \
        -Wl,-rpath,"$L" -ldl -o build/stl2step

# ---- Stage 2: runtime ----
FROM python:3.11-slim-bookworm

# Same OCCT packages the binary was linked against above, so the shared libs it
# needs at runtime are present (dev packages, not just the runtime ones, to keep
# this one apt-get list identical to the builder stage's).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libocct-foundation-dev libocct-modeling-data-dev libocct-modeling-algorithms-dev \
        libocct-ocaf-dev libocct-data-exchange-dev libocct-visualization-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
COPY webapp/ webapp/
COPY tools/ tools/
RUN pip install --no-cache-dir -e ".[web,repair]"

COPY --from=native-builder /build/build/stl2step /usr/local/bin/stl2step
ENV MESH2STEP_NATIVE=/usr/local/bin/stl2step

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "webapp.server:app", "--host", "0.0.0.0", "--port", "8000"]
