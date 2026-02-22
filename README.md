# LittleHive

LittleHive is a local-first, multi-model, multi-agent assistant platform optimized for small local models, strict context budgets, and low operating cost.

## Core Concepts
- ITR (Instruction-Tool Retrieval): only inject compact tool docs until invocation time.
- Memory Cards: typed compact reusable memory units, not full transcript replay.
- Transfer Primitive: clean-state handoffs between agents.
- Context Compiler: central token-budget preflight + deterministic trimming.

## Install
```bash
pip install littlehive
pip install "littlehive[telegram]"
pip install "littlehive[ui]"
pip install "littlehive[full]"
```

For development:
```bash
pip install -e ".[dev,telegram,ui]"
```

## Quickstart
1. Start LittleHive:
```bash
littlehive-run
```
This will:
- run onboarding on first launch (if config is missing),
- load `.env`,
- start API, dashboard, supervisor, and Telegram worker (when enabled and token is present),
- print the local dashboard URL.

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
- Tasks/Traces
- Memory search
- Permissions and power controls
- Usage/Budgets
- Diagnostics/Failures
- Pending confirmations

## Safety and Permission Profiles
Supported permission profiles:
- `read_only`
- `assist_only`
- `execute_safe`
- `execute_with_confirmation`
- `full_trusted`

Risk levels (`low|medium|high|critical`) are enforced in tool execution. Medium/high actions can require confirmations depending on profile and safe mode.

## Diagnostics
```bash
littlehive-diag --provider-health
littlehive-diag --failures
littlehive-diag --runtime-stats
littlehive-diag --budget-stats
```

## CLI Entrypoints
- `littlehive-run` (recommended for end users)
- `littlehive-onboard`
- `littlehive-api`
- `littlehive-telegram`
- `littlehive-diag`
- `littlehive-dashboard`
- `littlehive-supervisor`

## Development
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
