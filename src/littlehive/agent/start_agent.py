import sys
import os
import time
import json
import re
import logging
import threading
from littlehive.agent.logger_setup import logger
import requests
from datetime import datetime, timedelta

# Suppress noisy library logs
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
logging.getLogger("google_auth_oauthlib.flow").setLevel(logging.ERROR)

from littlehive.agent.config import get_config, save_config_value
from littlehive.agent.scheduler import start_proactive_scheduler
from littlehive.agent.queues import inbox_queue, outbox_telegram, outbox_web, MultiOutbox, context_stats
from littlehive.agent.constants import (
    MSG_TYPE_INIT, MSG_TYPE_TOOL_START, MSG_TYPE_DONE, MSG_TYPE_ERROR,
    SOURCE_TELEGRAM, SOURCE_WEB, SOURCE_SYSTEM, SOURCE_SYSTEM_MAINTENANCE, CMD_SHUTDOWN, CMD_EXTRACT_MEMORIES, CMD_MORNING_BRIEF
)


import mlx.core as mx
from mlx_lm import load, generate, stream_generate
from mlx_lm.models.cache import make_prompt_cache
from mlx_lm.sample_utils import make_sampler
from littlehive.agent.tool_registry import dispatch_tool, EA_PERSONA_TOOLS
from littlehive.agent.self_healing import resilient_dispatch_tool
from littlehive.agent.locks import mlx_lock
from littlehive.agent.parser import parse_mistral_tool_calls
from littlehive.tools.memory_tools import archive_messages
from littlehive.agent.anticipation import log_action, _make_turn_id
from littlehive.agent.slash_commands import try_slash_command

# Global to store the latest Telegram chat ID for proactive notifications
config_init = get_config()
active_telegram_chat_id = config_init.get("telegram_chat_id")


# --- THE TELEGRAM THREAD ---
def telegram_worker():
    config = get_config()
    BOT_TOKEN = config.get("telegram_bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not BOT_TOKEN:
        logger.warning(
            "\n[Warning] telegram_bot_token not set in config.json or env. Telegram bot will NOT run."
        )
        return

    BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

    def send_message(chat_id, text):
        if not text.strip():
            return
        requests.post(
            f"{BASE_URL}/sendMessage", json={"chat_id": chat_id, "text": text}
        )

    def edit_message(chat_id, message_id, text):
        if not text.strip():
            return
        requests.post(
            f"{BASE_URL}/editMessageText",
            json={"chat_id": chat_id, "message_id": message_id, "text": text},
        )

    update_offset = None
    logger.info("[Telegram] Thread started. Waiting for messages...")

    def _get_allowed_chat_ids():
        """Return a set of allowed chat IDs from config (supports comma-separated)."""
        raw = config.get("telegram_chat_id", "")
        if not raw:
            return set()
        ids = set()
        for part in str(raw).split(","):
            part = part.strip()
            if part:
                try:
                    ids.add(int(part))
                except ValueError:
                    pass
        return ids

    def send_typing(chat_id):
        """Show 'typing...' indicator in the Telegram chat header."""
        try:
            requests.post(
                f"{BASE_URL}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"},
            )
        except Exception:
            pass

    def telegram_sender():
        active_chat_id = None
        typing_timer = None

        def _keep_typing():
            """Telegram typing indicator expires after ~5s, so re-send it periodically."""
            while active_chat_id:
                send_typing(active_chat_id)
                time.sleep(4)

        while True:
            msg = outbox_telegram.get()
            if msg.get("type") == MSG_TYPE_INIT:
                active_chat_id = msg["chat_id"]
                send_typing(active_chat_id)
                typing_timer = threading.Thread(target=_keep_typing, daemon=True)
                typing_timer.start()
            elif msg.get("type") == MSG_TYPE_TOOL_START:
                if active_chat_id:
                    send_typing(active_chat_id)
            elif msg.get("type") == MSG_TYPE_DONE:
                content = msg.get("content", "").strip()
                prev_chat_id = active_chat_id
                active_chat_id = None
                target = prev_chat_id or msg.get("chat_id")
                if content and target:
                    send_message(target, content)
            elif msg.get("type") == MSG_TYPE_ERROR:
                prev_chat_id = active_chat_id
                active_chat_id = None
                target = prev_chat_id or msg.get("chat_id")
                if target:
                    send_message(target, f"Error: {msg['content']}")

    t_sender = threading.Thread(target=telegram_sender, daemon=True)
    t_sender.start()

    # The main Telegram Long-Polling Loop
    while True:
        try:
            resp = requests.get(
                f"{BASE_URL}/getUpdates",
                params={"timeout": 30, "offset": update_offset},
                timeout=35,
            )
            updates = resp.json()
        except Exception:
            time.sleep(1)
            continue

        if not updates or "result" not in updates:
            continue

        for update in updates["result"]:
            update_offset = update["update_id"] + 1
            if "message" not in update or "text" not in update["message"]:
                continue

            # Telegram API structure: update["message"]["chat"]["id"]
            if "chat" not in update["message"] or "id" not in update["message"]["chat"]:
                continue

            chat_id = update["message"]["chat"]["id"]
            user_input = update["message"]["text"]

            allowed = _get_allowed_chat_ids()

            if user_input.strip() == "/start":
                if not allowed:
                    global active_telegram_chat_id
                    active_telegram_chat_id = chat_id
                    save_config_value("telegram_chat_id", str(chat_id))
                    logger.info(f"[Telegram] First user registered: chat_id={chat_id}")
                    send_message(chat_id, "Hello! I am your Senior Executive Assistant. You are now linked.")
                elif chat_id in allowed:
                    send_message(chat_id, "Hello! I am your Senior Executive Assistant.")
                continue

            if allowed and chat_id not in allowed:
                logger.debug(f"[Telegram] Ignoring message from unauthorized chat_id={chat_id}")
                continue

            if active_telegram_chat_id != chat_id:
                active_telegram_chat_id = chat_id

            # Drop into the master queue, including the chat_id so we know where to reply
            outbox_telegram.put({"type": MSG_TYPE_INIT, "chat_id": chat_id})
            inbox_queue.put(
                {"source": SOURCE_TELEGRAM, "text": user_input, "chat_id": chat_id}
            )


