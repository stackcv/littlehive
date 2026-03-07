import sqlite3
import os
from datetime import datetime
import json

from littlehive.agent.paths import DB_PATH


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_memory_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _get_db()
    cursor = conn.cursor()
    # Core memory for life facts
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS core_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_text TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Archival memory for chat history (FTS5 for fast search)
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chat_archive USING fts5(
            role,
            content,
            timestamp UNINDEXED
        )
    """)
    conn.commit()
    conn.close()


# Initialize DB on import
init_memory_db()

_encoder_model = None


def _get_encoder_model():
    global _encoder_model
    if _encoder_model is None:
        try:
            from sentence_transformers import SentenceTransformer

            _encoder_model = SentenceTransformer("all-MiniLM-L6-v2")
        except ImportError:
            pass
    return _encoder_model


def save_core_fact(fact: str) -> str:
    """
    Saves an important fact about the user or their life into core memory.
    These facts are guaranteed to be remembered in all future conversations.
    """
    conn = _get_db()
    cursor = conn.cursor()

    # Dedup logic
    cursor.execute("SELECT id, fact_text FROM core_memory")
    existing_facts = cursor.fetchall()

    if existing_facts:
        model = _get_encoder_model()
        if model:
            from sklearn.metrics.pairwise import cosine_similarity

            existing_texts = [row["fact_text"] for row in existing_facts]

            embeddings = model.encode([fact] + existing_texts)
            sims = cosine_similarity(embeddings[0:1], embeddings[1:])[0]

            max_sim_idx = sims.argmax()
            max_sim = sims[max_sim_idx]

            if max_sim > 0.52:
                similar_fact = existing_texts[max_sim_idx]
                similar_id = existing_facts[max_sim_idx]["id"]
                conn.close()
                return json.dumps(
                    {
                        "status": "duplicate_found",
                        "message": f"Fact not saved. Found a highly similar existing fact (ID: {similar_id}): '{similar_fact}'. Delete it first if you wish to update.",
                    }
                )

    cursor.execute("INSERT INTO core_memory (fact_text) VALUES (?)", (fact,))
    conn.commit()
    conn.close()
    return json.dumps(
        {"status": "success", "message": f"Fact saved to core memory: {fact}"}
    )


def delete_core_fact(query: str) -> str:
    """
    Deletes facts from core memory that match the query keyword.
    """
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, fact_text FROM core_memory WHERE fact_text LIKE ?", (f"%{query}%",)
    )
    results = cursor.fetchall()

    if not results:
        conn.close()
        return json.dumps(
            {
                "status": "not_found",
                "message": f"No facts found in memory matching: '{query}'",
            }
        )

    ids_to_delete = [row["id"] for row in results]
    deleted_facts = [row["fact_text"] for row in results]

    placeholders = ",".join("?" for _ in ids_to_delete)
    cursor.execute(
        f"DELETE FROM core_memory WHERE id IN ({placeholders})", ids_to_delete
    )
    conn.commit()
    conn.close()

    return json.dumps(
        {
            "status": "success",
            "message": f"Deleted the following facts: {deleted_facts}",
        }
    )


def search_past_conversations(query: str) -> str:
    """
    Searches the archival chat history for past conversations.
    Useful when the user asks about something discussed previously that is no longer in the immediate context.
    """
    conn = _get_db()
    cursor = conn.cursor()
    # Ensure query is properly formatted for FTS5 (basic quoting)
    # This escapes double quotes and wraps the query in double quotes to prevent syntax errors
    safe_query = '"{}"'.format(query.replace('"', '""'))
    try:
        cursor.execute(
            """
            SELECT role, content, timestamp 
            FROM chat_archive 
            WHERE chat_archive MATCH ? 
            ORDER BY rank 
            LIMIT 10
        """,
            (safe_query,),
        )
        results = cursor.fetchall()
    except sqlite3.OperationalError as e:
        conn.close()
        return json.dumps({"error": f"Search failed: {str(e)}"})

    conn.close()

    if not results:
        return json.dumps(
            {"results": [], "message": "No relevant past conversations found."}
        )

    formatted_results = [
        {"role": row["role"], "content": row["content"], "timestamp": row["timestamp"]}
        for row in results
    ]
    return json.dumps({"results": formatted_results})


def get_all_core_facts() -> list:
    """Retrieves all core facts to be injected into the system prompt."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT fact_text FROM core_memory ORDER BY timestamp ASC")
    results = [row["fact_text"] for row in cursor.fetchall()]
    conn.close()
    return results


def archive_messages(messages: list):
    """Saves a list of compacted messages to the chat archive."""
    conn = _get_db()
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # Only archive non-empty string content, don't archive tool calls JSON structure
        if isinstance(content, str) and content.strip():
            cursor.execute(
                "INSERT INTO chat_archive (role, content, timestamp) VALUES (?, ?, ?)",
                (role, content, timestamp),
            )
    conn.commit()
    conn.close()
