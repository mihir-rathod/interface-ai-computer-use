#!/usr/bin/env python
"""CLI entry point. See README.md's "Demo path" for the exact commands this implements.

    uv run python cli.py discover --capability mockbank.member_balance_lookup --param member_id=10001
    uv run python cli.py replay    --capability mockbank.member_balance_lookup --param member_id=10002

Both commands log in first (via the mockbank.login artifact, replayed like any other
capability -- login is a first-class reusable capability, not special-cased CLI logic) and
write structured evidence -- a JSONL log of every perceive/act, screenshots, and the final
artifact or result -- to /evidence/<run>/ by default.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from agent.catalog import get_spec
from agent.gemini_client import GeminiClient
from agent.loop import DiscoveryLoop
from agent.recorder import build_artifact
from artifacts_lib.storage import load_artifact_by_id, save_artifact
from evidence_lib.logger import EvidenceLogger
from replay.engine import ReplayEngine
from replay.result import ReplayStatus
from safety.allowlist import AllowlistConfig, AllowlistPolicy, DEFAULT_ALLOWLIST_PATH
from safety.policy import SafetyPolicy
from surface.web import WebSurface

REPO_ROOT = Path(__file__).resolve().parent
EVIDENCE_ROOT = REPO_ROOT / "evidence"


def parse_params(pairs: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--param must be key=value, got: {pair!r}")
        key, value = pair.split("=", 1)
        params[key] = value
    return params


def build_safety_policy(base_url: str) -> SafetyPolicy:
    config = AllowlistConfig.from_json(DEFAULT_ALLOWLIST_PATH)
    # allowed_route_patterns/action_types come from the checked-in policy; allowed_base_urls is
    # overridden to whatever --base-url actually is, so the policy always matches where this
    # run is really pointed rather than silently drifting from the JSON file's documented default.
    config = config.model_copy(update={"allowed_base_urls": [base_url]})
    return SafetyPolicy(AllowlistPolicy(config))


def run_login(surface: WebSurface, username: str, password: str) -> None:
    login_artifact = load_artifact_by_id("mockbank.login")
    result = ReplayEngine(surface).run(login_artifact, {"username": username, "password": password})
    if result.status != ReplayStatus.SUCCESS:
        raise SystemExit(f"login failed: status={result.status.value} error={result.error}")


def _run_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def cmd_discover(args: argparse.Namespace) -> int:
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY is not set -- see README.md Setup (needed for `discover`, not `replay`).")

    spec = get_spec(args.capability, args.base_url)
    params = parse_params(args.param)
    evidence_dir = Path(args.evidence_dir) if args.evidence_dir else EVIDENCE_ROOT / _run_id("discovery_run")
    logger = EvidenceLogger(evidence_dir)
    safety_policy = build_safety_policy(args.base_url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_page()
        page.goto(f"{args.base_url}/login")

        surface = WebSurface(page, base_url=args.base_url, screenshot_dir=evidence_dir / "screenshots", evidence_logger=logger, safety_policy=safety_policy)
        run_login(surface, args.username, args.password)

        loop = DiscoveryLoop(surface, GeminiClient(), evidence_logger=logger, max_steps=args.max_steps, timeout_seconds=args.timeout)
        result = loop.run(goal=spec.goal, parameters=params, start_path=spec.start_path)
        browser.close()

    print(f"discovery stop_reason={result.stop_reason} steps={len(result.transcript)}")
    if result.reasoning:
        print(f"reasoning: {result.reasoning}")
    if result.stop_reason != "finished":
        print(f"evidence: {evidence_dir}")
        return 1

    artifact = build_artifact(
        result, params,
        capability_id=spec.capability_id, version=spec.version, name=spec.name, description=spec.description,
        target=spec.target, preconditions=spec.preconditions,
        input_schema=spec.input_schema, output_schema=spec.output_schema,
        success_checkpoint=spec.success_checkpoint, error_handling=spec.error_handling,
        safety=spec.safety, success_output_defaults=spec.success_output_defaults,
        discovered_by=GeminiClient().model, discovery_run_id=evidence_dir.name,
    )
    saved_path = save_artifact(artifact)
    (evidence_dir / "artifact.json").write_text(artifact.model_dump_json(indent=2))
    print(f"saved artifact: {saved_path}")
    print(f"evidence: {evidence_dir}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    load_dotenv()
    artifact = load_artifact_by_id(args.capability)
    params = parse_params(args.param)
    evidence_dir = Path(args.evidence_dir) if args.evidence_dir else EVIDENCE_ROOT / _run_id("replay_run")
    logger = EvidenceLogger(evidence_dir)
    safety_policy = build_safety_policy(args.base_url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_page()
        page.goto(f"{args.base_url}/login")

        surface = WebSurface(page, base_url=args.base_url, screenshot_dir=evidence_dir / "screenshots", evidence_logger=logger, safety_policy=safety_policy)
        run_login(surface, args.username, args.password)

        engine = ReplayEngine(surface, evidence_logger=logger, reauth_credentials={"username": args.username, "password": args.password})
        result = engine.run(artifact, params)
        browser.close()

    print(f"status: {result.status.value}")
    if result.outputs is not None:
        print("outputs:", json.dumps(result.outputs, indent=2))
    if result.business_outcome:
        print(f"business_outcome: {result.business_outcome}")
    if result.error:
        print(f"error: {result.error.message}" + (f" (step {result.error.step_id})" if result.error.step_id else ""))

    (evidence_dir / "result.json").write_text(result.model_dump_json(indent=2))
    print(f"evidence: {evidence_dir}")
    return 1 if result.status == ReplayStatus.HARD_FAILURE else 0


def main() -> int:
    default_base_url = os.environ.get("MOCKBANK_BASE_URL", "http://localhost:8000")
    parser = argparse.ArgumentParser(prog="cli.py")
    sub = parser.add_subparsers(dest="command", required=True)

    discover_p = sub.add_parser("discover", help="Run LLM-driven discovery and save the resulting artifact")
    discover_p.add_argument("--capability", required=True, help="capability_id from agent/catalog.py, e.g. mockbank.member_balance_lookup")
    discover_p.add_argument("--param", action="append", default=[], help="key=value, repeatable")
    discover_p.add_argument("--base-url", default=default_base_url)
    discover_p.add_argument("--username", default="operator")
    discover_p.add_argument("--password", default="bankdemo123")
    discover_p.add_argument("--headed", action="store_true", help="show the browser window instead of running headless")
    discover_p.add_argument("--evidence-dir", default=None)
    discover_p.add_argument("--max-steps", type=int, default=25)
    discover_p.add_argument("--timeout", type=int, default=300)
    discover_p.set_defaults(func=cmd_discover)

    replay_p = sub.add_parser("replay", help="Deterministically replay a saved artifact -- no LLM")
    replay_p.add_argument("--capability", required=True, help="capability_id of a saved artifact under /artifacts/")
    replay_p.add_argument("--param", action="append", default=[], help="key=value, repeatable")
    replay_p.add_argument("--base-url", default=default_base_url)
    replay_p.add_argument("--username", default="operator")
    replay_p.add_argument("--password", default="bankdemo123")
    replay_p.add_argument("--headed", action="store_true")
    replay_p.add_argument("--evidence-dir", default=None)
    replay_p.set_defaults(func=cmd_replay)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
