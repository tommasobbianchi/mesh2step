"""See a part from a distance: coarse, closed, clean, axis-aligned shape."""
import numpy as np
import trimesh
from scipy import ndimage
from skimage import measure


def simplify(mesh, p=0.01, max_faces=20000):
    """Reduce a mesh to its coarse axis-aligned shape seen from distance p."""
    # Step 1: Frame
    mesh = mesh.copy()
    mesh.merge_vertices()
    T0 = trimesh.bounds.oriented_bounds(mesh)[0]
    aligned = mesh.copy().apply_transform(T0)
    T = np.linalg.inv(T0)

    # Step 2: Voxelize and extract surface
    import igl
    pitch = p * np.linalg.norm(aligned.extents)
    h = pitch
    lo = aligned.bounds[0] - 3*h
    hi = aligned.bounds[1] + 3*h
    axes = [np.arange(lo[i] + h/2, hi[i], h) for i in range(3)]
    G = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
    w = igl.fast_winding_number(np.asarray(aligned.vertices, float), np.asarray(aligned.faces, np.int64), G)
    occ = (w > 0.5).reshape(len(axes[0]), len(axes[1]), len(axes[2]))
    occ = ndimage.binary_closing(occ, iterations=1); occ = ndimage.binary_fill_holes(occ)
    field = ndimage.gaussian_filter(occ.astype(float), 1.0)
    verts, faces, _, _ = measure.marching_cubes(field, level=0.5, spacing=(h, h, h))
    verts += lo + h/2                 # grid index 0 sits at lo + h/2
    surface = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    surface.merge_vertices()
    surface.fix_normals()

    # Step 3: Flatten axis-aligned faces (snap, on the DENSE mesh)
    _flatten_faces(surface, pitch)

    # Step 4: Decimate the clean manifold to at most max_faces
    out = _decimate(surface, max_faces)
    out.fix_normals()

    return out, T


def _flatten_faces(mesh, pitch):
    """Snap axis-aligned vertices to flat planes."""
    fnormals = mesh.face_normals
    vnormals = mesh.vertex_normals
    faces = mesh.faces
    n_verts = len(mesh.vertices)

    # Per-vertex count of adjacent faces aligned in each of 6 axis directions
    aligned_counts = np.zeros((n_verts, 6), dtype=np.int32)
    total_counts = np.zeros(n_verts, dtype=np.int32)

    for k in range(3):
        for si, sign in enumerate((1, -1)):
            direction = np.zeros(3)
            direction[k] = sign
            dots = fnormals @ direction
            face_mask = dots > np.cos(np.radians(30))
            np.add.at(aligned_counts[:, k * 2 + si], faces[face_mask].ravel(), 1)

    np.add.at(total_counts, faces.ravel(), 1)

    for k in range(3):
        for si, sign in enumerate((1, -1)):
            idx = k * 2 + si
            # Only snap vertices where ALL adjacent faces are aligned (interior to flat face)
            interior = (aligned_counts[:, idx] == total_counts) & (total_counts > 0)
            if not interior.any():
                continue
            vertex_indices = np.where(interior)[0]
            coords = mesh.vertices[vertex_indices, k]
            n = len(coords)
            lo, hi = coords.min(), coords.max()
            if hi - lo < 1e-10:
                continue
            n_bins = max(1, int(np.ceil((hi - lo) / pitch)))
            hist, bin_edges = np.histogram(coords, bins=n_bins, range=(lo, hi))
            threshold = 0.01 * n
            for i in range(len(hist)):
                if hist[i] >= threshold:
                    if i < len(hist) - 1:
                        bin_mask = (coords >= bin_edges[i]) & (coords < bin_edges[i + 1])
                    else:
                        bin_mask = (coords >= bin_edges[i]) & (coords <= bin_edges[i + 1])
                    peak_median = np.median(coords[bin_mask])
                    # Snap every vertex near this plane within the face extent, regardless of normal
                    other_axes = [j for j in range(3) if j != k]
                    peak_verts = vertex_indices[bin_mask]
                    pv = mesh.vertices[peak_verts]
                    extent_lo = pv[:, other_axes].min(axis=0) - pitch
                    extent_hi = pv[:, other_axes].max(axis=0) + pitch
                    all_verts = mesh.vertices
                    snap_mask = np.abs(all_verts[:, k] - peak_median) <= 1.5 * pitch
                    for j, ax in enumerate(other_axes):
                        snap_mask &= (all_verts[:, ax] >= extent_lo[j]) & (all_verts[:, ax] <= extent_hi[j])
                    snap_mask &= np.abs(vnormals[:, k]) > np.cos(np.radians(60))
                    mesh.vertices[snap_mask, k] = peak_median


def _decimate(mesh, max_faces):
    """Quadric decimation that never merges or cleans the snapped mesh (that is what opened the shell)."""
    if len(mesh.faces) <= max_faces:
        return mesh
    import open3d as o3d
    o = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(np.asarray(mesh.vertices, dtype=np.float64)),
                                  o3d.utility.Vector3iVector(np.asarray(mesh.faces, dtype=np.int32)))
    d = o.simplify_quadric_decimation(max_faces)
    out = trimesh.Trimesh(vertices=np.asarray(d.vertices), faces=np.asarray(d.triangles), process=False)
    out.fix_normals()
    return out if out.is_watertight else mesh
