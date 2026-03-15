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
lhive setup          Interactive setup wiz