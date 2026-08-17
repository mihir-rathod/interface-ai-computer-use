"""Pure-unit tests for SessionManager's pause/resume/command-queue mechanics -- a fake Surface
(no browser) so these run fast and exercise the threading model directly: pause() blocks the
calling thread until resume() is called from elsewhere, and any queued human action is executed
on the *same* thread that called pause(), never on the thread that enqueued it.
"""
from __future__ import annotations

import threading
import time

from artifacts_lib.schema import ActionType
from escalation.session_manager import SessionManager, SessionMode
from evidence_lib.logger import EvidenceLogger
from surface.base import Action, ActionResult, ObservedElement, ObservedState, Surface


class FakeSurface(Surface):
    def __init__(self):
        self.acted_on_thread: int | None = None
        self.actions_performed: list[Action] = []
        self.perceive_calls = 0

    def perceive(self, actor: str = "system") -> ObservedState:
        self.perceive_calls += 1
        return ObservedState(
            url="http://fake/page", title="Fake",
            elements=[ObservedElement(ref="e1", role="textbox", name="Member ID")],
        )

    def act(self, action: Action) -> ActionResult:
        self.acted_on_thread = threading.get_ident()
        self.actions_performed.append(action)
        return ActionResult(success=True)

    def compute_target(self, ref: str):
        raise NotImplementedError

    def check_signal(self, signal) -> bool:
        raise NotImplementedError


def _manager(tmp_path) -> tuple[SessionManager, FakeSurface]:
    surface = FakeSurface()
    logger = EvidenceLogger(tmp_path)
    manager = SessionManager("sess-1", surface, tmp_path, evidence_logger=logger, capability_id="mockbank.test", goal="test goal")
    return manager, surface


def test_pause_blocks_until_resume_is_called(tmp_path):
    manager, _ = _manager(tmp_path)
    manager.update_observed(manager.surface.perceive())

    resumed_at = []

    def call_resume_after_delay():
        time.sleep(0.2)
        resumed_at.append(time.monotonic())
        manager.resume()

    caller_thread = threading.Thread(target=call_resume_after_delay)
    started = time.monotonic()
    caller_thread.start()
    manager.pause(reason="test pause")
    finished = time.monotonic()
    caller_thread.join()

    assert finished - started >= 0.15  # actually blocked, didn't return immediately
    assert manager.mode == SessionMode.AUTOMATION


def test_mode_reflects_pause_and_resume(tmp_path):
    manager, _ = _manager(tmp_path)
    assert manager.mode == SessionMode.AUTOMATION

    def resume_soon():
        time.sleep(0.1)
        manager.resume()

    threading.Thread(target=resume_soon).start()
    manager.pause(reason="stuck")
    assert manager.mode == SessionMode.AUTOMATION


def test_human_action_executes_on_the_pausing_thread(tmp_path):
    manager, surface = _manager(tmp_path)
    pausing_thread_id = threading.get_ident()

    def operator_submits_action_then_resumes():
        time.sleep(0.1)
        manager.request_action(Action(kind=ActionType.TYPE, ref="e1", params={"text": "10001"}, actor="human"))
        time.sleep(0.2)  # give the pausing thread a chance to drain the queue
        manager.resume()

    threading.Thread(target=operator_submits_action_then_resumes).start()
    manager.pause(reason="stuck")

    assert len(surface.actions_performed) == 1
    assert surface.actions_performed[0].params == {"text": "10001"}
    assert surface.acted_on_thread == pausing_thread_id  # NOT the operator/enqueueing thread


def test_intervention_request_written_to_evidence(tmp_path):
    manager, _ = _manager(tmp_path)
    threading.Thread(target=lambda: (time.sleep(0.05), manager.resume())).start()
    manager.pause(reason="something went wrong", step_id="s3")

    files = list((tmp_path / "interventions").glob("*.json"))
    assert len(files) == 1
    import json
    data = json.loads(files[0].read_text())
    assert data["reason"] == "something went wrong"
    assert data["step_id"] == "s3"
    assert data["capability_id"] == "mockbank.test"
    assert data["goal"] == "test goal"


def test_snapshot_reports_current_state(tmp_path):
    manager, _ = _manager(tmp_path)
    manager.update_observed(manager.surface.perceive())
    snap = manager.snapshot()
    assert snap["mode"] == "automation"
    assert snap["capability_id"] == "mockbank.test"
    assert snap["observed"].url == "http://fake/page"
