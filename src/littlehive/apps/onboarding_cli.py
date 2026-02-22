from __future__ import annotations

from littlehive.cli import base_parser
from littlehive.core.config.onboarding import OnboardingAnswers, collect_interactive_answers, parse_id_list, run_onboarding


def _split_models(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def main() -> int:
    parser = base_parser("littlehive-onboard", "LittleHive onboarding CLI")
    parser.add_argument("--non-interactive", action="store_true", help="Run without interactive prompts")
    parser.add_argument("--force", action="store_true", help="Overwrite config/env output files")
    parser.add_argument("--skip-provider-tests", action="store_true", help="Skip provider connectivity tests")
    parser.add_argument("--allow-no-provider-success", action="store_true", help="Proceed even when provider checks fail")
    parser.add_argument("--config-output", default="config/instance.yaml")
    parser.add_argument("--env-output", default=".env")

    parser.add_argument("--instance-name", default="littlehive-local")
    parser.add_argument("--timezone", default="Asia/Kolkata")
    parser.add_argument("--environment", default="prod")

    parser.add_argument("--enable-telegram", action="store_true")
    parser.add_argument("--telegram-token-env", default="TELEGRAM_BOT_TOKEN")
    parser.add_argument("--telegram-allowed-ids", default="")
    parser.add_argument("--telegram-owner-id", type=int, default=None)

    parser.add_argument("--enable-local-provider", action="store_true", default=None)
    parser.add_argument("--disable-local-provider", action="store_true")
    parser.add_argument("--local-base-url", default="http://localhost:8001/v1")
    parser.add_argument("--local-api-key-env", default="LITTLEHIVE_LOCAL_PROVIDER_KEY")
    parser.add_argument("--local-models", default="llama3.1:8b")

    parser.add_argument("--enable-groq", action="store_true")
    parser.add_argument("--groq-api-key-env", default="LITTLEHIVE_GROQ_API_KEY")
    parser.add_argument("--groq-models", default="llama-3.1-8b-instant")

    parser.add_argument("--safe-mode", action="store_true", default=None)
    parser.add_argument("--unsafe-mode", action="store_true")
    parser.add_argument("--max-steps", type=int, default=4)
    parser.add_argument("--step-timeout", type=int, default=30)
    parser.add_argument("--recent-turn-limit", type=int, default=4)
    parser.add_argument("--max-memory-snippets", type=int, default=4)

    args = parser.parse_args()

    try:
        if args.non_interactive:
            enable_local_provider = True if args.enable_local_provider is None else bool(args.enable_local_provider)
            if args.disable_local_provider:
                enable_local_provider = False
            safe_mode = True if args.safe_mode is None else bool(args.safe_mode)
            if args.unsafe_mode:
                safe_mode = False
            answers = OnboardingAnswers(
                instance_name=args.instance_name,
                timezone=args.timezone,
                environment=args.environment,
                config_path=args.config_output,
                env_path=args.env_output,
                enable_telegram=args.enable_telegram,
                telegram_token_env=args.telegram_token_env,
                telegram_allowed_ids=parse_id_list(args.telegram_allowed_ids),
                telegram_owner_id=args.telegram_owner_id,
                enable_local_provider=enable_local_provider,
                local_base_url=args.local_base_url,
                local_api_key_env=args.local_api_key_env,
                local_models=_split_models(args.local_models),
                enable_groq=args.enable_groq,
                groq_api_key_env=args.groq_api_key_env,
                groq_models=_split_models(args.groq_models),
                safe_mode=safe_mode,
                max_steps=args.max_steps,
                step_timeout_seconds=args.step_timeout,
                recent_turn_limit=args.recent_turn_limit,
                max_memory_snippets=args.max_memory_snippets,
            )
        else:
            answers = collect_interactive_answers(input, print)

        result = run_onboarding(
            answers=answers,
            force=args.force,
            skip_provider_tests=args.skip_provider_tests,
            output_func=print,
            input_func=input,
            allow_no_provider_success=args.allow_no_provider_success,
        )
    except KeyboardInterrupt:
        print("Onboarding cancelled.")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Onboarding failed: {exc}")
        return 1

    print("")
    print("Onboarding summary")
    print(f"- config: {result.config_path}")
    print(f"- env: {result.env_path}")
    print(f"- hardware: {result.hardware_summary}")
    print("- provider checks:")
    for item in result.provider_results.values():
        print(f"  - {item.provider}: enabled={item.enabled} ok={item.ok} latency_ms={item.latency_ms} error={item.error}")
    print(f"- recommendation confidence: {result.recommendation.confidence}")
    print(f"- model mapping: {result.recommendation.mapping}")
    if result.recommendation.warnings:
        print(f"- warnings: {result.recommendation.warnings}")
    print("Next: littlehive-diag --validate-config --hardware --check-providers --recommend-models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
