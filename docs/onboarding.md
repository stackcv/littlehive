# Onboarding

## Install
```bash
pip install "littlehive[full]"
```

## Recommended Start
```bash
littlehive-run
```

On first run this launches onboarding and generates:
- `config/instance.yaml` (no secrets)
- `.env` (env var placeholders and saved token values you provide)

Then it starts API, dashboard, supervisor, and Telegram worker if enabled.

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
