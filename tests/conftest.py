import os
from pathlib import Path

import pytest
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader

DATA_DIR = Path(__file__).parent / "data"


def read_step_volume(path) -> float:
    """True end-to-end round trip: read the exported .step file back with OCCT and
    integrate its volume, rather than trusting the in-memory shape from the writer."""
    reader = STEPControl_Reader()
    status = reader.ReadFile(str(path))
    assert status == IFSelect_RetDone, f"failed to read back {path}"
    reader.TransferRoots()
    shape = reader.OneShape()
    assert not shape.IsNull()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


@pytest.fixture
def tmp_stl(tmp_path):
    def _make(mesh, name="mesh.stl"):
        p = tmp_path / name
        mesh.export(p.as_posix())
        return p

    return _make


@pytest.fixture
def tmp_step(tmp_path):
    return tmp_path / "out.step"


def deployed_engine() -> str:
    """The engine the web app actually serves with.

    MESH2STEP_NATIVE wins, as everywhere else. Otherwise read the systemd drop-in that
    selects the deployed engine, so a promotion audit tests what production runs rather
    than whichever binary happens to sit in the default directory. Falls back to the
    frozen engine when no drop-in is installed.
    """
    env = os.environ.get("MESH2STEP_NATIVE")
    if env:
        return env
    conf = Path.home() / ".config/systemd/user/mesh2step.service.d/native.conf"
    if conf.exists():
        for line in conf.read_text().splitlines():
            if line.startswith("Environment=MESH2STEP_NATIVE="):
                return line.split("=", 2)[2].replace("%h", str(Path.home()))
    return str(Path.home() / ".local/share/mesh2step-native/run.sh")


def reference_engine() -> str:
    """The FROZEN reference engine, for parity tests only.

    A test calling this is declaring itself a parity test: it asserts byte-identity or
    reference behaviour against the engine the goldens were built from, and is expected to
    disagree with whatever is currently deployed. Every other test must use
    deployed_engine(), so that a bare `pytest` run is a promotion signal rather than a
    list of failures that are red by construction.
    """
    return str(Path.home() / ".local/share/mesh2step-native/run.sh")
