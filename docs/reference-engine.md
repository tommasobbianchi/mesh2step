# Rebuilding the stl2step reference binary

Upstream: https://github.com/BlinkingSun/stl2step @ 7cf77a2 (v1.1.0, 2026-08-30), MIT.

The library builds cleanly with CMake against OCCT 7.6 (orca_cad's pin) and 7.8.
Linking the **CLI** fails on this host for a reason upstream already documents in its
CHANGELOG: distro OCCT CMake configs reference third-party libs by absolute path
(`libtbb.so` upstream, `libfreeimage.so` here) and those dev symlinks are absent.

    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
          -DCMAKE_PREFIX_PATH=/snap/freecad/2337/usr -DSTL2STEP_BUILD_TESTS=OFF
    cmake --build build -j"$(nproc)" --target stl2step_core   # library: clean

    # CLI, linked by hand around the missing freeimage dev symlink:
    L=/snap/freecad/2337/usr/lib
    g++ -O2 -std=c++17 -pthread -Iinclude -Isrc \
        -I/snap/freecad/2337/usr/include/opencascade \
        src/main.cpp build/libstl2step.a -L"$L" \
        $(cd "$L" && ls libTK*.so | sed 's|^lib|-l|;s|\.so$||' | tr '\n' ' ') \
        -Wl,-rpath,"$L" -Wl,-rpath,"$L/x86_64-linux-gnu" -ldl -o build/stl2step

Do NOT add `-L$L/x86_64-linux-gnu` to the link line: it shadows the host libc and ld
then fails to resolve `__tls_get_addr`. rpath only.

Run it through `RUN.sh`, which sets the LD_LIBRARY_PATH the rpath does not cover.