# --- THE CORE BRAIN (Main Thread) ---



_geocode_cache = {}

def _geocode_location(location_str: str) -> tuple:
    """Resolve a city/location name to (latitude, longitude) using Open-Meteo geocoding.
    Returns (None, None) on failure. Results are cached in-memory."""
    if not location_str or location_str == "Unknown Location":
        return None, None

    if location_str in _geocode_cache:
        return _geocode_cache[location_str]

    try:
        resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location_str, "count": 1, "language": "en"},
            timeout=5,
        )
        data = resp.json()
        results = data.get("results", [])
        if results:
            lat = round(results[0]["latitude"], 4)
            lon = round(results[0]["longitude"], 4)
            _geocode_cache[location_str] = (lat, lon)
            return lat, lon
    except Exception:
        pass

    _geocode_cache[location_str] = (None, None)
    return None, None


def get_system_prompt():
    config = get_config()
    location_str = config.get("home_location", "Unknown Location")
    utc_offset_sec = time.altzone if time.localtime().tm_isdst else time.timezone
    offset_hours = int(-utc_offset_sec / 3600)
    offset_mins = int((abs(-utc_offset_sec) % 3600) / 60)
    sign = "+" if -utc_offset_sec >= 0 else "-"
    offset_str = f"{sign}{abs(offset_hours):02d}:{abs(offset_mins):02d}"
    default_tz = f"{time.tzname[time.localtime().tm_isdst]} (UTC{offset_str})"

    prompt_path = os.path.join(os.path.dirname(__file__), "system_prompt.md")
    try:
        with open(prompt_path, "r") as f:
            template = f.read()
    except Exception as e:
        logger.error(f"Failed to load system prompt from {prompt_path}: {e}")
        template = "You are an AI assistant. (Fallback prompt due to error)\n### RUNTIME CONTEXT\n### CORE FACTS ABOUT THE PRINCIPAL\n{core_facts}\n{dynamic_context}"

    try:
        from littlehive.tools.memory_tools import get_all_core_facts
        facts_list = get_all_core_facts()
        core_facts_str = "\n".join([f"- {fact}" for fact in facts_list]) if facts_list else "No specific core facts loaded."
    except Exception as e:
        logger.error(f"Failed to load core facts: {e}")
        core_facts_str = "Memory subsystem unavailable."

    custom_apis_str = ""
    try:
        from littlehive.tools.api_registry_tools import get_api_descriptions
        custom_apis_str = get_api_descriptions()
    except Exception:
        pass

    # Build dynamic time-aware context
    dynamic_context_str = ""
    try:
        from littlehive.agent.dynamic_context import build_dynamic_context
        dynamic_context_str = build_dynamic_context()
    except Exception as e:
        logger.debug(f"Dynamic context generation skipped: {e}")

    lat, lon = _geocode_location(location_str)
    location_with_coords = location_str
    if lat is not None and lon is not None:
        location_with_coords = f"{location_str} (latitude={lat}, longitude={lon})"

    rendered = template.format(
        date=datetime.now().strftime("%A, %B %d, %Y"),
        timezone=os.environ.get("AGENT_TIMEZONE", default_tz),
        location=location_with_coords,
        agent_name=config.get("agent_name", "Roxy"),
        agent_title=config.get("agent_title", "Executive Staff"),
        user_name=config.get("user_name", "John Doe"),
        core_facts=core_facts_str,
        dynamic_context=dynamic_context_str,
    )

    if custom_apis_str:
        rendered += f"\n\n## REGISTERED CUSTOM APIs\n{custom_apis_str}"

    return rendered

