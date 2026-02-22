# Ops

## Admin API

Default bind should remain localhost unless explicitly exposed.

Key endpoints:
- `GET /health`
- `GET /status`
- `GET /providers`
- `GET /tasks`
- `GET /tasks/{task_id}/trace`
- `GET /memory/search`
- `GET /permissions/profile`
- `PATCH /permissions/profile`
- `GET /usage`
- `GET /diagnostics/failures`
- `GET /diagnostics/budgets`
- `GET /confirmations`
- `PATCH /confirmations/{id}`

If `LITTLEHIVE_ADMIN_TOKEN` is set, mutation endpoints require `X-Admin-Token`.

## Dashboard

```bash
littlehive-dashboard --config config/instance.yaml
```

Default host/port from config:
- `dashboard_host`
- `dashboard_port`

## Migrations
```bash
alembic upgrade head
```

## Packaging
```bash
python -m build
twine check dist/*
```
