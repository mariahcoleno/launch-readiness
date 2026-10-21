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
- **Gate rules**: which gates a configuration requires. Always-required gates (safety evals vs thresholds, red-team sign-off, rollback plan, monitoring & on-call, comms) plus conditional ones (e.g. code execution on → sandbox security review; web browsing on → browsing safety review; enterprise surface → data governance & privacy review; GA stage → capacity sign-off)
- **Decision**: go / no-go / scope change, who decided, date, rationale

## v1 features (build in this order)
1. **Data model + gate rules engine** — given a configuration, return the required gates. Rules live in one readable file (e.g. `gate_rules.py` or YAML) so a non-engineer could edit them.
2. **Create a launch** — form for version, surfaces, capabilities, stage; generates its gates. New gates are due a set number of days before the target date (`GATE_DUE_DAYS_BEFORE_LAUNCH` in `settings.py`, default 7), so they finish before the go/no-go review.
3. **Launch dashboard** — gates grouped by team, status colors, overdue flags, owner names. Includes **gate editing** (status, owner, due date, notes) — a gate can only be set to "waived" with a written waiver rationale. Also adds the **seed data** below.
4. **Go/no-go view** — overall readiness, list of blockers, and the option to **launch with a capability disabled**: turning it off removes its gates and logs a follow-up.
5. **Delta review** — turning a capability on for an existing launch shows only the *new* gates it requires.
6. **Decision log** — every go/no-go and scope change recorded with rationale.
7. **AI status summary** — drafts a one-page leadership update from the launch data (status, blockers, decisions, next steps). Clearly labeled as a draft for a person to review; the AI never changes gate status or makes the go/no-go call.

## Seed data (added in feature 3)
Two sample launches, e.g.:
- "Model Atlas v2.1 — API + consumer app, tool use on, code execution off, trusted testers" (mostly ready, one blocker)
- "Model Atlas v2.2 — adds code execution" (shows the delta review)

## Tests that must pass
- Rules engine: each capability/surface/stage produces exactly the expected gates
- Disabling a capability removes only its gates and logs a decision
- Enabling a capability adds only the new gates (delta)
- Go/no-go is "no-go" while any required gate is failed or not passed (waived counts as passed only with a rationale)
- New gates are due `GATE_DUE_DAYS_BEFORE_LAUNCH` days before the target date
- A gate can't be saved as "waived" without a waiver rationale

## Working process (same as the French tutor)
- Work on a branch per feature; plan first, review the plan, then build
- Run tests before every merge
- Short README: what it is, why configuration-based readiness, screenshots, how to run

## Out of scope for v1
Logins/permissions, multiple users editing at once, integrations (Jira, Slack), deployment to the web.
