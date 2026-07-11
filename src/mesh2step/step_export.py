"""STEP export. Schema is set via Interface_Static, matching how every OCCT-based
STEP writer (FreeCAD, 2STEP-Converter, OCC-CSG) configures it -- there is no writer
constructor argument for schema in OCCT's API."""
import os
from contextlib import contextmanager
from pathlib import Path

from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.TopoDS import TopoDS_Shape


@contextmanager
def _quiet_stdout():
    """STEPControl_Writer prints an OCCT transfer-statistics banner straight to the
    process's fd 1, bypassing Python's sys.stdout -- redirect the fd itself."""
    saved_fd = os.dup(1)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, 1)
        yield
    finally:
        os.dup2(saved_fd, 1)
        os.close(saved_fd)
        os.close(devnull_fd)

_SCHEMA_TOKENS = {
    "ap203": "AP203",
    "ap214": "AP214IS",
    "ap242": "AP242DIS",
}


class StepExportError(RuntimeError):
    pass


def write_step(shape: TopoDS_Shape, output_path, schema: str = "ap214") -> None:
    schema = schema.lower()
    if schema not in _SCHEMA_TOKENS:
        raise ValueError(f"unknown schema {schema!r}, expected one of {sorted(_SCHEMA_TOKENS)}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    Interface_Static.SetCVal_s("write.step.schema", _SCHEMA_TOKENS[schema])

    writer = STEPControl_Writer()
    with _quiet_stdout():
        status = writer.Transfer(shape, STEPControl_AsIs)
        if status != IFSelect_RetDone:
            raise StepExportError(f"STEP transfer failed with status {status}")

        status = writer.Write(output_path.as_posix())
        if status != IFSelect_RetDone:
            raise StepExportError(f"STEP write failed with status {status}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise StepExportError(f"STEP writer reported success but {output_path} is missing/empty")
