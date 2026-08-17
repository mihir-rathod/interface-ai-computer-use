"""The real end-to-end escalation test: a genuine hard failure against live MockBank pauses a
real ReplayEngine run, a background thread plays the human operator (reading the paused
session's own observed state to find the right element, exactly as the operator console's UI
would let a person do), performs the fix on the SAME live session via SessionManager, and
resumes -- proving the full pause/handoff/resume loop works, not just its pieces in isolation.
"""
from __future__ import annotations

import json
import threading
import time

from artifacts_lib.schema import ActionType, Artifact
from escalation.session_manager import SessionManager, SessionMode
from evidence_lib.logger import EvidenceLogger
from replay.engine import ReplayEngine
from replay.result import ReplayStatus
from surface.base import Action
from surface.web import WebSurface
from tests.conftest import login
from tests.test_replay_engine import LOOKUP_ARTIFACT_PATH


def test_human_fixes_a_broken_locator_via_the_live_session_and_replay_resumes(page, mockbank_base_url, tmp_path):
    login(page, mockbank_base_url)

    # Break s2's own action target (a bad css selector), but leave its checkpoint's target
    # intact -- this models a realistic drift scenario: the primary locator for *acting* has
    # gone stale, but the independently-declared checkpoint locator still correctly reflects
    # whether the field actually holds the right value once a human sets it directly.
    raw = json.loads(LOOKUP_ARTIFACT_PATH.read_text())
    raw["steps"][1]["target"]["locators"] = [{"strategy": "css", "value": "#totally-does-not-exist"}]
    artifact = Artifact.model_validate(raw)

    surface = WebSurface(page, base_url=mockbank_base_url, screenshot_dir=tmp_path / "screenshots")
    logger = EvidenceLogger(tmp_path)
    session = SessionManager("live-escalation-test", surface, tmp_path, evidence_logger=logger, capability_id=artifact.capability_id, goal="test")
    engine = ReplayEngine(surface, evidence_logger=logger, session_manager=session)

    operator_done = threading.Event()

    def operator_thread():
        # Wait for the run to actually pause, reading the SAME live session's published state
        # -- exactly what a human would see on the operator console page.
        deadline = time.monotonic() + 10
        while session.mode != SessionMode.PAUSED and time.monotonic() < deadline:
            time.sleep(0.05)
        assert session.mode == SessionMode.PAUSED
        assert session.pause_reason is not None
        assert session.current_step_id == "s2"

        member_id_ref = next(el.ref for el in session.latest_observed.elements if el.role == "textbox" and el.name == "Member ID")
        session.request_action(Action(kind=ActionType.TYPE, ref=member_id_ref, params={"text": "10001"}, actor="human"))
        time.sleep(0.5)  # let the automation thread drain the queue and act on it
        session.resume()
        operator_done.set()

    threading.Thread(target=operator_thread, daemon=True).start()

    result = engine.run(artifact, {"member_id": "10001"})

    assert operator_done.wait(timeout=15)
    assert result.status == ReplayStatus.SUCCESS, result.error
    assert result.outputs["savings_balance"] == 4231.55
    assert session.mode == SessionMode.AUTOMATION  # handed all the way back

    events = [json.loads(line) for line in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert any(e["event_type"] == "pause" for e in events)
    assert any(e["event_type"] == "resume" for e in events)
    assert any(e["actor"] == "human" and e["event_type"] == "action" for e in events)
    assert (tmp_path / "interventions").exists()
    assert len(list((tmp_path / "interventions").glob("*.json"))) == 1
