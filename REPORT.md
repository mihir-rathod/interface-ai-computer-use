# Design Report: Computer-Use Automation System

## 1. Architecture

Two modes share one perception/action layer. **Discovery** (`agent/`) runs an LLM (Gemini
2.5 Flash-Lite) in an observe-decide-act loop against a live browser, choosing from a fixed tool
set (navigate/click/type/select/extract/finish/give_up) based on a structured element list, not
screenshots. **Replay** (`replay/`) re-executes a saved artifact deterministically -- zero LLM
calls anywhere in that module. Both drive a `Surface` (`surface/base.py`, four methods:
`perceive`/`act`/`check_signal`/`compute_target`), so nothing above that interface --
`artifacts_lib/`, `replay/`, `safety/`, `agent/`, `escalation/` -- knows Playwright exists.
`WebSurface` (`surface/web.py`) is the only implementation; the only other files that import
Playwright are its own locator-resolution helper (`surface/locator_resolver.py`) and `cli.py`
(which only launches the browser process).

**Gemini, not Anthropic**: the only hard requirement is a real LLM-driven run; provider isn't
prescribed. Gemini's free tier needs no billing, independent of any paid subscription. The
model id (`gemini-flash-lite-latest`, an alias) was chosen after two real failures during
development: a dated model got deprecated for new API keys, and the plain `-latest` alias
resolved to a preview model with a 20-request/day quota that got exhausted mid-build. The lite
tier has a much higher quota and is still an alias, so it won't hard-break the same way again.

**Playwright, not Selenium/Puppeteer/screenshot-based control**: it's the only option with a
first-class accessibility-tree API (`aria_snapshot(mode="ai")`, which hands out stable element
refs built for exactly this agent-loop pattern). Selenium has wider raw browser coverage but no
comparable accessibility tooling and needs much more hand-written waiting, working against
determinism. Screenshot/coordinate control is explicitly weaker here: a pixel breaks on any
resize and gives an artifact's locator field nothing durable to store. This choice matters less
than it might, though -- see heading 4.

**Single process, no queues**: MockBank, discovery, replay, and the operator console all run in
one process. Replay is already stateless and deterministic per run, so throughput scaling later
is "run N workers," not an architecture change -- consistent with the brief not rewarding
scaling infrastructure.

**`cli.py`, not a UI**: the brief frames this as infrastructure another product calls, not
something a person operates through a dashboard. The one exception is the escalation console
(heading 5), a fallback for when automation can't proceed alone.

## 2. Artifact schema

Two mechanisms are each used once, for three different purposes, rather than inventing a shape
per use site. **`Target`**: an ordered locator fallback chain (role+name, then CSS, then XPath,
then a text anchor, each with a `note` field for robustness reasoning), used identically for
*acting* and *checking*. An ambiguous match (more than one element) is treated as no match, not
guessed at. **`Signal`**: "is this condition true right now," used for a step's own checkpoint,
the artifact's `success_checkpoint`, and both `business_outcomes`/`recoverable` rules. A replay
can complete every step and still miss the goal (an unexpected redirect), so those are separate
fields.

`input_schema`/`output_schema` are JSON-Schema-shaped, the same shape LLM tool-calling APIs use
for parameters -- directly reusable if capabilities are ever exposed as callable tools.

Validators enforce real invariants: unique step ids; an `extract` step's `output_binding` must
name a field actually in `output_schema`; action-specific required params; a `Signal` needs a
`target` exactly when it's element-based. Two fields were added once replay was actually
implemented, not designed up front: `BusinessOutcomeRule.output_field` (which output property
receives an outcome, instead of hardcoding "status") and `RecoverableRule.recovery_target` (what
to click for `dismiss_and_continue`) -- both backward-compatible.

