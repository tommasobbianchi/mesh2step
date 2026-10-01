"""Turn a clean CAD mesh into a scanner-like one for benchmarking."""
import sys

import numpy as np
import trimesh


def scanify(mesh, seed=0, noise=0.003, faces=150000, rotate=True) -> trimesh.Trimesh:
    """Make a clean CAD mesh look like a 3D scan, for benchmarking."""
    rng = np.random.default_rng(seed)

    # 1. Dense re-tessellation: uniform midpoint subdivision until we have enough faces
    result = mesh.copy()
    while len(result.faces) < faces:
        result = result.subdivide()

    # 2. Noise along vertex normals
    result.merge_vertices()
    sigma = noise * np.linalg.norm(mesh.extents)
    normals = result.vertex_normals
    offsets = rng.normal(0.0, sigma, size=len(result.vertices))
    result.vertices = result.vertices + normals * offsets[:, np.newaxis]

    # 3. Random rotation about centroid + translation
    if rotate:
        R = trimesh.transformations.random_rotation_matrix(rand=rng.random(3))
        centroid = result.centroid
        result.vertices = (result.vertices - centroid) @ R[:3, :3].T + centroid
        diag = np.linalg.norm(mesh.extents)
        t = rng.uniform(-0.1, 0.1, size=3) * diag
        result.vertices = result.vertices + t

    return result


if __name__ == "__main__":
    in_stl = sys.argv[1]
    out_stl = sys.argv[2]
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    noise = float(sys.argv[4]) if len(sys.argv) > 4 else 0.003
    faces = int(sys.argv[5]) if len(sys.argv) > 5 else 150000
    m = trimesh.load(in_stl)
    s = scanify(m, seed=seed, noise=noise, faces=faces)
    s.export(out_stl)
