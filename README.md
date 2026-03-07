# LittleHive 🐝

**A private, local-first AI assistant built exclusively for Apple Silicon.**

LittleHive is your personal AI agent that runs entirely on your Mac. Powered by Mistral's highly capable **Ministral 8B or 14B** model running natively via Apple's **MLX** framework, LittleHive ensures that your data, emails, and schedule are processed locally and completely privately.

No cloud processing for the AI. No subscription fees. Just a fast, intelligent assistant living on your machine.

---

## ✨ Major Features

*   **100% Local AI:** Uses Apple's MLX to run the Ministral 8B or 14B model directly on your hardware, ensuring lightning-fast responses and absolute privacy.
*   **Google Workspace Integration:** Securely connects to your Gmail and Google Calendar to read, draft, send emails, and manage your daily schedule.
*   **Proactive Assistant:** Runs quietly in the background. It polls for new events, handles scheduled reminders, and manages tasks without you having to constantly prompt it.
*   **Long-Term Memory:** Automatically extracts and remembers context from your past conversations, becoming more personalized over time.
*   **Web Dashboard:** Includes a clean, built-in local web interface to chat with your assistant, monitor background tasks, and easily manage your settings.

---

## 💻 Requirements

*   **Hardware:** An Apple Silicon Mac (M1, M2, M3, or M4 series). *Intel Macs are not supported.*
*   **Software:** macOS with Python 3.11 or higher installed.

---

## 🚀 Installation

It is highly recommended to install LittleHive inside an isolated Python "virtual environment" to keep your system clean.

**1. Create and activate a virtual environment:**
Open your terminal and run:
```bash
python3 -m venv littlehive-env
source littlehive-env/bin/activate
```

**2. Install LittleHive:**
```bash
pip install littlehive
```

---

## 🕹️ Usage

Once installed, managing your assistant is incredibly simple using the `lhive` command.

**Start the Assistant:**
```bash
lhive start
```
*Note: The first time you start LittleHive, it will download the Ministral AI model. This might take a few minutes depending on your internet connection.*

**Access the Dashboard:**
Once the assistant is awake, open your web browser and navigate to:
👉 **[http://localhost:8080](http://localhost:8080)**

**Stop the Assistant:**
```bash
lhive stop
```

*(You can also use `lhive restart` to quickly reboot the agent).*

---

## 💬 What can you ask LittleHive?

Because LittleHive is deeply integrated with your local environment and Google Workspace, you can ask it to perform complex, multi-step tasks natively:

*   **Email Management:**
    *   *"Do I have any unread emails from my manager?"*
    *   *"Draft a polite reply to Sarah saying I'll have the report ready by Friday, and send it."*
    *   *"Archive all the newsletter emails I received today."*
*   **Calendar & Scheduling:**
    *   *"What does my schedule look like tomorrow morning?"*
    *   *"Block out 2 hours for deep work this afternoon."*
    *   *"Schedule a 30-minute sync with Alex for next Tuesday at 10 AM."*
*   **Reminders & Tasks:**
    *   *"Remind me to check the oven in 45 minutes."*
    *   *"Set a reminder to follow up on the marketing budget next Monday at 9 AM."*
*   **Memory & Context:**
    *   *"What was the name of the restaurant John recommended to me last week?"*
    *   *"Summarize the key points from our conversation yesterday regarding the new project."*

---

## ⚙️ Customizing LittleHive

You can easily tweak LittleHive's behavior via the Web Dashboard or by editing the configuration files in `~/.littlehive/config/`. 

**Simple settings you can change:**
*   **AI Model:** Switch to a different MLX-compatible model (e.g., swapping between 8B and 14B versions depending on your Mac's RAM).
*   **User Details:** Add your name, timezone, and personal preferences so the AI has better context when helping you.
*   **Polling Intervals:** Adjust how often the background agent checks for new emails or upcoming calendar events.

---

## 📂 Where is my data?

LittleHive believes your data belongs to you. Everything is stored locally in your home directory:

*   **Main Directory:** `~/.littlehive/`
*   **Logs:** `~/.littlehive/logs/agent.log` (Check here if you ever need to troubleshoot)
*   **Local Database:** `~/.littlehive/db/littlehive.db` (Contains your chat history, memory, and reminders)
*   **Configuration & Auth:** `~/.littlehive/config/`