def main():
    config = get_config()
    model_path = config.get(
        "model_path", "mlx-community/mistralai_Ministral-3-14B-Instruct-2512-MLX-MXFP4"
    )

    logger.info(
        f"Initializing Core Brain & loading model ({model_path.split('/')[-1]})..."
    )

    all_possible_tools = EA_PERSONA_TOOLS

    def warm_cache(messages_list, cache, tools_list):
        """Pre-encode the system prompt + tool schemas into the KV cache.
        Returns (previous_prompt_tokens, cache) ready for incremental generation."""
        chat_kwargs_warmup = {
            "tokenize": False,
            "add_generation_prompt": False,
            "tools": tools_list,
        }
        warmup_text = tokenizer.apply_chat_template(messages_list, **chat_kwargs_warmup)
        tokens = tokenizer.encode(warmup_text)

        tokens_tensor = mx.array(tokens)[None]
        _ = model(tokens_tensor, cache=cache)

        eval_list = []
        for c in cache:
            eval_list.append(c.keys)
            eval_list.append(c.values)
        mx.eval(eval_list)
        return tokens

    MAX_CONTEXT_TOKENS = 131072

    try:
        model, tokenizer = load(model_path)
        prompt_cache = make_prompt_cache(model)

        messages = [{"role": "system", "content": get_system_prompt()}]
        historically_active_tools = list(all_possible_tools)

        logger.info("Pre-warming prompt cache with System Prompt + Tool Schemas...")
        previous_prompt_tokens = warm_cache(messages, prompt_cache, historically_active_tools)

        logger.info("Pre-compiling generation graph with cache...")
        try:
            dummy_prompt = tokenizer.encode("Hi")
            with mlx_lock:
                _ = generate(
                    model,
                    tokenizer,
                    prompt=dummy_prompt,
                    prompt_cache=prompt_cache,
                    max_tokens=1,
                )
            for c in prompt_cache:
                c.offset = len(previous_prompt_tokens)
        except Exception as e:
            logger.debug(f"Dummy generation skipped: {e}")

        context_stats["tokens_used"] = len(previous_prompt_tokens)
        context_stats["max_tokens"] = MAX_CONTEXT_TOKENS
        context_stats["messages"] = len(messages)
        logger.info(
            f"✅ [Brain] Cache warmed with {len(previous_prompt_tokens)} tokens! Agent is ready and fast."
        )

    except Exception as e:
        logger.error(f"❌ [Error] Model Initialization Failed: {e}")
        sys.exit(1)

    # Start the Peripheral Senses AFTER Model and Cache are ready
    logger.info("🚀 Starting Web Dashboard and Telegram Bot...")
    from littlehive.dashboard.server import start_dashboard_server

    start_dashboard_server(port=8080, inbox=inbox_queue, outbox=outbox_web)

    t_telegram = threading.Thread(target=telegram_worker, daemon=True)
    t_telegram.start()

    start_proactive_scheduler(
        inbox_queue, outbox_web, outbox_telegram, lambda: active_telegram_chat_id
    )

    logger.info("✨ [Brain] All senses active. Listening to Inbox Queue...")

    is_first_message_of_session = True
    CONTEXT_BUDGET_THRESHOLD = 0.60

    def _friendly_time(iso_str):
        """Convert '2026-03-12T08:00:00+05:30' to '8:00 AM'."""
        try:
            dt = datetime.fromisoformat(iso_str)
            return dt.strftime("%-I:%M %p").lstrip("0")
        except Exception:
            return iso_str

    def _fire_welcome_brief(delay=3):
        """After a short delay, read the local cache and inject a status brief."""
        def _run():
            time.sleep(delay)
            try:
                from littlehive.agent.local_cache import query_cached_emails, query_cached_events
                import json as _json

                parts = []

                emails_str = query_cached_emails("is:unread", limit=5)
                emails_data = _json.loads(emails_str)
                unread = emails_data.get("emails", [])
                if unread:
                    email_lines = [f"  - {e['sender'].split('<')[0].strip()}: {e['subject']}" for e in unread[:5]]
                    parts.append(f"**Unread emails ({len(unread)}):**\n" + "\n".join(email_lines))

                now = datetime.now()
                end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)

                # Today's remaining events (never bleed into tomorrow)
                today_str = query_cached_events(
                    time_min=now.isoformat(),
                    time_max=end_of_day.isoformat()
                )
                today_events = _json.loads(today_str)
                if today_events:
                    seen = set()
                    lines = []
                    for e in today_events[:10]:
                        s = e.get("summary", "Untitled")
                        if s in seen:
                            continue
                        seen.add(s)
                        lines.append(f"  - {s} at {_friendly_time(e.get('start', ''))}")
                    if lines:
                        label = "**Upcoming today:**" if now.hour < 18 else "**Remaining today:**"
                        parts.append(label + "\n" + "\n".join(lines[:5]))

                # Evening lookahead: after 6 PM, peek at tomorrow's morning events
                if now.hour >= 18:
                    tomorrow_start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                    tomorrow_noon = tomorrow_start.replace(hour=12)
                    tmrw_str = query_cached_events(
                        time_min=tomorrow_start.isoformat(),
                        time_max=tomorrow_noon.isoformat()
                    )
                    tmrw_events = _json.loads(tmrw_str)
                    if tmrw_events:
                        seen = set()
                        lines = []
                        for e in tmrw_events[:5]:
                            s = e.get("summary", "Untitled")
                            if s in seen:
                                continue
                            seen.add(s)
                            lines.append(f"  - {s} at {_friendly_time(e.get('start', ''))}")
                        if lines:
                            parts.append("**Heads-up for tomorrow morning:**\n" + "\n".join(lines))

                from littlehive.tools.reminder_tools import get_pending_reminders
                rem_str = get_pending_reminders()
                rem_data = _json.loads(rem_str)
                rems = rem_data if isinstance(rem_data, list) else []
                if rems:
                    rem_lines = [f"  - {r.get('task', r.get('title', '?'))}" for r in rems[:5]]
                    parts.append(f"**Active reminders ({len(rems)}):**\n" + "\n".join(rem_lines))

                if parts:
                    brief = "Here's your quick brief:\n\n" + "\n\n".join(parts)
                else:
                    brief = "All clear — no pending emails, events, or reminders right now."

                outbox_web.put({"type": MSG_TYPE_DONE, "content": brief})
                chat_id = active_telegram_chat_id
                if chat_id:
                    outbox_telegram.put({"type": MSG_TYPE_DONE, "content": brief, "chat_id": chat_id})
            except Exception as e:
                logger.debug(f"[Welcome Brief] Skipped: {e}")

        threading.Thread(target=_run, daemon=True).start()

    while True:
        # Block until a message arrives from ANY interface
        task = inbox_queue.get()

        if task.get("source") == SOURCE_SYSTEM and task.get("command") == CMD_SHUTDOWN:
            logger.info("\nShutting down master brain...")
            sys.exit(0)

        logger.info(f"📬 Received message from {task.get('source')}: {task.get('text')[:50]}...")

        source = task["source"]
        user_input = task["text"]

        if source == SOURCE_SYSTEM_MAINTENANCE and user_input == CMD_EXTRACT_MEMORIES:
            from littlehive.agent.scheduled_jobs import run_memory_extraction
            run_memory_extraction(model, tokenizer)
            continue
            
        if source == SOURCE_SYSTEM_MAINTENANCE and user_input == CMD_MORNING_BRIEF:
            from littlehive.agent.scheduled_jobs import run_morning_brief
            run_morning_brief(model, tokenizer, inbox_queue, active_telegram_chat_id)
            continue

        outbox = MultiOutbox(source, active_telegram_chat_id)

        cmd = user_input.strip().lower()
        if cmd in ["/reset", "/new"]:
            messages = [{"role": "system", "content": get_system_prompt()}]
            historically_active_tools = list(all_possible_tools)
            prompt_cache = make_prompt_cache(model)
            previous_prompt_tokens = warm_cache(messages, prompt_cache, historically_active_tools)
            is_first_message_of_session = True
            context_stats["tokens_used"] = len(previous_prompt_tokens)
            context_stats["messages"] = len(messages)
            logger.info(f"🔄 [Brain] Cache re-warmed with {len(previous_prompt_tokens)} tokens after reset.")
            outbox.put({"type": MSG_TYPE_DONE, "content": "🧠 Memory wiped and cache rebuilt. Starting a fresh conversation."})
            continue

        elif cmd in ["/context", "/status"]:
            tok_len = len(previous_prompt_tokens)
            perc = (tok_len / MAX_CONTEXT_TOKENS) * 100
            health = "🟢 Healthy" if perc < 50 else ("🟡 Moderate" if perc < CONTEXT_BUDGET_THRESHOLD * 100 else "🔴 High — consider /reset")
            reply = (
                f"📊 **Context Status:**\n"
                f"Tokens Used: {tok_len:,} / {MAX_CONTEXT_TOKENS:,} ({perc:.1f}%)\n"
                f"Messages in memory: {len(messages)}\n"
                f"Health: {health}"
            )
            outbox.put({"type": MSG_TYPE_DONE, "content": reply})
            continue

        elif cmd == "/help":
            reply = (
                "🛠️ **Available Commands:**\n"
                "`/clear` - Clear the UI window (keeps memory)\n"
                "`/reset` or `/new` - Wipe agent's memory/context for a fresh start\n"
                "`/context` or `/status` - Check current token usage\n"
                "`/help` - Show this message\n\n"
                "⚡ **Instant Slash Commands** (bypass AI, execute directly):\n"
                "`/email <name> about <subject>: <body>` - Draft an email\n"
                "`/remind <time> <task>` - Set a reminder (e.g. `/remind 5pm call mom`)\n"
                "`/bill <amount> <vendor> due <date>` - Record a bill\n"
                "`/search <query>` - Quick web search\n"
                "`/cal [today|tomorrow|week]` - Check your calendar\n"
                "`/bills` - List pending bills\n"
                "`/reminders` - List pending reminders"
            )
            outbox.put({"type": MSG_TYPE_DONE, "content": reply})
            continue

        # --- SLASH COMMAND PRE-PROCESSOR ---
        # Intercept structured commands and execute directly without LLM inference.
        if user_input.strip().startswith("/"):
            slash_response, slash_tool_info = try_slash_command(user_input)
            if slash_response is not None:
                logger.info(f"⚡ [SlashCmd] Handled instantly: {user_input[:40]}...")
                outbox.put({"type": MSG_TYPE_DONE, "content": slash_response})
                if slash_tool_info:
                    log_action(
                        slash_tool_info["tool"],
                        slash_tool_info.get("args", {}),
                        source=source,
                        turn_id=_make_turn_id(user_input),
                        session_position=0,
                    )
                continue

        current_time_str = datetime.now().strftime("%A, %b %d, %I:%M %p")
        # Removing "Source: Telegram" from the user input string.
        # It confuses the LLM into thinking the user is asking ABOUT Telegram.
        context_input = f"[Current Time: {current_time_str}] {user_input}"
        
        # Save the clean, short message to persistent history
        messages.append({"role": "user", "content": context_input})


            
        # --- EPHEMERAL ATTACHMENT INJECTION ---
        # If the web UI intercepted a massive text block, we inject it ONLY for this turn
        # so it doesn't pollute the long-term sliding window KV cache.
        attachment = task.get("attachment", None)
        active_messages_for_turn = list(messages)
        
        if attachment:
            logger.info(f"📎 Injecting ephemeral attachment of length {len(attachment)} into current turn context.")
            # We append the attachment specifically to the final user message for this evaluation
            injected_content = active_messages_for_turn[-1]["content"] + f"\n\n[USER ATTACHMENT DATA (DO NOT STORE THIS IN MEMORY)]\n{attachment}\n[/USER ATTACHMENT DATA]"
            active_messages_for_turn[-1] = {"role": "user", "content": injected_content}
            # Because we are changing the end of the prompt dynamically for one turn, 
            # we must reset the prompt cache so it evaluates the attachment correctly.
            previous_prompt_tokens = []
            prompt_cache = make_prompt_cache(model)

        has_fired_tool_indicator = False
        message_start_time = time.time()
        turn_id = _make_turn_id(user_input)
        tool_chain_idx = 0
        logger.info(f"🧠 [Brain] Beginning thought process for: {user_input[:30]}...")

        try:
            tool_call_prefix = re.compile(r"^\s*(?:</s>\s*)?\[TOOL_CALLS\]")
            tool_call_anywhere = re.compile(r"\[TOOL_CALLS\]")
            while True:  # Tool Chaining Loop
                chat_kwargs = {"tokenize": False, "add_generation_prompt": True}
                if historically_active_tools:
                    chat_kwargs["tools"] = historically_active_tools

                # Use the modified active_messages_for_turn which may contain the attachment
                full_prompt_text = tokenizer.apply_chat_template(
                    active_messages_for_turn, **chat_kwargs
                )
                full_prompt_tokens = tokenizer.encode(full_prompt_text)
                prompt_tokens = full_prompt_tokens[len(previous_prompt_tokens) :]

                # Guard against zero-token incremental prompts (can happen if cache
                # state drifts from prompt state). Rebuild cache and run full prompt.
                if len(prompt_tokens) == 0:
                    logger.warning(
                        "[Brain] Zero-token incremental prompt detected; rebuilding cache for full prompt evaluation."
                    )
                    prompt_cache = make_prompt_cache(model)
                    previous_prompt_tokens = []
                    prompt_tokens = full_prompt_tokens

                temp = get_config().get("temperature", 0.35)
                sampler = make_sampler(temp=temp)

                logger.info(f"  -> Starting stream_generate with {len(prompt_tokens)} new tokens...")
                
                is_tool_call = False
                full_response = ""
                first_token_received = False
                
                with mlx_lock:
                    for response in stream_generate(
                        model,
                        tokenizer,
                        prompt=prompt_tokens,
                        prompt_cache=prompt_cache,
                        max_tokens=2048,
                        sampler=sampler,
                    ):
                        if not first_token_received:
                            first_token_received = True
                        
                        full_response += response.text
                        
                        if tool_call_prefix.match(full_response):
                            is_tool_call = True

                # Handle mid-response tool calls: the model sometimes emits
                # explanation text before [TOOL_CALLS]. Strip the preamble so
                # the tool call is still parsed and executed.
                if not is_tool_call and tool_call_anywhere.search(full_response):
                    tc_pos = full_response.index("[TOOL_CALLS]")
                    preamble = full_response[:tc_pos].strip()
                    if preamble:
                        logger.info(f"  -> Stripped {len(preamble)}-char preamble before mid-response [TOOL_CALLS]")
                    full_response = full_response[tc_pos:]
                    is_tool_call = True

                logger.info(f"  -> Done. length={len(full_response)}, is_tool_call={is_tool_call}")

                # --- CACHE ROLLBACK ---
                # MLX generate appends sampled tokens to the cache.
                # Roll back to the prompt boundary so the chat template
                # re-evaluates the response on the next turn.
                for c in prompt_cache:
                    c.offset = len(full_prompt_tokens)
                previous_prompt_tokens = full_prompt_tokens
                context_stats["tokens_used"] = len(previous_prompt_tokens)
                context_stats["messages"] = len(messages)

                if not is_tool_call:
                    final_text = full_response.strip()
                    messages.append({"role": "assistant", "content": final_text})

                    time_taken = time.time() - message_start_time
                    if source == SOURCE_WEB:
                        display_text = (
                            final_text
                            + f'\n\n<div style="font-size: 0.7em; color: gray; margin-top: 5px;">⏱️ {time_taken:.1f}s</div>'
                        )
                    else:
                        display_text = final_text

                    outbox.put({"type": MSG_TYPE_DONE, "content": display_text})

                    # Fire welcome brief after the first user message of the session
                    if is_first_message_of_session:
                        is_first_message_of_session = False
                        _fire_welcome_brief(delay=2)

                    # Context budget warning
                    tok_len = len(previous_prompt_tokens)
                    usage_pct = tok_len / MAX_CONTEXT_TOKENS
                    if usage_pct >= CONTEXT_BUDGET_THRESHOLD:
                        budget_warn = (
                            f'\n\n<div style="font-size:0.7em;color:#ec4899;margin-top:4px;">'
                            f'⚠️ Context is {usage_pct:.0%} full ({tok_len}/{MAX_CONTEXT_TOKENS} tokens). '
                            f'Consider `/reset` to start fresh.</div>'
                        )
                        outbox.put({"type": MSG_TYPE_DONE, "content": budget_warn})

                    import copy
                    threading.Thread(target=archive_messages, args=(copy.deepcopy(messages),), daemon=True).start()
                    break

                # --- Tools Triggered ---
                tool_calls_list = parse_mistral_tool_calls(full_response)

                if not tool_calls_list:
                    fallback_text = full_response.replace("[TOOL_CALLS]", "").strip()
                    if fallback_text:
                        logger.warning(
                            "[Parser] Tool marker detected but no valid tool calls parsed; returning response as plain text."
                        )
                        messages.append({"role": "assistant", "content": fallback_text})
                        outbox.put({"type": MSG_TYPE_DONE, "content": fallback_text})
                    else:
                        err_msg = "Error: Model generated a malformed tool call that could not be parsed."
                        outbox.put({"type": MSG_TYPE_ERROR, "content": err_msg})
                        messages.append(
                            {"role": "assistant", "content": f"System Error: {err_msg}"}
                        )
                    break

                if not has_fired_tool_indicator:
                    tool_names = [tc["name"] for tc in tool_calls_list]
                    outbox.put({"type": MSG_TYPE_TOOL_START, "tools": tool_names})
                    has_fired_tool_indicator = True

                formatted_tool_calls = [
                    {
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"])
                            if isinstance(tc["arguments"], dict)
                            else tc["arguments"],
                        },
                    }
                    for tc in tool_calls_list
                ]

                messages.append(
                    {
                        "role": "assistant",
                        "tool_calls": formatted_tool_calls,
                        "content": "",
                    }
                )
                active_messages_for_turn.append(
                    {
                        "role": "assistant",
                        "tool_calls": formatted_tool_calls,
                        "content": "",
                    }
                )

                for tc in tool_calls_list:
                    func_name = tc["name"]
                    func_args = tc["arguments"]

                    if get_config().get("self_healing_enabled", True):
                        max_retries = get_config().get("self_healing_max_retries", 2)
                        tool_result = resilient_dispatch_tool(
                            dispatch_tool, func_name, func_args, max_retries=max_retries
                        )
                    else:
                        tool_result = dispatch_tool(func_name, func_args)

                    log_action(func_name, func_args, source=source, turn_id=turn_id, session_position=tool_chain_idx)
                    tool_chain_idx += 1
                    
                    tool_msg = {"role": "tool", "name": func_name, "content": tool_result}
                    messages.append(tool_msg)
                    active_messages_for_turn.append(tool_msg)

                # Loop continues — tool results feed back into the next generation

        except Exception as e:
            err_msg = str(e)
            outbox.put({"type": MSG_TYPE_ERROR, "content": err_msg})
            messages.append(
                {"role": "assistant", "content": f"Internal Error: {err_msg}"}
            )
            prompt_cache = make_prompt_cache(model)
            previous_prompt_tokens = []


if __name__ == "__main__":
    main()
