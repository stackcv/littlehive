# Onboarding

## Install
```bash
pip install littlehive
```

## Setup
```bash
lhive setup
```

The interactive wizard configures:
1. **Identity** — Your name, assistant name, title, location
2. **Google Workspace** — OAuth setup for Gmail, Calendar, Tasks (copies `credentials.json`, runs browser auth)
3. **Telegram** — Bot token from @BotFather (optional)
4. **Model** — Choose Ministral 8B (8 GB+ RAM) or 14B (16 GB+ RAM)
5. **Do Not Disturb** — Hours when proactive notifications are suppressed

Config is saved to `~/.littlehive/config/config.json`.

## Start
```bash
lhive start
```

On first start, the AI model is downloaded from Hugging Face (~4–8 GB). A spinner shows progress. Once ready, the dashboard opens at http://localhost:8080.

## Re-configure
```bash
lhive setup
```

Running setup again shows current values as defaults. Press Enter to keep, or type a new value.

## Google Re-authentication
```bash
lhive auth google
```

Deletes the existing token and re-runs the OAuth browser flow.
