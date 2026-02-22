# LittleHive

LittleHive is a local-first, multi-model, multi-agent assistant platform.

## Built-in Tools
- `status.get`
- `utility.echo`
- `task.create`
- `task.update`
- `memory.search`
- `memory.write`
- `memory.summarize`
- `memory.failure_fix`

## Install
```bash
pip install littlehive
```

## Quickstart
1. Start LittleHive:
```bash
lhive run
# or: lh-run
```
This will:
- run **quick onboarding** on first launch (if config is missing),
- load `.env`,
- start API, dashboard, and Telegram worker (when enabled and token is present),
- keep supervisor off by default to reduce console noise,
- print the local dashboard URL.

For full power-user onboarding prompts:
```bash
lhive run --advanced
# or: littlehive-run --advanced
```

To reset local setup and start fresh:
```bash
lhive reset
# or: lh-reset
```

2. Optional diagnostics:
```bash
littlehive-diag --validate-config --hardware --check-providers
```

Advanced/manual control CLIs are still available (see below).

## Dashboard
`littlehive-dashboard` is Python-only (NiceGUI), no Node/React install required.

Main views:
- Overview
- Providers (health + breaker + routing score)
- Tasks
- Users (optional profile context: name/timezone/city/country/notes)
- Memory search
- Permissions and power controls
- Usage/Budgets
- Diagnostics/Failures
- Pending confirmations

## Optional User Context
You can optionally store per-user context from the Dashboard `Users` tab (or admin API):
- display name
- preferred timezone
- city
- country
- notes

This context is injected into runtime metadata and can be used for personalized responses.

## Safety and Permission Profiles
Supported permission profiles:
- `read_only`: blocks all tool execution.
- `assist_only`: allows only low-risk tool actions.
- `execute_safe`: allows low-risk, requires confirmation for medium-risk, blocks high/critical.
- `execute_with_confirmation`: allows medium/high with confirmation, blocks critical in safe mode.
- `full_trusted`: allows all except critical when safe mode is enabled.

Risk levels (`low|medium|high|critical`) are enforced in tool execution. Medium/high actions can require confirmations depending on profile and safe mode.
Default profile is `execute_safe`.
Profile can be changed from the Dashboard Permissions tab or via Admin API (`PATCH /permissions/profile`).

## Diagnostics
```bash
littlehive-diag --provider-health
littlehive-diag --failures
littlehive-diag --runtime-stats
littlehive-diag --budget-stats
```

## CLI Entrypoints
- `lhive` (short command: `lhive run`, `lhive reset`, `lhive diag`)
- `lh-run` (short alias)
- `lh-reset` (short alias)
- `littlehive-run` (recommended for end users)
- `littlehive-onboard`
- `littlehive-api`
- `littlehive-telegram`
- `littlehive-diag`
- `littlehive-dashboard`
- `littlehive-supervisor`
- `littlehive-reset`

## Development
Install editable package with dev tooling:
```bash
pip install -e ".[dev]"
```

Run checks:
```bash
pytest -q
python -m build
twine check dist/*
```

## Limitations
- Dashboard auth is currently basic token gating; default host binding is localhost.
- Provider/tool telemetry is compact summaries by design (no full raw payload dump).

## Roadmap
Phase 6+: richer admin auth, stronger benchmarking, and broader channel/runtime controls.
