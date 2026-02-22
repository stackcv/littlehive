from __future__ import annotations

from littlehive.channels.telegram.adapter import build_telegram_runtime
from littlehive.cli import base_parser
from littlehive.core.config.hardware_audit import collect_hardware_audit, render_hardware_summary
from littlehive.core.config.loader import load_app_config
from littlehive.core.config.recommender import recommend_models
from littlehive.core.providers.health import check_configured_providers
from littlehive.core.telemetry.diagnostics import budget_stats, failure_summary, runtime_stats


def main() -> int:
    parser = base_parser("littlehive-diag", "LittleHive diagnostics CLI")
    parser.add_argument("--config", default=None, help="Config file path")
    parser.add_argument("--validate-config", action="store_true")
    parser.add_argument("--hardware", action="store_true")
    parser.add_argument("--check-providers", action="store_true")
    parser.add_argument("--recommend-models", action="store_true")
    parser.add_argument("--skip-provider-tests", action="store_true")

    parser.add_argument("--provider-health", action="store_true")
    parser.add_argument("--failures", action="store_true")
    parser.add_argument("--runtime-stats", action="store_true")
    parser.add_argument("--budget-stats", action="store_true")
    parser.add_argument("--supervisor-status", action="store_true")
    args = parser.parse_args()

    did_work = False
    cfg = None

    needs_cfg = any(
        [
            args.validate_config,
            args.check_providers,
            args.recommend_models,
            args.provider_health,
            args.failures,
            args.runtime_stats,
            args.budget_stats,
        ]
    )

    if needs_cfg:
        try:
            cfg = load_app_config(instance_path=args.config)
            if args.validate_config:
                did_work = True
                print(f"config-valid instance={cfg.instance.name} env={cfg.environment} safe_mode={cfg.runtime.safe_mode}")
        except Exception as exc:  # noqa: BLE001
            print(f"config-invalid error={exc}")
            return 1

    audit = None
    if args.hardware or args.recommend_models:
        did_work = True
        audit = collect_hardware_audit()
        if args.hardware:
            print("hardware-summary:")
            print(render_hardware_summary(audit))
            if audit.warnings:
                print(f"hardware-warnings={audit.warnings}")

    provider_results = None
    if args.check_providers or args.recommend_models:
        did_work = True
        provider_results = check_configured_providers(cfg, skip_tests=args.skip_provider_tests)
        if args.check_providers:
            print("provider-checks:")
            for item in provider_results.values():
                print(
                    f"- {item.provider}: enabled={item.enabled} ok={item.ok} "
                    f"latency_ms={item.latency_ms} error={item.error}"
                )

    if args.recommend_models:
        assert audit is not None
        assert provider_results is not None
        rec = recommend_models(
            hardware=audit,
            provider_results=provider_results,
            configured_local_models=cfg.providers.local_compatible.models,
            configured_groq_models=cfg.providers.groq.models,
        )
        print("recommendation:")
        print(f"- confidence={rec.confidence}")
        print(f"- mapping={rec.mapping}")
        if rec.warnings:
            print(f"- warnings={rec.warnings}")
        if rec.notes:
            print(f"- notes={rec.notes}")

    runtime = None
    if args.provider_health or args.failures or args.runtime_stats or args.budget_stats:
        did_work = True
        runtime = build_telegram_runtime(config_path=args.config)

    if args.provider_health and runtime is not None:
        print("provider-health:")
        details = runtime.pipeline.provider_router.provider_status()
        scores = runtime.pipeline.provider_router.provider_scores()
        for name in sorted(details):
            d = details[name]
            print(
                f"- {name}: health={d['health']} score={scores.get(name)} "
                f"breaker={d['breaker']['state']} failures={d['stats'].get('failure', 0)} "
                f"latency_ms={d['stats'].get('latency_ms', 0.0)}"
            )

    if args.failures and runtime is not None:
        print("failure-summary:")
        rows = failure_summary(runtime.db_session_factory, limit=10)
        if not rows:
            print("- none")
        for row in rows:
            print(
                f"- {row['category']}:{row['component']} type={row['error_type']} "
                f"count={row['count']} recovered={row['recovered']} last_strategy={row['last_strategy']}"
            )

    if args.runtime_stats and runtime is not None:
        print("runtime-stats:")
        st = runtime_stats(runtime.db_session_factory)
        print(f"- tasks_by_status={st['tasks_by_status']}")
        print(f"- trace_summaries={st['trace_summaries']}")
        print(f"- safe_mode={cfg.runtime.safe_mode}")

    if args.budget_stats and runtime is not None:
        print("budget-stats:")
        b = budget_stats(runtime.db_session_factory)
        print(f"- avg_estimated_prompt_tokens={b['avg_estimated_prompt_tokens']}")
        print(f"- trim_event_count={b['trim_event_count']}")
        print(f"- over_budget_incidents={b['over_budget_incidents']}")
        print(f"- trace_count={b['trace_count']}")

    if args.supervisor_status:
        did_work = True
        print("supervisor-status: available (use littlehive-supervisor --once)")

    if not did_work:
        print(
            "diag-ready (use --validate-config/--hardware/--check-providers/--recommend-models "
            "--provider-health/--failures/--runtime-stats/--budget-stats)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
