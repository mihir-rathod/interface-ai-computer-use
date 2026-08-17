"""Tests for the operator console's HTTP surface via Starlette's TestClient -- no live server,
no browser needed. Uses the same FakeSurface as test_session_manager.py so these stay fast and
independent of Playwright/MockBank; the real end-to-end wiring (a genuine paused replay handed
off through this exact console) is tests/test_escalation_live.py.
"""
from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from escalation.operator_console import app
from escalation.registry import register_session, unregister_session
from escalation.session_manager import SessionManager
from tests.test_session_manager import FakeSurface

client = TestClient(app)


def _paused_session(tmp_path, session_id="test-op-sess"):
    surface = FakeSurface()
    manager = SessionManager(session_id, surface, tmp_path, capability_id="mockbank.test", goal="find the thing")
    manager.update_observed(surface.perceive())
    register_session(manager)
    thread = threading.Thread(target=lambda: manager.pause(reason="stuck on step", step_id="s2"))
    thread.start()
    time.sleep(0.15)  # let pause() actually enter its wait loop before the test proceeds
    return manager, surface, thread


def test_operator_page_shows_pause_context_and_elements(tmp_path):
    manager, _, thread = _paused_session(tmp_path, "sess-page")
    try:
        resp = client.get("/operator/sess-page")
        assert resp.status_code == 200
        assert "stuck on step" in resp.text
        assert "mockbank.test" in resp.text
        assert "find the thing" in resp.text
        assert "Member ID" in resp.text  # from FakeSurface's perceive()
    finally:
        manager.resume()
        thread.join()
        unregister_session("sess-page")


def test_unknown_session_returns_404(tmp_path):
    resp = client.get("/operator/does-not-exist")
    assert resp.status_code == 404


def test_act_endpoint_enqueues_and_executes_on_pausing_thread(tmp_path):
    manager, surface, thread = _paused_session(tmp_path, "sess-act")
    try:
        resp = client.post("/operator/sess-act/act", data={"action_kind": "type", "ref": "e1", "value": "10001", "confirmed": "true"}, follow_redirects=False)
        assert resp.status_code == 303
        time.sleep(0.3)  # give the pausing thread's poll loop a chance to drain the queue
        assert len(surface.actions_performed) == 1
        assert surface.actions_performed[0].params == {"text": "10001"}
        assert surface.actions_performed[0].confirmed is True
        assert surface.acted_on_thread == thread.ident
    finally:
        manager.resume()
        thread.join()
        unregister_session("sess-act")


def test_resume_endpoint_releases_the_paused_thread(tmp_path):
    _manager, _, thread = _paused_session(tmp_path, "sess-resume")
    try:
        assert thread.is_alive()
        resp = client.post("/operator/sess-resume/resume", follow_redirects=False)
        assert resp.status_code == 303
        thread.join(timeout=2)
        assert not thread.is_alive()
    finally:
        unregister_session("sess-resume")


def test_screenshot_endpoint_404_without_one(tmp_path):
    manager, _, thread = _paused_session(tmp_path, "sess-shot")
    try:
        resp = client.get("/operator/sess-shot/screenshot")
        assert resp.status_code == 404
    finally:
        manager.resume()
        thread.join()
        unregister_session("sess-shot")
