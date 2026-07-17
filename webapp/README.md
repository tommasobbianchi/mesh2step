# mesh2step web app (MVP)

BumpMesh-style single-page front-end + FastAPI backend that runs the real OCCT
conversion server-side. Visual language studied in
[`../docs/bumpmesh-design-study.md`](../docs/bumpmesh-design-study.md).

## Run

```sh
pip install -e ".[web]"          # fastapi, uvicorn, python-multipart
python webapp/server.py          # -> http://127.0.0.1:8000
# or: uvicorn webapp.server:app --reload
```

Open the URL, drag in an `.stl/.obj/.3mf/.ply`, tune tolerance / merge-coplanar /
STEP format in the sidebar, hit **Convert to STEP**, read the live stats, download.

## Architecture

- **Frontend** (`static/`): zero-framework — plain HTML + CSS + ES-module JS +
  three.js 0.170 via CDN importmap. Renders the mesh locally for preview
  (STL/OBJ/PLY/3MF loaders); orbit/pan/zoom; wireframe + light/dark theme;
  **Select &amp; cut** panel with box, plane, and lasso gizmos for previewing
  and accumulating centroid-mask cut operations before conversion.
  Interactive **component picker**: split into connected components, click a
  colored part to select it, then Delete selected or Keep only selected
  (replaces auto keep-largest).
- **Backend** (`server.py`): `POST /api/convert` (multipart) runs
  `mesh2step.convert.convert_file`, returns the full `ConvertStats` as JSON plus a
  one-time download token; `GET /api/download/{token}` streams the STEP file.
  `POST /api/edit` applies cut operations to the uploaded mesh and returns the
  result as an STL preview (with `X-Mesh-Stats` header). In-memory job registry,
  1h TTL — **single-worker only**; move results to object storage + a real queue
  before scaling out or adding billing.

## Not yet (future SaaS)

- Auth / accounts / billing / quotas (this MVP is anonymous and unlimited).
- Multi-worker: the job registry and temp files are per-process.
- The privacy story differs from BumpMesh: meshes **are** uploaded (OCCT can't run
  in-browser). Files are deleted after 1h; state that clearly if this ships.
- Client-side render is best-effort; a mesh that fails to preview can still convert.
