# Launch Readiness Tracker for AI Model Releases — v1 Plan

## Goal
A small web app that a technical program manager would use to decide whether an AI model release is ready to launch. Readiness is decided per **launch configuration** (model version + product surfaces + enabled capabilities + rollout stage), not per product.

All model names, teams and people in the app are **fictional sample data** (e.g. "Model Atlas v2.1"). No real company names or branding.

## Tech
- Python 3 + Flask, SQLite, server-rendered HTML (Jinja templates), minimal CSS
- pytest for tests
- One optional AI feature (status summary), behind a setting so the app works without an API key

## Core concepts
- **Launch**: name, model version, target date, rollout stage (internal → trusted testers → limited GA → GA)
- **Configuration**: product surfaces (API, consumer app, enterprise) and capabilities, each on/off (tool use, code execution, web browsing, file uploads, memory)
- **Gate**: a readiness check with owner, team, status (not started / in progress / passed / failed / waived), due date, notes
- **Gate rules**: which gates a configuration requires. Always-required gates (safety evals vs thresholds, frontier safety evals (dangerous capabilities), red-team sign-off, rollback plan, monitoring & on-call, comms) plus conditional ones (e.g. code execution on → sandbox security review; web browsing on → browsing safety review; enterprise surface → data governance & privacy review; GA stage → capacity sign-off)
- **Decision**: go / no-go / scope change, who decided, date, rationale

## v1 features (build in this order)
1. **Data model + gate rules engine** — given a configuration, return the required gates. Rules live in one readable file (e.g. `gate_rules.py` or YAML) so a non-engineer could edit them.
2. **Create a launch** — form for version, surfaces, capabilities, stage; generates its gates. New gates are due a set number of days before the target date (`GATE_DUE_DAYS_BEFORE_LAUNCH` in `settings.py`, default 7), so they finish before the go/no-go review.
3. **Launch dashboard** — header with target date and days until launch; a **Needs attention** list (failed, overdue or unassigned gates) above the team groups; gates grouped by team, status colors, overdue flags, owner names. Includes **gate editing** (status, owner, due date, notes) — a gate can only be set to "waived" with a written waiver rationale and who waived it (both enforced in the form and the database, shown on the dashboard, and cleared if the status changes away from waived). Also adds the **seed data** below (`flask --app launch_readiness.app seed`).
4. **Go/no-go view** — overall readiness shown as **"Ready"** or **"Not ready: N blockers"** ("Go" and "No-go" are reserved for the human decision in feature 6), list of blockers, and the option to **launch with a capability disabled**: turning it off removes its gates and logs a scope change with a follow-up. The dashboard shows the readiness badge and a **Removed by scope change** section (last status, removed date, follow-up); removed gates don't count toward readiness. Also flags gates as **at risk** when they're due within 3 days and not yet started (the 3 days is a named setting in `settings.py`); the seed data includes one at-risk gate.
5. **Delta review** — turning a capability on for an existing launch shows only the *new* gates it requires, and is recorded as a scope-change decision. Gates removed by an earlier scope change are restored, not duplicated: reset to not started (owner and notes kept), with a line added to the notes recording the restore date, the capability turned back on, and the previous status (and waiver, if any).
5b. **Stage promotion** — moving a launch to a later stage shows only the new gates (e.g. trusted testers → limited GA adds capacity sign-off and legal review), recorded as a scope-change decision.
6. **Decision log** — every go/no-go and scope change recorded with rationale, who decided, the date and a snapshot of readiness at that moment. A follow-up is required for No-go, and for Go while the launch is Not ready (which also needs an explicit acknowledgement and is marked "Go with open blockers"); it's optional only for Go when Ready. Decisions can't be changed or deleted (enforced by the database); corrections are new decisions. Per-launch log, all-launches log with filters, and a "changed since the latest decision" notice.
7. **AI status summary** — drafts a one-page leadership update from the launch data (status, blockers, decisions, next steps) using the Claude API (`claude-opus-5-5`, effort `medium`; both in `settings.py`). Works only when `ANTHROPIC_API_KEY` is set; otherwise the page says it isn't configured and the rest of the app works as normal. Clearly labeled as a draft for a person to review; the AI never changes gate status or makes the go/no-go call (read-only data, no tools, output only displayed). If the model declines, the page says so and stops (no retry on another model). Drafts aren't saved in v1. **Not yet tested against the real Claude API:** no API key was set up as of 2026-10-21, so the real-API path (including the `anthropic==1.17.0` request shape) has only been tested with a fake client. Before relying on it, set `ANTHROPIC_API_KEY` and run `RUN_LIVE_AI_TESTS=1 .venv/bin/pytest tests/test_ai_live.py`, then generate one draft in the app.

## Seed data (added in feature 3)
Two sample launches, e.g.:
- "Model Atlas v2.1 — API + consumer app, tool use on, code execution off, trusted testers" (mostly ready, one blocker)
- "Model Atlas v2.2 — adds code execution" (shows the delta review)

## Tests that must pass
- Rules engine: each capability/surface/stage produces exactly the expected gates
- Disabling a capability removes only its gates and logs a decision
- Enabling a capability adds only the new gates (delta)
- Re-enabling a capability restores its removed gates (same rows) as not started, with a restore note
- Readiness is "Not ready" while any required gate is failed or not passed (waived counts as passed only with a rationale and approver)
- New gates are due `GATE_DUE_DAYS_BEFORE_LAUNCH` days before the target date
- A gate can't be saved as "waived" without a waiver rationale and who waived it
- A gate is "at risk" when it's not started and due within 3 days; the seed data has one
- No-go, and Go while Not ready, can't be recorded without a follow-up; Go while Not ready also needs the acknowledgement
- Decisions can't be changed or deleted
- The AI summary works without an API key (shows "not configured"), never writes to the database, and never retries a declined request

## Working process (same as the French tutor)
- Work on a branch per feature; plan first, review the plan, then build
- Run tests before every merge
- Short README: what it is, why configuration-based readiness, screenshots, how to run

## Out of scope for v1
Logins/permissions, multiple users editing at once, integrations (Jira, Slack), deployment to the web.
