"""See a part from a distance: coarse, closed, clean, axis-aligned shape."""
import numpy as np
import trimesh
from scipy import ndimage


def simplify(mesh, p=0.01, max_faces=20000):
    """Reduce a mesh to its coarse axis-aligned shape seen from distance p, by dual contouring: sharp corners by
    construction where marching cubes rounded them (runs/second_opinion/answer.md). Watertight 56/56 (28 scans x
    p 0.01, 0.0025; runs/second_opinion/kimi_dc.md).
    Checkerboard grid faces (4 alternating corner signs of the smoothed field) are disambiguated
    up front; without that their dual edges are shared by 4 quads and the mesh is non-manifold."""
    occ, lo, h, T = _occupancy(mesh, p)
    out = _finish(_dual_contour(occ, lo, h), h, max_faces)
    _sharpen_corners(out)
    return out, T


simplify_dc = simplify


def _occupancy(mesh, p):
    """Closed occupancy grid of the mesh in its oriented-bounds frame; pitch p * diagonal."""
    import igl
    mesh = mesh.copy()
    mesh.merge_vertices()
    T0 = trimesh.bounds.oriented_bounds(mesh)[0]
    aligned = mesh.copy().apply_transform(T0)
    h = p * np.linalg.norm(aligned.extents)
    lo = aligned.bounds[0] - 3*h
    hi = aligned.bounds[1] + 3*h
    axes = [np.arange(lo[i] + h/2, hi[i], h) for i in range(3)]
    G = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
    w = igl.fast_winding_number(np.asarray(aligned.vertices, float), np.asarray(aligned.faces, np.int64), G)
    occ = (w > 0.5).reshape(len(axes[0]), len(axes[1]), len(axes[2]))
    occ = ndimage.binary_closing(occ, iterations=1); occ = ndimage.binary_fill_holes(occ)
    return occ, lo, h, np.linalg.inv(T0)


def _finish(surface, pitch, max_faces):
    _flatten_faces(surface, pitch)    # snap axis-aligned faces on the DENSE mesh
    out = _decimate(surface, max_faces)
    out.fix_normals()
    return out


def _dual_contour(occ, lo, h, sigma=1.2, lam=0.1):
    """Watertight dual contouring of a bool occupancy grid (node (i,j,k) at lo + h/2 + (i,j,k)*h).
    Sign changes and Hermite normals both come from the smoothed field, never from the scan: the scan's
    normals are noise (median 18 deg tilt), and a binary grid's checkerboard faces make it non-manifold."""
    occ = np.pad(occ, 1, constant_values=False)
    f = ndimage.gaussian_filter(occ.astype(np.float64), sigma)   # 0..1, surface at 0.5
    origin = lo - h/2
    cdims = np.array(occ.shape) - 1
    g = np.stack(np.gradient(f, h, h, h), axis=-1)               # points inside; outward is -g
    sign = _disambiguate(f)
    cells, pts, norms = [], [], []
    for ax in range(3):
        idx = np.argwhere(np.diff(sign.astype(np.int8), axis=ax) != 0)
        nxt = tuple((idx + np.eye(3, dtype=int)[ax]).T)
        f0, f1 = f[tuple(idx.T)], f[nxt]
        t = np.clip(np.where(np.abs(f1 - f0) < 1e-12, 0.5, (0.5 - f0) / np.where(f1 == f0, 1, f1 - f0)), 0, 1)
        pts.append(origin + idx * h + t[:, None] * np.eye(3)[ax] * h)
        gc = (1 - t)[:, None] * g[tuple(idx.T)] + t[:, None] * g[nxt]
        norms.append(-gc / np.maximum(np.linalg.norm(gc, axis=1, keepdims=True), 1e-12))
        ay, az = [k for k in range(3) if k != ax]
        off = np.zeros((4, 3), np.int64)
        off[:, ay] = [0, 1, 1, 0]
        off[:, az] = [0, 0, 1, 1]
        c = idx[:, None, :] - off[None]
        cells.append((c[..., 0] * cdims[1] + c[..., 1]) * cdims[2] + c[..., 2])
    cells, pts, norms = np.concatenate(cells), np.concatenate(pts), np.concatenate(norms)

    # QEF per active cell (each edge feeds its 4 cells); compact arrays, a full-grid H OOMs on fine sweeps
    active, inv = np.unique(cells.ravel(), return_inverse=True)
    n4, p4 = np.repeat(norms, 4, axis=0), np.repeat(pts, 4, axis=0)
    H = np.zeros((len(active), 3, 3)); rhs = np.zeros((len(active), 3))
    np.add.at(H, inv, np.einsum("ij,ik->ijk", n4, n4))
    np.add.at(rhs, inv, n4 * np.einsum("ij,ij->i", n4, p4)[:, None])
    centers = origin + (np.array(np.unravel_index(active, cdims)).T + 0.5) * h
    verts = np.linalg.solve(H + lam**2 * np.eye(3), (rhs + lam**2 * centers)[..., None])[..., 0]
    verts = np.clip(verts, centers - h/2, centers + h/2)

    q = inv.reshape(-1, 4)                                       # one quad per edge, wound outward
    v = verts[q]
    flip = np.einsum("ij,ij->i", np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), norms) < 0
    q = np.where(flip[:, None], q[:, [0, 3, 2, 1]], q)
    surface = trimesh.Trimesh(vertices=verts, faces=q[:, [0, 1, 2, 0, 2, 3]].reshape(-1, 3), process=False)
    surface.merge_vertices()
    surface.fix_normals()
    return surface


