"""Integration tests for WebSurface against a real (in-process) MockBank + real Chromium.

Each test logs in independently (fresh Playwright context => fresh cookies => a fresh
server-side session), so tests don't need to worry about interfering with each other's login
state. None of them mutate member data, so the session-scoped MockBank server can be shared.
"""
from __future__ import annotations

import json

from artifacts_lib.schema import ActionType, Locator, Target
from evidence_lib.logger import EvidenceLogger
from surface.base import Action
from surface.web import WebSurface
from tests.conftest import login


def test_perceive_login_page(page, mockbank_base_url):
    page.goto(f"{mockbank_base_url}/login")
    surface = WebSurface(page, base_url=mockbank_base_url)
    state = surface.perceive()
    roles_names = {(el.role, el.name) for el in state.elements}
    assert ("textbox", "Username") in roles_names
    assert ("textbox", "Password") in roles_names
    assert ("button", "Log In") in roles_names
    assert state.url.endswith("/login")


def test_act_by_ref_full_login_flow(page, mockbank_base_url):
    page.goto(f"{mockbank_base_url}/login")
    surface = WebSurface(page, base_url=mockbank_base_url)
    state = surface.perceive()

    username_ref = next(el.ref for el in state.elements if el.role == "textbox" and el.name == "Username")
    password_ref = next(el.ref for el in state.elements if el.role == "textbox" and el.name == "Password")
    login_ref = next(el.ref for el in state.elements if el.role == "button" and el.name == "Log In")

    assert surface.act(Action(kind=ActionType.TYPE, ref=username_ref, params={"text": "operator"})).success
    assert surface.act(Action(kind=ActionType.TYPE, ref=password_ref, params={"text": "bankdemo123"})).success
    assert surface.act(Action(kind=ActionType.CLICK, ref=login_ref)).success
    page.wait_for_url("**/search")


def test_act_by_target_and_extract(page, mockbank_base_url):
    login(page, mockbank_base_url)
    page.get_by_role("textbox", name="Member ID").fill("10003")
    page.get_by_role("button", name="Search").click()
    page.wait_for_url("**/member/10003")

    surface = WebSurface(page, base_url=mockbank_base_url)
    target = Target(
        semantic_description="account status cell",
        locators=[
            Locator(strategy="role", value="cell[name='Account Status value']"),
            Locator(strategy="css", value="#account-status-value"),
        ],
    )
    result = surface.act(Action(kind=ActionType.EXTRACT, target=target))
    assert result.success
    assert result.extracted_value == "Active"
    assert result.resolved_strategy == "role"


def test_target_fallback_chain_falls_back_to_css_when_role_wrong(page, mockbank_base_url):
    login(page, mockbank_base_url)
    page.get_by_role("textbox", name="Member ID").fill("10003")
    page.get_by_role("button", name="Search").click()
    page.wait_for_url("**/member/10003")

    surface = WebSurface(page, base_url=mockbank_base_url)
    target = Target(
        semantic_description="account status cell",
        locators=[
            Locator(strategy="role", value="cell[name='Nonexistent Label']"),  # deliberately wrong
            Locator(strategy="css", value="#account-status-value"),
        ],
    )
    result = surface.act(Action(kind=ActionType.EXTRACT, target=target))
    assert result.success
    assert result.extracted_value == "Active"
    assert result.resolved_strategy == "css"  # fell through past the broken role locator


def test_compute_target_from_ref_after_login(page, mockbank_base_url):
    page.goto(f"{mockbank_base_url}/login")
    surface = WebSurface(page, base_url=mockbank_base_url)
    state = surface.perceive()
    username_ref = next(el.ref for el in state.elements if el.role == "textbox" and el.name == "Username")

    target = surface.compute_target(username_ref)
    assert target.locators[0].strategy == "role"
    assert target.locators[0].value == "textbox[name='Username']"
    assert any(loc.strategy == "css" and loc.value == "#username" for loc in target.locators)


def test_dialog_scopes_perception_out_of_the_box(page, mockbank_base_url):
    login(page, mockbank_base_url)
    page.goto(f"{mockbank_base_url}/_debug/simulate?condition=terms_modal")
    page.goto(f"{mockbank_base_url}/search")

    surface = WebSurface(page, base_url=mockbank_base_url)
    state = surface.perceive()
    roles_names = {(el.role, el.name) for el in state.elements}
    assert ("dialog", "Terms Updated") in roles_names
    assert ("button", "Dismiss") in roles_names
    assert ("button", "Search") not in roles_names


def test_select_combobox_option(page, mockbank_base_url):
    login(page, mockbank_base_url)
    page.goto(f"{mockbank_base_url}/member/10002/open-subaccount")

    surface = WebSurface(page, base_url=mockbank_base_url)
    state = surface.perceive()
    combo_ref = next(el.ref for el in state.elements if el.role == "combobox")
    assert state.elements[[el.ref for el in state.elements].index(combo_ref)].options == ["Savings", "Checking"]

    result = surface.act(Action(kind=ActionType.SELECT, ref=combo_ref, params={"value": "checking"}))
    assert result.success
    state2 = surface.perceive()
    combo2 = next(el for el in state2.elements if el.role == "combobox")
    assert combo2.value == "Checking"


def test_action_by_ref_or_target_mutually_exclusive():
    import pytest
    with pytest.raises(ValueError):
        Action(kind=ActionType.CLICK, ref="e1", target=Target(semantic_description="x", locators=[Locator(strategy="css", value="#x")]))


def test_evidence_logger_records_action_and_redacts_password(tmp_path, page, mockbank_base_url):
    page.goto(f"{mockbank_base_url}/login")
    logger = EvidenceLogger(tmp_path)
    surface = WebSurface(page, base_url=mockbank_base_url, evidence_logger=logger)
    state = surface.perceive(actor="agent")
    password_ref = next(el.ref for el in state.elements if el.role == "textbox" and el.name == "Password")

    result = surface.act(Action(kind=ActionType.TYPE, ref=password_ref, params={"text": "bankdemo123"}, actor="agent"))
    assert result.success
    logger.close()

    raw = logger.path.read_text()
    assert "bankdemo123" not in raw
    lines = [json.loads(line) for line in raw.splitlines()]
    action_events = [line for line in lines if line["event_type"] == "action"]
    assert action_events[0]["data"]["params"]["text"] == "***REDACTED***"
    assert any(line["event_type"] == "perceive" for line in lines)
