Fixture corpus vendored from stl2step (MIT, https://github.com/BlinkingSun/stl2step @ 7cf77a2),
used as the parity oracle for mesh2step v2. Kept here so the overlay suite is self-contained
and does not depend on `refs/` (gitignored) continuing to exist.

| file | tris | why it is in the corpus |
|---|---|---|
| `cube.stl` | 12 | trivial closed solid; 6 faces after coplanar merge |
| `S09.stl` | 54 | two disjoint bodies — exercises component splitting |
| `nonprismatic-control.stl` | 96 | negative control: TrueForm must decline, not invent |
| `handle-lock.stl` | 908 | fully prismatic real CAD export; 15 analytic cylinders |
| `Body11.stl` | 15300 | 69 non-manifold edges; mesh2step v1 fails to close it |
| `Body28.stl` | 14126 | dense real body; 40 degenerate triangles |
