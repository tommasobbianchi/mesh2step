"""A loader failure of any kind is a MeshLoadError, which the web app turns into a JSON error (not a 500)."""
import pytest
import trimesh

from mesh2step.io_mesh import MeshLoadError, load_mesh


def test_a_crashing_loader_becomes_a_mesh_load_error(tmp_path, monkeypatch):
    p = tmp_path / "part.3mf"; p.write_bytes(b"not really a 3mf")

    def boom(*a, **k):
        raise ModuleNotFoundError("No module named 'networkx'")

    monkeypatch.setattr(trimesh, "load", boom)
    with pytest.raises(MeshLoadError, match="networkx"):
        load_mesh(p)


def test_a_garbage_stl_is_a_mesh_load_error(tmp_path):
    p = tmp_path / "junk.stl"; p.write_bytes(b"\x00\x01garbage")
    with pytest.raises(MeshLoadError):
        load_mesh(p)
