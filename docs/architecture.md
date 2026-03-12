# Architecture

LittleHive is a single-process, local-first AI agent running on Apple Silicon.

## Core Components

```
┌─────────────────────────────────────────────────┐
│  start_agent.py  (main thread)                  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ MLX Model │  │ KV Cache │  │ Tool Registry │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
│          ↑ inbox_queue    ↓ outbox_web/telegram  │
├─────────────────────────────────────────────────┤
│  Peripherals (daemon threads)                    │
│  ┌──────────────┐  ┌────────────┐  ┌──────────┐ │
│  │ Web Dashboard │  │ Telegram   │  │Scheduler │ │
│  │ (port 8080)   │  │ Bot Worker │  │(APSched) │ │
│  └──────────────┘  └────────────┘  └──────────┘ │
└─────────────────────────────────────────────────┘
```

### Brain Loop (`start_agent.py`)
- Loads model via `mlx_lm.load()` with KV prompt caching
- Pre-warms cache with system prompt + tool schemas at startup
- Main loop: `inbox_queue.get()` → tool routing → generation → outbox
- Tool chaining: LLM can call tools in sequence until a text response is produced

### Tool Routing (`tool_router.py`)
- Uses `semantic-router` with sentence embeddings to classify user intent
- Maps intent to a subset of tool schemas (email, calendar, finance, etc.)
- Only relevant tools are injected per turn, keeping context lean

### Tool Registry (`tool_registry.py`)
- Central dispatch: maps tool names to Python functions
- Schemas follow OpenAI function-calling format (used by Mistral chat template)
- Tools: email, calendar, reminders, finance, contacts, memory, messaging, tasks, web search

### Dashboard (`dashboard/`)
- `server.py`: threaded HTTP server with REST API and long-polling chat
- `index.html` + `style.css` + `app.js`: SPA with Bootstrap, dark mode, live context stats

### Scheduler (`scheduler.py`)
- APScheduler-based background jobs: reminder polling, task execution, API sync, nightly cleanup/memory extraction
- Communicates with the brain via `inbox_queue` for system commands

## Data Flow

1. User message arrives (web POST or Telegram long-poll)
2. Stored in `chat_history` and put into `inbox_queue`
3. Brain thread picks up, runs semantic routing, injects tools
4. MLX generates response (may include tool calls)
5. Tool calls dispatched, results fed back for another generation round
6. Final text response sent to `outbox_web` / `outbox_telegram`

## Storage

All state lives in `~/.littlehive/`:
- `config/config.json` — user preferences, model path, Telegram token
- `config/token.json` — Google OAuth token
- `db/littlehive.db` — SQLite: memories, reminders, bills, contacts, cached emails/events, task queue, chat logs
