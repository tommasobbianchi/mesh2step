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


def _wait_for_outcome(page):
    """Either the result card appears or a status line that is not the in-progress
    one. Waiting on any status text at all would race the request."""
    page.wait_for_function(
        """() => {
            const r = document.getElementById('result-card');
            const s = document.getElementById('convert-status');
            const t = s ? s.textContent.trim() : '';
            return (r && !r.classList.contains('hidden'))
                || (t && !t.startsWith('Converting'));
        }""",
        timeout=180000,
    )


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
    page.click("#advanced > summary")      # engine lives under Options now
    page.select_option("#engine", engine)
    page.click("#convert-btn")
    # Either outcome ends the wait: a rendered panel, or a status line. Waiting
    # only for the panel turns a failed render into a timeout instead of a
    # readable assertion.
    _wait_for_outcome(page)
    status = page.inner_text("#convert-status")
    assert "Failed" not in status and "error" not in status.lower(), status
    # the result card is the primary surface now; the numbers live under Options
    result = page.inner_text("#result-card")
    assert "Download" in result, result
    assert "undefined" not in result and "NaN" not in result, result
    assert errors == [], errors
    page.close()


def test_a_circle_in_the_detection_gap_is_rebuilt_not_just_reported(browser, live_url, tmp_path):
    """96 segments per circle is 3.75 deg between facets, under the engine's 5 deg
    seed band, so it used to come back as 96 planar strips and a warning naming
    what was lost. Now it is rebuilt, and the result says so in plain words."""
    import trimesh

    p = tmp_path / "cyl96.stl"
    trimesh.creation.cylinder(radius=10, height=20, sections=96).export(str(p))
    page = browser.new_page()
    page.goto(live_url, wait_until="networkidle", timeout=60000)
    page.evaluate("document.getElementById('welcome-overlay').classList.add('hidden')")
    page.set_input_files("#file-input", str(p))
    page.wait_for_timeout(1500)
    page.click("#convert-btn")
    _wait_for_outcome(page)

    result = page.inner_text("#result-card")
    assert "Ready to download" in result, result
    assert "round surface" in result, result          # it says what it rebuilt
    warnings = page.inner_text("#warnings")
    assert "No curved surface was recovered" not in warnings, warnings
    assert "volume differs" not in warnings, warnings  # stale: describes the old result
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
    page.click("#advanced > summary")
    page.select_option("#engine", "trueform")
    page.click("#convert-btn")
    _wait_for_outcome(page)
    warnings = page.inner_text("#warnings")
    assert "changed the volume by" in warnings, warnings
    assert "11.07" in warnings, warnings
    page.close()
