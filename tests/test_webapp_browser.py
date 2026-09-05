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
            return (p && !p.classList.contains('hidden'))
                || (s && !s.classList.contains('hidden') && s.textContent.trim());
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
