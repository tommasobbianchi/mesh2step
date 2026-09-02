"""Vertex welding and component splitting into manifold bodies.

Replicates the reference engine's front-end: weld exactly-duplicate vertices,
drop index-degenerate triangles, then flood-fill connected components across
edges used exactly twice. Two solids glued along a non-manifold edge therefore
split into two clean manifold bodies instead of one dirty component that would
need the slower sewing repair.
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class Component:
    verts: np.ndarray  # local Nx3 float64
    tris: np.ndarray  # local Mx3 int64
    n_tris: int
    n_open_edges: int  # edges used by exactly one triangle
    n_conflict_edges: int  # edges used twice, both in the same direction
    n_nonmanifold_edges: int  # edges used by >=3 triangles
    signed_volume: float

    @property
    def is_clean(self) -> bool:
        return (
            self.n_open_edges == 0
            and self.n_conflict_edges == 0
            and self.n_nonmanifold_edges == 0
        )


@dataclass
class SplitResult:
    verts: np.ndarray  # welded global Nx3
    components: list
    n_unique_verts: int
    n_components: int
    watertight: bool
    mesh_volume: float


def weld_and_split(verts, tris) -> SplitResult:
    verts = np.asarray(verts, dtype=np.float64)
    tris = np.asarray(tris, dtype=np.int64)

    welded, inverse = np.unique(verts, axis=0, return_inverse=True)
    remapped = inverse[tris]

    degen = (
        (remapped[:, 0] == remapped[:, 1])
        | (remapped[:, 1] == remapped[:, 2])
        | (remapped[:, 0] == remapped[:, 2])
    )
    remapped = remapped[~degen]
    n_tris = len(remapped)

    edges: dict = {}
    for t, tri in enumerate(remapped):
        for s in range(3):
            a = int(tri[s])
            b = int(tri[(s + 1) % 3])
            key = (a, b) if a < b else (b, a)
            edges.setdefault(key, []).append(t)

    parent = list(range(n_tris))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for ts in edges.values():
        if len(ts) == 2:
            ra, rb = find(ts[0]), find(ts[1])
            if ra != rb:
                parent[rb] = ra

    comp_tris: dict = {}
    for t in range(n_tris):
        comp_tris.setdefault(find(t), []).append(t)

    components = []
    for tids in comp_tris.values():
        global_tris = remapped[np.asarray(tids, dtype=np.int64)]
        edge_cnt: dict = {}
        edge_fwd: dict = {}
        for a, b, c in global_tris:
            for u, w in ((a, b), (b, c), (c, a)):
                key = (int(u), int(w)) if u < w else (int(w), int(u))
                edge_cnt[key] = edge_cnt.get(key, 0) + 1
                if u < w:
                    edge_fwd[key] = edge_fwd.get(key, 0) + 1
        n_open = sum(1 for n in edge_cnt.values() if n == 1)
        n_nonmanifold = sum(1 for n in edge_cnt.values() if n > 2)
        n_conflict = sum(
            1 for k, n in edge_cnt.items() if n == 2 and edge_fwd.get(k, 0) != 1
        )

        used = np.unique(global_tris)
        remap = {int(g): i for i, g in enumerate(used)}
        local_tris = np.array(
            [
                [remap[int(a)], remap[int(b)], remap[int(c)]]
                for a, b, c in global_tris
            ],
            dtype=np.int64,
        )
        local_verts = welded[used]

        pa = local_verts[local_tris[:, 0]]
        pb = local_verts[local_tris[:, 1]]
        pc = local_verts[local_tris[:, 2]]
        signed_volume = float(
            np.sum(
                pa[:, 0] * (pb[:, 1] * pc[:, 2] - pb[:, 2] * pc[:, 1])
                - pa[:, 1] * (pb[:, 0] * pc[:, 2] - pb[:, 2] * pc[:, 0])
                + pa[:, 2] * (pb[:, 0] * pc[:, 1] - pb[:, 1] * pc[:, 0])
            )
            / 6.0
        )

        components.append(
            Component(
                verts=local_verts,
                tris=local_tris,
                n_tris=len(local_tris),
                n_open_edges=n_open,
                n_conflict_edges=n_conflict,
                n_nonmanifold_edges=n_nonmanifold,
                signed_volume=signed_volume,
            )
        )

    components.sort(key=lambda c: -c.n_tris)

    mesh_volume = sum(abs(c.signed_volume) for c in components)
    watertight = all(c.is_clean for c in components)

    return SplitResult(
        verts=welded,
        components=components,
        n_unique_verts=len(welded),
        n_components=len(components),
        watertight=watertight,
        mesh_volume=mesh_volume,
    )
