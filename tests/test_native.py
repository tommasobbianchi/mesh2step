from pathlib import Path

from mesh2step.native import convert_native, native_available, native_binary

CORPUS = Path(__file__).resolve().parent / "data" / "corpus"


def test_native_available_on_this_host():
    assert native_available() is True
    binary = native_binary()
    assert binary is not None
    assert binary.exists()


def test_convert_native_verbatim_cube(tmp_path):
    out = tmp_path / "cube.step"
    res = convert_native(CORPUS / "cube.stl", out, engine="verbatim")
    assert res["exit_code"] == 0
    assert res["solids"] == 1
    assert out.read_bytes().startswith(b"ISO-10303-21")


def test_convert_native_trueform_nonprismatic_exit_2(tmp_path):
    out = tmp_path / "nonprismatic.step"
    res = convert_native(CORPUS / "nonprismatic-control.stl", out, engine="trueform")
    assert res["exit_code"] == 2
    assert res["warnings"]
    assert out.read_bytes().startswith(b"ISO-10303-21")
