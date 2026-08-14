# Computer-Use Automation System

A system that takes a natural-language goal, uses an LLM to accomplish it against a live UI
("computer use"), records the successful run as a typed reusable artifact, and replays that
artifact deterministically -- without the LLM in the loop -- with structured error handling and a
human escalation path.

Built against **MockBank**, a small local FastAPI app with a deliberately legacy-flavored UI
(nested tables, no test IDs, generic markup) standing in for a bank back-office system, per the
take-home brief.

> Status: scaffolding in progress. This README is filled in incrementally as each phase lands --
> see `/REPORT.md` for the design write-up once complete.

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

Start MockBank in a separate terminal before `discover` or `replay`:

```bash
uv run uvicorn mockbank.app:app --port 8000
```

(Not port 5000 -- macOS's AirPlay Receiver squats on it by default.)

MockBank has one hardcoded operator login (no self-registration -- see "What's mocked, and why"
below): username `operator`, password `bankdemo123`. Both are dummy values checked into
`mockbank/data.py`; they are not secrets and grant access to nothing but this local mock app.

## Demo path

_TODO (Phase 8): exact `discover` then `replay` commands once the CLI exists._

## Repo layout

```
/mockbank        MockBank target app (FastAPI + Jinja2)
/agent            LLM-driven discovery loop (perceive -> decide -> act)
/artifacts_lib    Pydantic artifact schema, JSON storage, validation
/replay           Deterministic replay executor, locator resolver, error classifier
/safety           Allowlist config, risk classifier
/escalation       Session manager, operator console (human handoff)
/evidence_lib     Structured JSONL logger, screenshot capture
/artifacts        Saved capability artifact JSON files
/evidence         Logs/artifacts from real discovery + replay runs (required deliverable)
/tests            pytest -- schema validation, locator resolution, error classification
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
