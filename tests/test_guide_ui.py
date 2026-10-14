"""The guided feature selection in a real browser (epic guided-*, M3): convert the synthetic plate, open
"Refine features", go to the Fillets step, click one fillet triangle, see its radius, build, download a
STEP with the fillet as a real r4 cylinder. The fillet (vertical edge at +30, +20) faces the default camera,
so a click on its projected centroid lands on it.
"""
import pathlib
import socket
import sys
import threading

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import guided_part as G

playwright_api = pytest.importorskip("playwright.sync_api")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_url():
    import uvicorn

    from webapp.server import app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(200):
        if server.started:
            break
        threading.Event().wait(0.05)
    assert server.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}/"
    server.should_exit = True
    t.join(timeout=10)


FILLET_TRIANGLE_JS = """() => {
  const P = window.__guide.mesh, n = P.length / 9, hits = [];
  for (let i = 0; i < n; i++) {
    let on = true;
    for (let k = 0; k < 3; k++) {
      const x = P[9 * i + 3 * k], y = P[9 * i + 3 * k + 1];
      if (Math.abs(Math.hypot(x - 26, y - 16) - 4) > 0.02) on = false;
    }
    if (on) hits.push(i);
  }
  return hits.length ? hits[Math.floor(hits.length / 2)] : -1;
}"""


def test_guided_fillet_to_step(live_url, tmp_path):
    mesh, _, _, _ = G.tessellate(G.part())
    stl = tmp_path / "plate.stl"
    mesh.export(str(stl))
    with playwright_api.sync_playwright() as pw:
        b = pw.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        page = b.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(live_url, wait_until="networkidle", timeout=60000)
        page.evaluate("document.getElementById('welcome-overlay').classList.add('hidden')")
        page.set_input_files("#file-input", str(stl))
        page.wait_for_timeout(1500)
        page.click("#convert-btn")
        page.wait_for_function("() => { const r = document.getElementById('result-card');"
                               " return r && !r.classList.contains('hidden'); }", timeout=180000)

        page.click("#guide-start")
        page.wait_for_function("() => window.__guide && window.__guide.mesh && window.__guide.mesh.length > 0",
                               timeout=60000)
        for _ in range(8):
            if "Fillet" in page.inner_text("#guide-step-title"):
                break
            page.click("#guide-next")
        assert "Fillet" in page.inner_text("#guide-step-title")

        t = page.evaluate(FILLET_TRIANGLE_JS)
        assert t >= 0
        xy = page.evaluate("(t) => window.__guide.project(t)", t)
        page.mouse.click(xy["x"], xy["y"])
        page.wait_for_function("() => /4\\.0/.test(document.getElementById('guide-params').textContent)",
                               timeout=60000)
        assert "partial" in page.inner_text("#guide-params").lower()
        assert len(page.evaluate("() => window.__guide.selections")) == 1

        for _ in range(8):
            if page.is_visible("#guide-build"):
                break
            page.click("#guide-next")
        page.click("#guide-build")
        page.wait_for_selector("#guide-download", state="visible", timeout=600000)
        href = page.get_attribute("#guide-download", "href")
        body = page.request.get(live_url.rstrip("/") + "/" + href.lstrip("/")).body()
        step = tmp_path / "guided.step"
        step.write_bytes(body)
        _, faces, nsol, valid = G.read_step(step)
        assert nsol == 1 and valid
        assert any(k in ("cylinder", "torus") and abs(r - 4) < 0.04 for k, r in faces), faces
        assert errors == [], errors
        b.close()


FILLET_STROKE_JS = """() => {
  // scan triangles on the r4 fillet's quarter arc, one per z band: the path a user's brush drags along
  const P = window.__guide.mesh, n = P.length / 9, best = {};
  for (let i = 0; i < n; i++) {
    let x = 0, y = 0, z = 0;
    for (let k = 0; k < 3; k++) { x += P[9 * i + 3 * k] / 3; y += P[9 * i + 3 * k + 1] / 3; z += P[9 * i + 3 * k + 2] / 3; }
    const off = Math.abs(Math.hypot(x - 26, y - 16) - 4), a = Math.atan2(y - 16, x - 26);
    if (off > 0.5 || Math.abs(z) > 3.5 || Math.abs(a - Math.PI / 4) > 0.3) continue;
    const band = Math.round(z);
    if (!(band in best) || off < best[band][1]) best[band] = [i, off];
  }
  return Object.keys(best).sort((a, b) => a - b).map(k => best[k][0]);
}"""


