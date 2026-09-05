"""Drive the real UI in a browser.

Two bugs shipped in one day that every API-level test was blind to: the client
rendered stats keys the native engine does not emit ("Cannot read properties of
undefined (reading 'toLocaleString')"), and three's 3MFLoader died on files the
server reads fine. Both are DOM-level failures behind a 200 OK, so this is the
only test here that clicks the button a user clicks.
"""
import pathlib
import socket
import sys
import threading

import pytest
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

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


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        except Exception as e:  # no downloaded browser on this host
            pytest.skip(f"chromium unavailable: {e}")
        yield b
        b.close()


@pytest.fixture
def cube_stl(tmp_path):
    p = tmp_path / "cube.stl"
    trimesh.creation.box((10, 10, 10)).export(str(p))
    return str(p)


@pytest.mark.parametrize("engine", ["faceted", "trueform"])
def test_convert_renders_stats_in_the_browser(browser, live_url, cube_stl, engine):
    errors = []
    page = browser.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(live_url, wait_until="networkidle", timeout=60000)
    page.evaluate("document.getElementById('welcome-overlay').classList.add('hidden')")
    page.set_input_files("#file-input", cube_stl)
    page.wait_for_timeout(1500)
    page.select_option("#engine", engine)
    page.click("#convert-btn")
    # Either outcome ends the wait: a rendered panel, or a status line. Waiting
    # only for the panel turns a failed render into a timeout instead of a
    # readable assertion.
    page.wait_for_function(
        """() => {
            const p = document.getElementById('stats-panel');
            const s = document.getElementById('convert-status');
            const t = s ? s.textContent.trim() : '';
            // 'Converting on server...' is set synchronously on click: waiting on
            // any status text at all would race the request and pass vacuously.
            return (p && !p.classList.contains('hidden'))
                || (t && !t.startsWith('Converting'));
        }""",
        timeout=120000,
    )
    status = page.inner_text("#convert-status")
    assert "Failed" not in status and "error" not in status.lower(), status
    assert not page.locator("#stats-panel").is_hidden(), "no stats rendered"
    stats = page.inner_text("#stats-panel")
    assert "undefined" not in stats and "NaN" not in stats, stats
    assert "Download" in stats
    assert errors == [], errors
    page.close()


def test_lost_circle_gets_an_actionable_warning(browser, live_url, tmp_path):
    # 96 segments per circle -> 3.75 deg between facets, under the engine's 5 deg
    # cylinder seed band, so the cylinder comes out as 96 planar strips.
    import trimesh

    p = tmp_path / "cyl96.stl"
    trimesh.creation.cylinder(radius=10, height=20, sections=96).export(str(p))
    page = browser.new_page()
    page.goto(live_url, wait_until="networkidle", timeout=60000)
    page.evaluate("document.getElementById('welcome-overlay').classList.add('hidden')")
    page.set_input_files("#file-input", str(p))
    page.wait_for_timeout(1500)
    page.select_option("#engine", "trueform")
    page.click("#convert-btn")
    page.wait_for_selector("#stats-panel:not(.hidden)", timeout=120000)
    warnings = page.inner_text("#warnings")
    assert "No curved surface was recovered" in warnings, warnings
    assert "72-120" in warnings
    # and it must name the radii it actually measured off the output
    assert "still in the file as polylines" in warnings, warnings
    assert "10.00" in warnings, warnings
    page.close()


def test_prism_rounded_into_a_cylinder_is_flagged(browser, live_url, tmp_path):
    # An 8-sided prism sits inside the engine's [5, 60] deg seed band, so trueform
    # rebuilds it as the circumscribed cylinder: 25132.74 against the mesh's
    # 22627.42, +11.07%, and the engine itself emits no warning.
    import trimesh

    p = tmp_path / "oct.stl"
    trimesh.creation.cylinder(radius=20, height=20, sections=8).export(str(p))
    page = browser.new_page()
    page.goto(live_url, wait_until="networkidle", timeout=60000)
    page.evaluate("document.getElementById('welcome-overlay').classList.add('hidden')")
    page.set_input_files("#file-input", str(p))
    page.wait_for_timeout(1500)
    page.select_option("#engine", "trueform")
    page.click("#convert-btn")
    page.wait_for_selector("#stats-panel:not(.hidden)", timeout=120000)
    warnings = page.inner_text("#warnings")
    assert "changed the volume by" in warnings, warnings
    assert "11.07" in warnings, warnings
    page.close()
