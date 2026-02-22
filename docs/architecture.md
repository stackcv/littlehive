# Architecture

LittleHive enforces anti-bloat boundaries:

- Provider calls only through `src/littlehive/core/providers/router.py`.
- Tool execution only through `src/littlehive/core/tools/executor.py`.
- Context compilation/token preflight for internal model calls.
- No global tool schema injection; use ITR staged docs.
- Agent handoffs via Transfer object with compact payloads.
- Structured logs/traces and compact persisted summaries.

## Operator Plane (Phase 4+5)

- Admin service layer: `src/littlehive/core/admin/service.py`
- Admin API: `src/littlehive/apps/api_server.py`
- Dashboard UI (Python-only NiceGUI): `src/littlehive/apps/dashboard.py`
- Permission policy engine: `src/littlehive/core/permissions/policy_engine.py`
- Pending confirmations and profile audit persisted in DB.

## Runtime Safety

- Safe mode and permission profile jointly gate risky tool actions.
- Medium/high/critical tool calls can be blocked or require confirmations.
- Retry/fallback/circuit breaker logic remains centralized in runtime modules.
