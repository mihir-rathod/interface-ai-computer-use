"""Integration tests proving the safety enforcement point actually blocks live actions --
not just that the policy object returns the right decision in isolation (tests/test_safety.py
already covers that), but that WebSurface.act() actually refuses to perform them.
"""
from __future__ import annotations

from artifacts_lib.schema import ActionType, Locator, Target
from safety.allowlist import AllowlistConfig, AllowlistPolicy
from safety.policy import SafetyPolicy
from surface.base import Action
from surface.web import WebSurface
from tests.conftest import login


def _policy(base_url: str, **overrides) -> SafetyPolicy:
    config = AllowlistConfig(
        allowed_base_urls=[base_url],
        allowed_route_patterns=["/login", "/search", "/member/*"],
        allowed_action_types=["navigate", "click", "type", "select", "extract", "wait_for", "dismiss_dialog"],
    )
    return SafetyPolicy(AllowlistPolicy(config), **overrides)


def test_normal_flow_still_works_with_a_permissive_matching_allowlist(page, mockbank_base_url):
    login(page, mockbank_base_url)
    surface = WebSurface(page, base_url=mockbank_base_url, safety_policy=_policy(mockbank_base_url))
    state = surface.perceive()
    member_id_ref = next(el.ref for el in state.elements if el.role == "textbox" and el.name == "Member ID")
    search_ref = next(el.ref for el in state.elements if el.role == "button" and el.name == "Search")

    assert surface.act(Action(kind=ActionType.TYPE, ref=member_id_ref, params={"text": "10001"})).success
    assert surface.act(Action(kind=ActionType.CLICK, ref=search_ref)).success
    assert "/member/10001" in page.url


def test_navigate_outside_allowed_base_url_is_blocked(page, mockbank_base_url):
    login(page, mockbank_base_url)
    surface = WebSurface(page, base_url=mockbank_base_url, safety_policy=_policy(mockbank_base_url))

    result = surface.act(Action(kind=ActionType.NAVIGATE, params={"url": "http://example.com/"}))

    assert not result.success
    assert "allowlist" in result.error
    assert "example.com" not in page.url  # the browser must never have actually navigated there


def test_navigate_to_disallowed_route_is_blocked(page, mockbank_base_url):
    login(page, mockbank_base_url)
    surface = WebSurface(page, base_url=mockbank_base_url, safety_policy=_policy(mockbank_base_url))

    result = surface.act(Action(kind=ActionType.NAVIGATE, params={"url": "/admin"}))

    assert not result.success
    assert "allowlist" in result.error


def test_unconfirmed_irreversible_click_is_blocked(page, mockbank_base_url):
    login(page, mockbank_base_url)
    page.get_by_role("textbox", name="Member ID").fill("10002")
    page.get_by_role("button", name="Search").click()
    page.wait_for_url("**/member/10002")
    page.goto(f"{mockbank_base_url}/member/10002/open-subaccount")
    page.get_by_role("combobox", name="Account Type").select_option(value="savings")
    page.get_by_role("textbox", name="Initial Deposit Amount").fill("500")
    page.get_by_role("button", name="Continue").click()
    page.wait_for_url("**/open-subaccount/confirm")

    surface = WebSurface(page, base_url=mockbank_base_url, safety_policy=_policy(mockbank_base_url))
    target = Target(
        semantic_description="Confirm & Open Account button",
        locators=[Locator(strategy="role", value="button[name='Confirm & Open Account']")],
    )

    result = surface.act(Action(kind=ActionType.CLICK, target=target))  # confirmed defaults to False

    assert not result.success
    assert "confirmation" in result.error
    # the browser must genuinely not have clicked it -- still on the confirm page, no sub-account created
    assert "open-subaccount/confirm" in page.url


def test_confirmed_irreversible_click_is_allowed(page, mockbank_base_url):
    login(page, mockbank_base_url)
    page.get_by_role("textbox", name="Member ID").fill("10003")
    page.get_by_role("button", name="Search").click()
    page.wait_for_url("**/member/10003")
    page.goto(f"{mockbank_base_url}/member/10003/open-subaccount")
    page.get_by_role("combobox", name="Account Type").select_option(value="checking")
    page.get_by_role("textbox", name="Initial Deposit Amount").fill("250")
    page.get_by_role("button", name="Continue").click()
    page.wait_for_url("**/open-subaccount/confirm")

    surface = WebSurface(page, base_url=mockbank_base_url, safety_policy=_policy(mockbank_base_url))
    target = Target(
        semantic_description="Confirm & Open Account button",
        locators=[Locator(strategy="role", value="button[name='Confirm & Open Account']")],
    )

    result = surface.act(Action(kind=ActionType.CLICK, target=target, confirmed=True))

    assert result.success
    assert "Account Opened" in page.content()
