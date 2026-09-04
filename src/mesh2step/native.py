"""Thin wrapper around the native stl2step C++ engine.

The web app routes conversions through the native binary when it is present,
falling back to the Python engines otherwise. The binary takes STL only and
prints ``RESULT {json}`` as its last stdout line; exit 0 = clean, 2 =
written-with-warnings, 1 = failed. The parsed payload is returned unchanged
(plus an ``exit_code`` key), so the caller decides what exit 2 means.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_DEFAULT_TIMEOUT = 900.0


class NativeEngineError(RuntimeError):
    """Raised when the native engine cannot be located, run, or parsed."""


class NativeUnavailable(NativeEngineError):
    def __init__(self) -> None:
        super().__init__(
            "stl2step native engine is required but not found; "
            "set MESH2STEP_NATIVE to the path of the stl2step binary"
        )


class NativeTimeout(NativeEngineError):
    def __init__(self, seconds: float) -> None:
        super().__init__(f"stl2step exceeded the {seconds}s timeout")


class NativeParseError(NativeEngineError):
    def __init__(self, stdout: str) -> None:
        super().__init__(f"stl2step emitted no RESULT line (stdout: {stdout.strip()[-400:]!r})")


class InvalidEngine(ValueError):
    def __init__(self, engine: str) -> None:
        super().__init__(f"invalid engine {engine!r}; must be verbatim or trueform")


def native_binary() -> Path | None:
    env = os.environ.get("MESH2STEP_NATIVE")
    if env:
        p = Path(env)
        return p if p.exists() else None
    launcher = _REPO_ROOT / "refs" / "stl2step" / "RUN.sh"
    if launcher.exists():
        return launcher
    found = shutil.which("stl2step")
    return Path(found) if found else None


def native_available() -> bool:
    return native_binary() is not None


def convert_native(
    input_path,
    output_path,
    *,
    engine: str = "verbatim",
    schema: str = "ap214",
    unify_angle: float | None = None,
    no_unify: bool = False,
    verify: bool = True,
    timeout: float | None = None,
) -> dict:
    binary = native_binary()
    if binary is None:
        raise NativeUnavailable()
    if engine not in ("verbatim", "trueform"):
        raise InvalidEngine(engine)

    cmd = [
        str(binary),
        str(input_path),
        "-o",
        str(output_path),
        "--engine",
        engine,
        "--schema",
        schema,
        "--quiet",
    ]
    if no_unify:
        # The binary's default is --unify-angle 0.001, which MERGES coplanar
        # triangles. The Python faceted engine does not merge unless asked, so
        # without this the faceted STEP silently changes (a cube: 12 faces -> 6).
        cmd += ["--no-unify"]
    elif unify_angle is not None:
        cmd += ["--unify-angle", str(unify_angle)]
    if not verify:
        # Skip the binary's re-read + volume check; the caller verifies the
        # output itself. Meaningfully faster on large faceted meshes.
        cmd += ["--no-verify"]

    seconds = timeout if timeout is not None else _DEFAULT_TIMEOUT
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds)
    except subprocess.TimeoutExpired:
        raise NativeTimeout(seconds) from None

    result = _parse_result(proc.stdout)
    result["exit_code"] = proc.returncode
    return result


def _parse_result(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT ") :])
    raise NativeParseError(stdout)
