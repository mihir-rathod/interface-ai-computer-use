# Computer-Use Automation System

A system that takes a natural-language goal, uses an LLM to accomplish it against a live UI
("computer use"), records the successful run as a typed reusable artifact, and replays that
artifact deterministically -- without the LLM in the loop -- with structured error handling and a
human escalation path.

Built against **MockBank**, a small local FastAPI app with a deliberately legacy-flavored UI
(nested tables, no test IDs, generic markup) standing in for a bank back-office system, per the
take-home brief.

> Status: MockBank (the target app), the artifact schema, the Surface abstraction (perceive/act
> over Playwright), and the deterministic replay engine are built and tested end to end --
> replay correctly handles the full success path, both business outcomes, all four recoverable
> conditions (including reauthenticate-and-resume), and hard failures. The discovery agent,
> safety module, and escalation handoff are not yet built. This README is filled in
> incrementally as each phase lands -- see `/REPORT.md` for the design write-up once complete.

## Setup

```bash
uv sync
uv run playwright install chromium
cp .env.example .env   # then fill in GEMINI_API_KEY (see below)
```

Get a free `GEMINI_API_KEY` at https://aistudio.google.com/apikey -- no billing required, free-tier
rate limits apply (see REPORT.md for why Gemini over Anthropic).

## What needs live services, and what doesn't

| Command | Needs `GEMINI_API_KEY` | Needs MockBank running |
|---|---|---|
| `pytest` | no | no |
| `uv run python cli.py replay ...` | no | yes |
| `uv run python cli.py discover ...` | yes | yes |

("no" for MockBank means you don't need to start it yourself -- the WebSurface tests spin up a
real MockBank instance in-process on an OS-assigned free port for the duration of the test
session, and drive it with a real headless Chromium via Playwright.)

Start MockBank in a separate terminal before `discover` or `replay`:

```bash
uv run uvicorn mockbank.app:app --port 8000
```

(Not port 5000 -- macOS's AirPlay Receiver squats on it by default.)

MockBank has one hardcoded operator login (no self-registration -- see "What's mocked, and why"
below): username `operator`, password `bankdemo123`. Both are dummy values checked into
`mockbank/data.py`; they are not secrets and grant access to nothing but this local mock app.

### Trying MockBank manually

Log in at http://localhost:8000/login, then search a member ID:

| Member ID | Result |
|---|---|
| `10001`, `10002`, `10003` | Active member -- Account Summary with savings/checking balances |
| `40004` | Permission-denied business outcome ("Access denied") |
| anything else | Not-found business outcome ("No member found") |

From an active member's page, "Open Sub-Account" walks through account type (Savings/Checking) +
initial deposit -> a validation error if the deposit is missing/non-positive -> a confirmation step
-> a success page with a confirmation number. The new sub-account then shows up on the member's
page under "Sub-Accounts" -- confirming the action actually persisted, not just displayed a message.

The four environmental/recoverable conditions (slow load, transient "service unavailable", an
unexpected terms-update modal, mid-flow session expiry) aren't reachable through the UI -- they're
armed one-shot, per-session, via a test-only route so the discovery agent never sees a "simulate a
failure" control sitting in the app it's operating:

```bash
curl "http://localhost:8000/_debug/simulate?condition=slow"   # or: unavailable | terms_modal | expire_session
```

Hit that (with the same session cookie/browser context you're about to use), then make the next
request -- that's the one the condition fires on.

## Demo path

_TODO (Phase 8): exact `discover` then `replay` commands once the CLI exists._

## Repo layout

```
/mockbank        MockBank target app (FastAPI + Jinja2)
/surface          Surface abstraction: perceive()/act(), the aria-snapshot element-list parser,
                   and the locator fallback-chain resolver. WebSurface (Playwright) is the only
                   implementation; both discovery and replay drive a surface through this same
                   interface (ASSIGNMENT_ORIGINAL.md 3.7's "seam").
/agent            LLM-driven discovery loop (decides what to do; acts through a Surface)
/artifacts_lib    Pydantic artifact schema, JSON storage, validation
/replay           Deterministic replay executor, error classifier (acts through a Surface)
/safety           Allowlist config, risk classifier
/escalation       Session manager, operator console (human handoff)
/evidence_lib     Structured JSONL logger, redaction -- wired into every Surface.act() call
/artifacts        Saved capability artifact JSON files
/evidence         Logs/artifacts from real discovery + replay runs (required deliverable)
/tests            pytest -- schema validation, surface/locator behavior, error classification
```

## What's mocked, and why

- **No self-registration / sign-up.** MockBank stands in for the class of system
  ASSIGNMENT_ORIGINAL.md Section 1 describes: "core banking screens, servicing tools, and admin
  consoles" -- internal back-office software used by bank employees, not a customer-facing product.
  Real systems like this provision accounts through IT/HR onboarding, not self-service sign-up, so a
  register flow would be unrealistic rather than a missing feature. One hardcoded operator login
  (`operator` / `bankdemo123`, both dummy values) stands in for that provisioning step. This also
  keeps the login flow a single reusable `mockbank.login` capability with real credential handling
  (Section 3.4: never persist real secrets) without building an unneeded user-management surface.
