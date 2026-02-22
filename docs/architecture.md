# Architecture

Phase 0 enforces boundaries:
- Provider calls only through `littlehive.core.providers.router`.
- Tool execution only through `littlehive.core.tools.executor`.
- Context compilation and token preflight before future model calls.
- Structured logging/tracing for pipeline observability.
