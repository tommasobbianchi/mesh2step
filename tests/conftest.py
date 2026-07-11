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
