# Onboarding

## Install
```bash
pip install littlehive
```

## Recommended Start
```bash
lhive run
# or: lh-run
```

On first run this launches onboarding and generates:
- `config/instance.yaml` (no secrets)
- `.env` (env var placeholders and saved token values you provide)

Then it starts API, dashboard, and Telegram worker if enabled. Supervisor stays off by default.

Use full onboarding prompts when needed:
```bash
lhive run --advanced
```

To wipe local setup and start over:
```bash
lhive reset
# or: lh-reset
```

## Manual Generate Config
```bash
littlehive-onboard
```

Outputs:
- `config/instance.yaml` (no secrets)
- `.env` (env var placeholders)

## Validate
```bash
littlehive-diag --validate-config --hardware --check-providers --recommend-models
```

## Start Services
```bash
littlehive-api --config config/instance.yaml
littlehive-dashboard --config config/instance.yaml
littlehive-telegram --config config/instance.yaml
```