def test_scan_brush_fillet(live_url, tmp_path):
    """A scan: the user switches to scan mode, brushes the fillet, fits it as a cylinder and reads r4."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
    import scanbench as B

    mesh = G.tessellate(G.part())[0]
    mesh.merge_vertices()
    stl = tmp_path / "plate_scan.stl"
    B.scanify(mesh).export(str(stl))
    with playwright_api.sync_playwright() as pw:
        b = pw.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        page = b.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(live_url, wait_until="networkidle", timeout=60000)
        page.evaluate("document.getElementById('welcome-overlay').classList.add('hidden')")
        page.set_input_files("#file-input", str(stl))
        page.wait_for_timeout(1500)
        page.click("#convert-btn")
        page.wait_for_function("() => { const r = document.getElementById('result-card');"
                               " return r && !r.classList.contains('hidden'); }", timeout=900000)  # 488 s measured
        page.click("#guide-start")
        page.wait_for_function("() => window.__guide && window.__guide.mesh && window.__guide.mesh.length > 0",
                               timeout=60000)
        n0 = page.evaluate("() => window.__guide.mesh.length")
        page.click("#guide-scan")
        page.wait_for_function("(n0) => window.__guide.mesh.length !== n0"
                               " && document.getElementById('guide-status').textContent === ''", arg=n0,
                               timeout=300000)
        assert "Cylinder" in page.inner_text("#guide-step-title")

        stroke = page.evaluate(FILLET_STROKE_JS)
        assert len(stroke) >= 4, stroke
        pts = [page.evaluate("(t) => window.__guide.project(t)", t) for t in stroke]
        page.click("#guide-brush")
        page.mouse.move(pts[0]["x"], pts[0]["y"])
        page.mouse.down()
        for p in pts[1:]:
            page.mouse.move(p["x"], p["y"], steps=4)
        page.mouse.up()
        assert page.evaluate("() => window.__guide.painted.size") >= 10
        page.click("#guide-fit")
        page.wait_for_function("() => /radius/.test(document.getElementById('guide-params').textContent)",
                               timeout=60000)
        txt = page.inner_text("#guide-params")
        assert any(f"radius {r} mm" in txt for r in ("3.9", "4.0", "4.1")), txt
        assert len(page.evaluate("() => window.__guide.selections")) == 1
        assert errors == [], errors
        b.close()


NEAR_JS = """(q) => {
  const P = window.__guide.mesh, n = P.length / 9;
  let best = -1, bd = Infinity;
  for (let i = 0; i < n; i++) {
    let d = 0;
    for (let a = 0; a < 3; a++) {
      const c = (P[9 * i + a] + P[9 * i + 3 + a] + P[9 * i + 6 + a]) / 3 - q[a];
      d += c * c;
    }
    if (d < bd) { bd = d; best = i; }
  }
  return best;
}"""


def test_scan_gauge(live_url, tmp_path):
    """The V-gauge (bd projects-vgj7.4): in scan mode the user clicks Gauge, clicks the plate's top/back edge, accepts,
    and the gauge is a selection with two exactly perpendicular planes. The job is converted from the clean plate (fast)
    and its mesh swapped for the scanned one before the guide opens: the subject is the gauge, not converting a scan."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
    import scanbench as B

    from webapp import server

    mesh = G.tessellate(G.part())[0]
    stl = tmp_path / "plate.stl"
    mesh.export(str(stl))
    mesh.merge_vertices()
    scan = tmp_path / "plate_scan.stl"
    B.scanify(mesh).export(str(scan))
    with playwright_api.sync_playwright() as pw:
        b = pw.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        page = b.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(live_url, wait_until="networkidle", timeout=60000)
        page.evaluate("document.getElementById('welcome-overlay').classList.add('hidden')")
        page.set_input_files("#file-input", str(stl))
        page.wait_for_timeout(1500)
        page.click("#convert-btn")
        page.wait_for_function("() => { const r = document.getElementById('result-card');"
                               " return r && !r.classList.contains('hidden'); }", timeout=180000)
        job = max((j for j in server._JOBS.values() if j.get("stl")), key=lambda j: j["ts"])
        job["stl"] = scan
        job.pop("tri", None)
        page.click("#guide-start")
        page.wait_for_function("() => window.__guide && window.__guide.mesh && window.__guide.mesh.length > 0",
                               timeout=60000)
        n0 = page.evaluate("() => window.__guide.mesh.length")
        page.click("#guide-scan")
        page.wait_for_function("(n0) => window.__guide.mesh.length !== n0"
                               " && document.getElementById('guide-status').textContent === ''", arg=n0,
                               timeout=300000)
        assert page.is_visible("#guide-gauge")
        page.click("#guide-gauge")
        t = page.evaluate(NEAR_JS, [10, 19.5, 5])
        xy = page.evaluate("(t) => window.__guide.project(t)", t)
        page.mouse.click(xy["x"], xy["y"])
        page.wait_for_selector("#guide-gauge-accept", state="visible", timeout=60000)
        assert "90" in page.inner_text("#guide-gauge-info")
        page.click("#guide-gauge-accept")
        sel = page.evaluate("() => window.__guide.selections")
        assert len(sel) == 1 and sel[0]["kind"] == "gauge" and len(sel[0]["planes"]) == 2, sel
        n1, n2 = (p["normal"] for p in sel[0]["planes"])
        assert abs(sum(a * c for a, c in zip(n1, n2, strict=True))) < 1e-9
        assert page.locator(".guide-gauge-remove").count() == 1
        page.click(".guide-gauge-remove")
        assert page.evaluate("() => window.__guide.selections.length") == 0
        assert errors == [], errors
        b.close()