def _disambiguate(f, iters=256):
    """Flip near-tie corners until no grid face is a checkerboard (4 alternating corner signs).

    A face with 4 sign-changing boundary edges gives the dual edge between its two cell
    vertices 4 incident quads -> non-manifold (measured 1:1 with every bad edge in
    runs/second_opinion/classify_*.log). Flipping the corner closest to the isolevel makes
    the face 3-1 -> exactly 2 sign-changing edges. Crossings/normals still come from f.
    Corners flip at most twice (once freely, once as a forced move on a stuck face), so the
    loop terminates; measured 2-3 passes on the most ambiguous scans (2, 19, 27 @ p=0.0025)."""
    sign = f > 0.5
    flips = np.zeros(f.shape, np.int8)
    for _ in range(iters):
        faces = []
        for ax in range(3):
            oax = [a for a in range(3) if a != ax]
            def sl(dj, dk):
                s = [slice(None)] * 3
                s[oax[0]] = slice(0, -1) if dj == 0 else slice(1, None)
                s[oax[1]] = slice(0, -1) if dk == 0 else slice(1, None)
                return tuple(s)
            c000, c011, c010, c001 = sign[sl(0, 0)], sign[sl(1, 1)], sign[sl(1, 0)], sign[sl(0, 1)]
            amb = (c000 == c011) & (c010 == c001) & (c000 != c010)
            for loc in np.argwhere(amb):
                i, j, k = (int(x) for x in loc)
                corners = []
                for dj in (0, 1):
                    for dk in (0, 1):
                        c = [i, j, k]
                        c[oax[0]] += dj
                        c[oax[1]] += dk
                        corners.append(tuple(c))
                faces.append(corners)
        if not faces:
            return sign
        faces.sort(key=lambda cs: min(abs(f[c] - 0.5) for c in cs))
        for corners in faces:
            c0, c1, c2, c3 = corners
            if not (sign[c0] == sign[c3] and sign[c1] == sign[c2] and sign[c0] != sign[c1]):
                continue  # already resolved by an earlier flip this pass
            for budget in (1, 2):                      # 1 = free flip, 2 = forced flip of a pinned corner
                for c in sorted(corners, key=lambda c: abs(f[c] - 0.5)):
                    if flips[c] < budget:
                        sign[c] = ~sign[c]
                        flips[c] += 1
                        break
                else:
                    continue
                break
            else:
                raise RuntimeError(f"_disambiguate: unresolvable checkerboard face at {corners[0]}")
    raise RuntimeError(f"_disambiguate: {len(faces)} checkerboard faces left after {iters} passes")


def _sharpen_corners(mesh):
    """Snap the nearest vertex to each bbox corner, filling the chamfer decimation leaves; vertices only."""
    if mesh.is_empty:                 # p so coarse the part vanished; the sweep's volume gate reports it
        return mesh
    lo, hi = mesh.bounds
    for c in np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]):
        mesh.vertices[int(np.linalg.norm(mesh.vertices - c, axis=1).argmin())] = c
    return mesh


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
