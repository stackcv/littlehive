import json
import sqlite3
import logging
from mlx_lm import generate

from littlehive.agent.paths import DB_PATH
from littlehive.tools.memory_tools import save_core_fact

logger = logging.getLogger(__name__)


def run_memory_extraction(model, tokenizer):
    """
    Nightly scheduled job: reads the last 24 hours of chat history,
    extracts persistent user facts, and saves them to core memory.
    """
    try:
        logger.info("[Scheduled: Memory] Starting nightly memory extraction...")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content FROM chat_archive WHERE datetime(timestamp) >= datetime('now', '-1 day')"
        )
        chats = cursor.fetchall()
        conn.close()

        chat_text = "\n".join(
            [
                f"{r[0]}: {r[1]}"
                for r in chats
                if r[1] and r[0] in ("user", "assistant")
            ]
        )
        
        if not chat_text.strip():
            logger.info("[Scheduled: Memory] No recent chat history found. Skipping extraction.")
            return

        prompt = f"Analyze the following conversation from the last 24 hours. Extract any new, persistent facts about the user (e.g., preferences, relationships, names). Return ONLY a JSON list of strings representing the facts. If none, return [].\n\nChat:\n{chat_text}"
        temp_messages = [
            {
                "role": "system",
                "content": "You are a data extraction assistant. Output only a raw JSON list of strings.",
            },
            {"role": "user", "content": prompt},
        ]
        
        temp_prompt_str = tokenizer.apply_chat_template(
            temp_messages, tokenize=False, add_generation_prompt=True
        )

        response = generate(
            model,
            tokenizer,
            prompt=temp_prompt_str,
            verbose=False,
            max_tokens=300,
        )
        
        start = response.find("[")
        end = response.rfind("]")
        if start != -1 and end != -1 and end > start:
            facts = json.loads(response[start : end + 1])
            if isinstance(facts, list):
                count = 0
                for f in facts:
                    if isinstance(f, str):
                        save_core_fact(f)
                        count += 1
                logger.info(f"[Scheduled: Memory] Extracted and saved {count} new facts.")
            else:
                logger.info("[Scheduled: Memory] No new facts found (JSON was not a list).")
        else:
             logger.info("[Scheduled: Memory] No facts extracted or model did not return a valid JSON list.")

    except Exception as e:
        logger.error(f"[Scheduled: Memory] Memory extraction failed: {e}")


def run_morning_brief(model, tokenizer, inbox_queue, chat_id):
    """
    Morning scheduled job: reads unprocessed intelligence from the database,
    summarizes it, and sends a morning brief to the user.
    """
    try:
        logger.info("[Scheduled: Brief] Starting Morning Intelligence Brief...")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT id, source, topic, content FROM raw_intelligence WHERE processed = 0"
        )
        rows = cursor.fetchall()
        
        if not rows:
            logger.info("[Scheduled: Brief] No new intelligence found. Skipping brief.")
            conn.close()
            return
            
        intel_dump = "Here is the raw intelligence gathered overnight:\n\n"
        row_ids = []
        for r in rows:
            row_ids.append(r["id"])
            intel_dump += f"--- Source: {r['source']} | Topic: {r['topic']} ---\n"
            intel_dump += f"{r['content']}\n\n"
            
        prompt = f"Synthesize the following information into a highly concise, punchy 5-bullet-point morning brief for the user. Do not use markdown bolding/italics as it breaks the messaging client. Be direct and executive.\n\n{intel_dump}"
        temp_messages = [
            {"role": "system", "content": "You are an Executive Assistant giving a morning briefing."},
            {"role": "user", "content": prompt}
        ]
        
        temp_prompt_str = tokenizer.apply_chat_template(
            temp_messages, tokenize=False, add_generation_prompt=True
        )

        response = generate(
            model,
            tokenizer,
            prompt=temp_prompt_str,
            verbose=False,
            max_tokens=800,
        )
        
        brief_text = response.strip()
        
        placeholders = ",".join(["?"] * len(row_ids))
        cursor.execute(f"UPDATE raw_intelligence SET processed = 1 WHERE id IN ({placeholders})", tuple(row_ids))
        conn.commit()
        conn.close()
        
        injection = f"SYSTEM NOTIFICATION: I have prepared the Morning Brief based on background intelligence gathering. Please send the following exact text to the user immediately as a new message:\n\n{brief_text}"
        
        inbox_queue.put({
            "source": "proactive",
            "text": injection,
            "chat_id": chat_id,
        })
        
        logger.info("[Scheduled: Brief] Morning Brief generated and pushed to inbox.")

    except Exception as e:
        logger.error(f"[Scheduled: Brief] Morning brief generation failed: {e}")
