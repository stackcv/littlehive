from __future__ import annotations

from littlehive.cli import base_parser
from littlehive.core.config.hardware_audit import collect_hardware_audit, render_hardware_summary
from littlehive.core.config.loader import load_app_config
from littlehive.core.config.recommender import recommend_models
from littlehive.core.providers.health import check_configured_providers


def main() -> int:
    parser = base_parser("littlehive-diag", "LittleHive diagnostics CLI")
    parser.add_argument("--config", default=None, help="Config file path")
    parser.add_argument("--validate-config", action="store_true")
    parser.add_argument("--hardware", action="store_true")
    parser.add_argument("--check-providers", action="store_true")
    parser.add_argument("--recommend-models", action="store_true")
    parser.add_argument("--skip-provider-tests", action="store_true")
    args = parser.parse_args()

    did_work = False
    cfg = None

    if args.validate_config or args.check_providers or args.recommend_models:
        try:
            cfg = load_app_config(instance_path=args.config)
            if args.validate_config:
                did_work = True
                print(f"config-valid instance={cfg.instance.name} env={cfg.environment}")
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

    if not did_work:
        print("diag-ready (use --validate-config/--hardware/--check-providers/--recommend-models)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
