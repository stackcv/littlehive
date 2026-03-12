# Operations

## CLI Commands

```
lhive setup          Interactive setup wizard
lhive start          Start agent (background process)
lhive stop           Stop agent
lhive restart        Restart agent
lhive status         Show status and config summary
lhive update         Check for and install PyPI updates
lhive version        Show version
lhive auth google    Re-run Google OAuth
```

## Dashboard

Default: http://localhost:8080 (opens automatically on start)

### API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Health check + version |
| GET | `/api/dashboard` | Stat counts (emails, reminders, bills) |
| GET | `/api/context` | Current token usage and context stats |
| GET | `/api/config` | Read configuration |
| POST | `/api/config` | Update configuration |
| POST | `/api/chat/send` | Send a chat message |
| GET | `/api/chat/poll?cursor=N` | Long-poll for agent responses |
| GET | `/api/memories` | List core memories |
| PUT | `/api/memories/:id` | Edit a memory |
| DELETE | `/api/memories/:id` | Delete a memory |
| GET | `/api/contacts` | List contacts |
| POST | `/api/contacts` | Add contact |
| PUT | `/api/contacts/:id` | Update contact |
| DELETE | `/api/contacts/:id` | Delete contact |
| GET | `/api/tools` | List registered tools |

## Logs

```
~/.littlehive/logs/agent.log
```

## Database

SQLite at `~/.littlehive/db/littlehive.db`. Tables include:
- `core_memory` — Long-term facts
- `reminders` — Scheduled reminders
- `bills` — Financial tracking
- `stakeholders` — Contacts directory
- `cached_emails` / `cached_events` — Local API cache
- `pending_tasks` — Background task queue
- `system_logs` — Structured logs
- `conversation_archive` — Chat history for memory extraction

## Telegram Authorization

The bot uses a chat ID allowlist stored in `telegram_chat_id` config.
- First `/start` from any user auto-registers if no IDs are configured.
- After registration, only allowlisted chat IDs receive responses.
- Multiple IDs supported via comma-separated values (e.g. `"123456,789012"`).
