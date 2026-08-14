from __future__ import annotations

from agent.tools import ToolCall, is_terminal, to_action
from artifacts_lib.schema import ActionType


def test_is_terminal_for_finish_and_give_up():
    assert is_terminal(ToolCall("finish", {"reasoning": "done"}))
    assert is_terminal(ToolCall("give_up", {"reasoning": "stuck"}))


def test_is_not_terminal_for_actions():
    assert not is_terminal(ToolCall("click", {"ref": "e1"}))
    assert not is_terminal(ToolCall("extract", {"ref": "e1", "output_name": "x"}))


def test_to_action_navigate():
    action = to_action(ToolCall("navigate", {"url": "/search"}))
    assert action.kind == ActionType.NAVIGATE
    assert action.params == {"url": "/search"}
    assert action.ref is None


def test_to_action_click():
    action = to_action(ToolCall("click", {"ref": "e5"}))
    assert action.kind == ActionType.CLICK
    assert action.ref == "e5"


def test_to_action_type_text():
    action = to_action(ToolCall("type_text", {"ref": "e2", "text": "10001"}))
    assert action.kind == ActionType.TYPE
    assert action.ref == "e2"
    assert action.params == {"text": "10001"}


def test_to_action_select_option():
    action = to_action(ToolCall("select_option", {"ref": "e9", "value": "checking"}))
    assert action.kind == ActionType.SELECT
    assert action.params == {"value": "checking"}


def test_to_action_extract():
    action = to_action(ToolCall("extract", {"ref": "e3", "output_name": "balance"}))
    assert action.kind == ActionType.EXTRACT
    assert action.ref == "e3"
    assert action.params == {}
