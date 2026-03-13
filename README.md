# LittleHive 🐝

**A private, local-first AI executive assistant built exclusively for Apple Silicon.**

LittleHive runs entirely on your Mac — powered by Mistral's **Ministral** models via Apple's **MLX** framework. Your emails, calendar, and personal data never leave your machine.

No cloud AI. No subscription. Just a fast, intelligent assistant on your hardware.

---

## Features

- **100% Local AI** — Runs Ministral 3B / 8B / 14B natively on Apple Silicon via MLX with KV prompt caching for sub-second responses.
- **Google Workspace** — Connects to Gmail, Google Calendar, and Google Tasks. Read, draft, send emails (with PDF attachments); create events; manage tasks.
- **GitHub Integration** — Create, list, update, and close GitHub issues. Add comments to issues and PRs directly from chat.
- **Web Search** — Search the web via DuckDuckGo for current events, prices, or facts the model isn't confident about.
- **Webpage Reader** — Fetch and summarize any webpage by URL. Just paste a link and ask for a summary.
- **Custom APIs** — Register external APIs (weather, stocks, smart home, RSS feeds) and the agent calls them on demand. Supports JSON and XML/RSS responses. Auto-geocodes location-based APIs.
- **Shell & File Tools** — Run governed shell commands and manage files within a sandboxed workspace. Three-tier security (allowed / logged / blocked) with a full audit trail. Disabled by default.
- **Text-to-Speech** — Ask the agent to announce something and it speaks aloud on your Mac using the built-in `say` command.
- **Proactive Scheduling** — Background threads poll for new emails, fire reminders on time, and sync your calendar automatically.
- **Long-Term Memory** — Remembers important facts across conversations. Nightly extraction saves key details from your chats.
- **Contacts Directory** — Manage stakeholders with optional auto-reply drafting for trusted contacts.
- **Finance Tracking** — Track bills, due dates, and mark payments as they come in.
- **Telegram Bot** — Chat with your assistant from Telegram with typing indicators and chat ID authorization.
- **Web Dashboard** — A local web interface with real-time chat, context usage monitoring, dark mode, and full configuration.
- **Self-Updating** — Check for and install updates directly from PyPI with a single command.

---

## Requirements

- **Hardware:** Apple Silicon Mac (M1, M2, M3, or M4). Intel Macs are not supported.
- **RAM:** 8 GB minimum (3B model), 16 GB recommended (8B model), 24+ GB ideal (14B model).
- **Software:** macOS with Python 3.11+.

---

## Installation

**1. Create a virtual environment:**
```bash
python3 -m venv littlehive-env
source littlehive-env/bin/activate
```

**2. Install LittleHive:**
```bash
pip install littlehive
```

**3. Run the setup wizard:**
```bash
lhive setup
```

The wizard walks you through identity, Google OAuth, Telegram, model selection, and preferences. Takes about 2 minutes.

---

## CLI Commands

```
lhive setup          Interactive setup wizard (run this first)
lhive start          Start the agent in the background
lhive stop           Stop the agent
lhive restart        Restart the agent
lhive status         Show agent status and configuration
lhive update         Check for and install updates from PyPI
lhive version        Show current version
lhive auth google    Re-run Google OAuth flow
```

The first `lhive start` downloads the AI model (~2-8 GB depending on model size). Subsequent starts are instant.

---

## Dashboard

Once the agent is running, open your browser:

**http://localhost:8080**

The dashboard includes:
- **Dashboard** — Chat with your agent, view unread emails, today's events, reminders, task queue, and pending bills at a glance.
- **Contacts** — Manage your contacts directory and auto-reply settings.
- **Memories** — View, edit, or delete facts the agent has memorized.
- **Custom APIs** — Register and manage external API integrations.
- **System** — Background schedulers, data management (flush queues), and shell audit log.
- **Settings** — Configure identity, model, Telegram, GitHub, shell tools, and task preferences.
- **Top Bar** — Live clock, context usage %, model name, connection status, and theme toggle.

---

## What Can You Ask?

- **Email:** *"Do I have unread emails?"* · *"Send a PDF summary about AI trends to Sarah."* · *"Archive all newsletters."*
- **Calendar:** *"What's on my schedule tomorrow?"* · *"Block 2 hours for deep work."*
- **Reminders:** *"Remind me about the dentist at 3 PM."* · *"What reminders do I have?"*
- **Web Search:** *"What's the latest news on AI?"* · *"Current weather in London."*
- **Webpage:** *"Summarize this page: https://example.com/article"*
- **GitHub:** *"Create an issue for the login bug."* · *"List open issues on stackcv."* · *"Close issue #42."*
- **Custom APIs:** *"What's the weather right now?"* · *"Register an API for stock prices."*
- **Finance:** *"Add a bill for electricity — $240 due March 20."* · *"Mark the internet bill as paid."*
- **Memory:** *"Remember that my son's name is Vivaan."* · *"Who is in my family?"*
- **Contacts:** *"Look up Sarah's email."* · *"Add John as a contact."*
- **Shell:** *"List files in my workspace."* · *"Run git status."*
- **TTS:** *"Announce: dinner is ready!"*

### Chat Commands

Type these directly in the chat window or Telegram:

```
/reset    Wipe context and start a fresh conversation
/context  Show current token usage and context health
/clear    Clear the chat window (UI only, keeps memory)
/help     Show available commands
```

---

## Optional Integrations

| Integration | Setup |
|---|---|
| **Google Workspace** | Run `lhive auth google` with your `credentials.json` from Google Cloud Console |
| **Telegram** | Create a bot via @BotFather, add the token in Settings |
| **GitHub** | Generate a Personal Access Token with `repo` scope, add it in Settings |
| **Custom APIs** | Register via the dashboard or chat: *"Register an API called get_weather..."* |
| **Shell Tools** | Enable in Settings, configure workspace folder and command permissions |

---

## Data Storage

Everything stays local:

| Path | Contents |
|------|----------|
| `~/.littlehive/config/` | Configuration and Google OAuth tokens |
| `~/.littlehive/db/littlehive.db` | Chat history, memories, reminders, cached emails, custom APIs, shell audit log |
| `~/.littlehive/logs/agent.log` | Runtime logs for troubleshooting |

---

## License

MIT