`artifact_schema_version` (the format) is separate from `version` (this flow's own recording),
so replay can tell schema drift from a re-recorded flow.

## 3. Determinism & error handling

No blind `sleep()`: waits are Playwright's own auto-waiting or an explicit checkpoint re-check.
Classification (business outcome, then recoverable, then hard failure) is checked proactively
after every action, not only on checkpoint failure -- found via a real bug: a `url_matches`
checkpoint can pass on a broken page that loaded at the right URL with the wrong content
(a simulated "service unavailable" banner), so a weaker checkpoint alone wouldn't catch it.

All six named runtime conditions are demonstrated through a real replay: not-found and
permission-denied (business outcomes), a validation error (business outcome -- required a second
capability, since the read-only lookup has no form to validate), an unexpected modal
(dismiss-and-continue), session expiry (`reauthenticate_and_resume`), and a slow load (tolerated
via Playwright's own wait). Reauthentication replays whatever capability is named in
`preconditions.requires_capability` and restarts from step one -- but only if no non-idempotent
step has already completed; otherwise it's a hard failure, never a silent retry that could
double-submit a real transaction. That's the concrete use of the `idempotent` field.

Two more bugs surfaced only by actually replaying artifacts: `url_matches`/`redirected_to`
originally matched the full URL including query string, so a redirect to `/login?next=/search`
spuriously satisfied a `**/search` checkpoint while failing to match `**/login` -- backwards
both ways at once. Fixed to match the path only. Separately, `get_by_role(name=...)` does
substring matching by default, which caused false ambiguity in MockBank's nested tables (an
unlabeled `<td>` inherits a huge concatenated name from its descendants); fixed with
`exact=True`.

**UI drift**: the locator fallback chain (heading 2) is also the drift-tolerance mechanism --
replay logs which strategy actually resolved (`resolved_strategy`) for every action, in order.
A capability that starts silently falling back to its CSS or text-anchor tier instead of its
primary role+name locator is visible in evidence as a drift signal before it fully breaks, not
only after replay starts failing outright.

## 4. Heterogeneity & multi-tenant

Not built, per the brief -- but the seam is real. `Surface` is a 4-method abstract class;
`WebSurface` is the only implementation. Nothing in `artifacts_lib/`, `replay/`, `safety/`,
`agent/`, or `escalation/` has ever seen a browser-specific concept or imported Playwright.

A `DesktopSurface` is a credible next step: Windows UI Automation and macOS's Accessibility API
both expose the same role/name/value shape Playwright's accessibility tree does, via
`pywinauto`/`atomacos`. A `LegacyWebSurface` needs even less -- Playwright already traverses
iframes/framesets; it would mostly lean harder on the CSS/text-anchor tiers of the existing
locator chain. Neither touches the schema, replay engine, or safety policy.

Multi-tenant reuse has one schema seam today: `CapabilityTarget.tenant_id` is nullable. The
design: a base capability with parameterized locators/routes, plus a thin per-tenant override
layer (base URL, locator overrides, branding text) merged at replay time, instead of
re-recording per tenant. Drift detection follows from evidence already being collected: track
replay success per (capability, tenant); a tenant whose *one specific step* starts failing flags
that step for override, not a full re-discovery.

## 5. Escalation & handoff

The threading model is the load-bearing decision. Automation runs on the thread that owns the
live Playwright page. The operator console runs in a separate background thread and never
touches that page directly -- Playwright's sync API isn't thread-safe. The console only calls
`request_action()`, enqueuing an intent; the actual `Surface.act()` call happens inside
`pause()`'s own wait loop, on the thread that owns the page. `mode`
(`AUTOMATION`/`PAUSED`/`HUMAN_ACTIVE`) is always inspectable.

"Stuck" differs by mode but feeds the same mechanism: discovery escalates on give-up/dead-end/
out-of-steps/timeout; replay escalates on any failure with no known signal, including a safety
block on an unconfirmed irreversible action. Either way, an `intervention_request` (reason,
capability/goal, step, live screenshot, full element list) is written before the thread blocks.

On resume, the code doesn't blindly redo the original action -- it re-classifies first, then
checks whether the step's checkpoint is already satisfied. Found via a real bug: a broken
locator's retry would keep using that same broken locator and never succeed, even after a human
had already fixed the field through a separate, valid locator (the checkpoint's own, declared
independently).

The console itself (`escalation/operator_console.py`) is deliberately bare, per the brief's
scope note. What's real underneath: it acts on the exact live session, verified end to end
(`tests/test_escalation_live.py`, and via the real CLI --
`/evidence/replay_run_20260815T005612Z/` is a saved run where `open_subaccount` blocked at its
irreversible step, a human approved the exact action, and it resumed to a real completion).

## 6. Safety

Enforced entirely inside `Surface.act()`, not the replay engine alone, so discovery and replay
share one enforcement point. **Allowlist** (`safety/allowlist.py`): permitted base URLs, route
patterns (path-only, same reasoning as heading 3), action types. A violation is blocked and
always logged, never silently skipped. **Risk classification** (`safety/risk.py`): binary
safe/irreversible, re-classified live rather than trusted from the artifact -- defense against a
stale or hand-edited one. The keyword list excludes "submit": a fixture's login button was
described as "login submit button" (the author's prose, not its real name, "Log In"), false-
positiving it as irreversible and blocking login entirely. Fixed by dropping the keyword and
correcting fixtures to describe elements by real accessible name. **Conservative gating**
(`safety/policy.py`): irreversible actions block by default; only proceed with an explicit
`confirmed=True`, which `Surface` never grants itself -- only a human, via escalation.

**Redaction**: typed text is masked when the target looks like a password field, verified in
real evidence logs. Deliberately narrow, not a general PII scanner -- MockBank's data has no
real PII to scan for; a broader pipeline would be untested and speculative.

**Limits**: allowlist and risk classifier are process-local config -- fine for one process, but
a real multi-tenant deployment needs these centrally managed. Risk classification is
keyword-based; simple, worked for every case tested, but not a substitute for human review
before an artifact's `requires_confirmation` is ever set to `false`.

## 7. Cuts

- **Full co-browsing console.** Explicitly out of scope. Built the minimal-but-real version
  instead: pause, live handoff, capture, resume. Next: make each row in the element table
  clickable to auto-fill the manual-action form, cutting the tedium of typing a ref by hand
  without crossing into real co-browsing -- still routed through the same `act()` call, still
  fully logged and safety-checked.
- **Auto-resuming discovery after escalation.** A human-fixed stuck run reports its original
  stop reason with `escalated: true` rather than automatically resuming the LLM loop with a
  fresh budget. Simpler and bounded. Next: let a resumed run continue the same conversation
  history with a capped number of budget extensions, instead of ending the attempt.
- **Desktop and legacy-web surfaces, multi-tenant reuse.** Designed (heading 4), not built.
  Next: a real `DesktopSurface` against one native Windows or macOS app would be the strongest
  validation that the `Surface` seam actually holds outside a browser, not just in theory.
- **Other stretch goals** (LLM-assisted single-step replay recovery, confidence/flakiness
  scoring, code generation from an artifact). None attempted, in favor of a thin-but-real
  implementation of every core requirement with evidence behind it, over optional breadth on a
  thinner core. Assisted recovery specifically was skipped because wiring `agent/` into
  `replay/` would blur the "no LLM in replay" guarantee the rest of this report leans on. Of the
  three, confidence/flakiness scoring would be the cheapest next add -- replay a capability N
  times and report a pass rate, no new mechanism, just running what already exists repeatedly.
- **General PII redaction, queues/worker pools/multi-tenant plumbing.** Narrowed/not built per
  the brief; the architecture doesn't need to change shape to add either later (heading 1). Next
  for redaction specifically: a policy-driven ruleset once real regulated-data shapes are known,
  rather than guessing at patterns against MockBank's synthetic data now.
