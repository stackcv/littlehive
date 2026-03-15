"""
Proactive Anticipation Engine
Tracks user actions, mines behavioral patterns, and predicts future needs.
All pattern detection is algorithmic (no LLM required).
"""

import json
import sqlite3
import hashlib
import logging
from datetime import datetime, timedelta
from collections import defaultdict

from littlehive.agent.paths import DB_PATH

logger = logging.getLogger(__name__)

TOOL_CATEGORY_MAP = {
    "search_emails": "email",
    "read_full_email": "email",
    "send_email": "email",
    "reply_to_email": "email",
    "manage_email": "email",
    "get_events": "calendar",
    "create_event": "calendar",
    "update_event": "calendar",
    "delete_event": "calendar",
    "add_bill": "finance",
    "list_bills": "finance",
    "mark_bill_paid": "finance",
    "set_reminder": "reminders",
    "get_pending_reminders": "reminders",
    "complete_reminder": "reminders",
    "lookup_stakeholder": "contacts",
    "add_stakeholder": "contacts",
    "update_stakeholder": "contacts",
    "web_search": "web",
    "fetch_webpage": "web",
    "get_tasks": "tasks",
    "create_task": "tasks",
    "update_task": "tasks",
    "delete_task": "tasks",
    "save_core_fact": "memory",
    "search_past_conversations": "memory",
    "delete_core_fact": "memory",
    "exec_command": "shell",
    "read_file": "shell",
    "write_file": "shell",
    "list_directory": "shell",
    "github_list_issues": "github",
    "github_create_issue": "github",
    "github_update_issue": "github",
    "github_add_comment": "github",
    "register_api": "custom_api",
    "call_api": "custom_api",
    "list_apis": "custom_api",
    "announce": "shell",
    "send_channel_message": "messaging",
}

CATEGORY_VERBS = {
    "email": "check your email",
    "calendar": "review your calendar",
    "finance": "review your bills/finances",
    "reminders": "manage your reminders",
    "contacts": "look up contacts",
    "web": "search the web",
    "tasks": "check your tasks",
    "memory": "review memories",
    "shell": "run shell commands",
    "github": "check GitHub issues",
    "custom_api": "call custom APIs",
    "messaging": "send messages",
}

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

ENTITY_EXTRACT_KEYS = {
    "to": "email_recipient",
    "email": "email_address",
    "name": "person_name",
    "vendor": "vendor_name",
    "query": "search_query",
    "task": "reminder_text",
    "title": "task_title",
    "repo": "github_repo",
    "summary": "event_summary",
}


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _extract_entities(tool_name, tool_args):
    """Pull identifiable entities from tool arguments."""
    entities = []
    if not isinstance(tool_args, dict):
        return entities
    for key, label in ENTITY_EXTRACT_KEYS.items():
        val = tool_args.get(key)
        if val and isinstance(val, str) and len(val) < 200:
            entities.append({"type": label, "value": val})
    return entities


def _make_turn_id(user_input_snippet):
    """Hash-based turn identifier for grouping tool calls within a single turn."""
    ts = datetime.now().strftime("%Y%m%d%H%M")
    raw = f"{ts}:{user_input_snippet[:50]}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Layer 1: Action Logging
# ---------------------------------------------------------------------------

def log_action(tool_name, tool_args, source="web", turn_id=None, session_position=0):
    """Record a single tool invocation. Called from start_agent.py after dispatch_tool()."""
    try:
        now = datetime.now()
        category = TOOL_CATEGORY_MAP.get(tool_name, "other")
        entities = _extract_entities(tool_name, tool_args)

        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO user_actions 
               (hour, minute, day_of_week, day_of_month, tool_name, 
                action_category, entities, turn_id, session_position, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now.hour,
                now.minute,
                now.weekday(),
                now.day,
                tool_name,
                category,
                json.dumps(entities),
                turn_id or "",
                session_position,
                source,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"[Anticipation] Action logging failed: {e}")


# ---------------------------------------------------------------------------
# Layer 2: Pattern Mining (nightly job)
# ---------------------------------------------------------------------------

def _compute_confidence(frequency, opportunities, days_since_last):
    """Score a pattern based on how often it fires vs how often it could fire, decayed by recency."""
    if opportunities <= 0:
        return 0.0
    base = frequency / opportunities
    recency_decay = max(0.0, 1.0 - (days_since_last / 45.0))
    return round(base * recency_decay, 4)


def _upsert_pattern(conn, pattern_type, pattern_key, description, frequency,
                    opportunities, confidence, predicted_action, trigger_conditions,
                    last_matched):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, user_confirmed FROM action_patterns WHERE pattern_key = ?",
        (pattern_key,),
    )
    existing = cursor.fetchone()

    if existing:
        cursor.execute(
            """UPDATE action_patterns
               SET frequency = ?, total_opportunities = ?, confidence = ?,
                   description = ?, predicted_action = ?, trigger_conditions = ?,
                   last_matched = ?
               WHERE pattern_key = ?""",
            (
                frequency, opportunities, confidence, description,
                json.dumps(predicted_action), json.dumps(trigger_conditions),
                last_matched, pattern_key,
            ),
        )
    else:
        cursor.execute(
            """INSERT INTO action_patterns
               (pattern_type, pattern_key, description, frequency, total_opportunities,
                confidence, predicted_action, trigger_conditions, last_matched)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pattern_type, pattern_key, description, frequency, opportunities,
                confidence, json.dumps(predicted_action), json.dumps(trigger_conditions),
                last_matched,
            ),
        )


def mine_temporal_patterns(conn, lookback_days=30, min_frequency=3):
    """Find recurring (day_of_week, hour_bucket, category) patterns."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT day_of_week, 
                  CASE WHEN hour < 6  THEN 'early_morning'
                       WHEN hour < 9  THEN 'morning'
                       WHEN hour < 12 THEN 'late_morning'
                       WHEN hour < 14 THEN 'afternoon'
                       WHEN hour < 17 THEN 'late_afternoon'
                       WHEN hour < 20 THEN 'evening'
                       ELSE 'night' END AS hour_bucket,
                  hour,
                  action_category,
                  COUNT(*) AS freq,
                  MAX(timestamp) AS last_seen
           FROM user_actions
           WHERE timestamp >= datetime('now', 'localtime', ?)
             AND action_category != 'other'
           GROUP BY day_of_week, hour_bucket, action_category
           HAVING freq >= ?""",
        (f"-{lookback_days} days", min_frequency),
    )
    rows = cursor.fetchall()

    # Count total opportunities per (dow, hour_bucket) — how many such time slots existed
    weeks_in_window = max(lookback_days // 7, 1)

    count = 0
    for row in rows:
        dow = row["day_of_week"]
        bucket = row["hour_bucket"]
        cat = row["action_category"]
        freq = row["freq"]
        last_seen = row["last_seen"]
        representative_hour = row["hour"]

        days_since = 0
        if last_seen:
            try:
                last_dt = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
                days_since = (datetime.now() - last_dt).days
            except Exception:
                pass

        opportunities = weeks_in_window
        confidence = _compute_confidence(freq, opportunities, days_since)

        verb = CATEGORY_VERBS.get(cat, f"use {cat} tools")
        day_name = DAY_NAMES[dow]
        desc = f"You usually {verb} on {day_name} {bucket.replace('_', ' ')}s"

        pattern_key = f"temporal:dow={dow}:bucket={bucket}:cat={cat}"

        _upsert_pattern(
            conn,
            pattern_type="temporal",
            pattern_key=pattern_key,
            description=desc,
            frequency=freq,
            opportunities=opportunities,
            confidence=confidence,
            predicted_action={"action_category": cat, "suggestion": desc},
            trigger_conditions={"day_of_week": dow, "hour_bucket": bucket, "hour": representative_hour},
            last_matched=last_seen,
        )
        count += 1

    return count


def mine_sequential_patterns(conn, lookback_days=30, min_frequency=3):
    """Find tool A -> tool B chains that recur across turns."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT a.action_category AS cat_a, b.action_category AS cat_b,
                  COUNT(*) AS freq, MAX(b.timestamp) AS last_seen
           FROM user_actions a
           JOIN user_actions b
             ON a.turn_id = b.turn_id
            AND a.turn_id != ''
            AND b.session_position = a.session_position + 1
           WHERE a.timestamp >= datetime('now', 'localtime', ?)
             AND a.action_category != b.action_category
             AND a.action_category != 'other'
             AND b.action_category != 'other'
           GROUP BY a.action_category, b.action_category
           HAVING freq >= ?""",
        (f"-{lookback_days} days", min_frequency),
    )
    rows = cursor.fetchall()

    # Total turns as opportunity denominator
    cursor.execute(
        "SELECT COUNT(DISTINCT turn_id) FROM user_actions WHERE timestamp >= datetime('now', 'localtime', ?) AND turn_id != ''",
        (f"-{lookback_days} days",),
    )
    total_turns = cursor.fetchone()[0] or 1

    count = 0
    for row in rows:
        cat_a = row["cat_a"]
        cat_b = row["cat_b"]
        freq = row["freq"]
        last_seen = row["last_seen"]

        days_since = 0
        if last_seen:
            try:
                last_dt = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
                days_since = (datetime.now() - last_dt).days
            except Exception:
                pass

        confidence = _compute_confidence(freq, total_turns, days_since)

        verb_a = CATEGORY_VERBS.get(cat_a, cat_a)
        verb_b = CATEGORY_VERBS.get(cat_b, cat_b)
        desc = f"After you {verb_a}, you often {verb_b}"

        pattern_key = f"sequential:{cat_a}->{cat_b}"

        _upsert_pattern(
            conn,
            pattern_type="sequential",
            pattern_key=pattern_key,
            description=desc,
            frequency=freq,
            opportunities=total_turns,
            confidence=confidence,
            predicted_action={"action_category": cat_b, "preceding_category": cat_a, "suggestion": desc},
            trigger_conditions={"preceding_category": cat_a},
            last_matched=last_seen,
        )
        count += 1

    return count


def mine_entity_temporal_patterns(conn, lookback_days=30, min_frequency=2):
    """Find recurring interactions with specific entities on specific days."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT day_of_week, action_category, entities,
                  COUNT(*) AS freq, MAX(timestamp) AS last_seen
           FROM user_actions
           WHERE timestamp >= datetime('now', 'localtime', ?)
             AND entities != '[]'
             AND action_category IN ('email', 'contacts', 'calendar')
           GROUP BY day_of_week, action_category, entities
           HAVING freq >= ?""",
        (f"-{lookback_days} days", min_frequency),
    )
    rows = cursor.fetchall()

    weeks_in_window = max(lookback_days // 7, 1)

    count = 0
    for row in rows:
        dow = row["day_of_week"]
        cat = row["action_category"]
        entities_str = row["entities"]
        freq = row["freq"]
        last_seen = row["last_seen"]

        try:
            entities_list = json.loads(entities_str)
        except Exception:
            continue

        if not entities_list:
            continue

        primary_entity = entities_list[0].get("value", "unknown")
        entity_type = entities_list[0].get("type", "unknown")

        days_since = 0
        if last_seen:
            try:
                last_dt = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
                days_since = (datetime.now() - last_dt).days
            except Exception:
                pass

        confidence = _compute_confidence(freq, weeks_in_window, days_since)

        day_name = DAY_NAMES[dow]
        verb = CATEGORY_VERBS.get(cat, cat)
        # Truncate entity for description readability
        entity_display = primary_entity[:40]
        desc = f"You often interact with '{entity_display}' ({cat}) on {day_name}s"

        pattern_key = f"entity:dow={dow}:cat={cat}:entity={hashlib.md5(primary_entity.encode()).hexdigest()[:8]}"

        _upsert_pattern(
            conn,
            pattern_type="entity_temporal",
            pattern_key=pattern_key,
            description=desc,
            frequency=freq,
            opportunities=weeks_in_window,
            confidence=confidence,
            predicted_action={
                "action_category": cat,
                "entity": primary_entity,
                "entity_type": entity_type,
                "suggestion": desc,
            },
            trigger_conditions={"day_of_week": dow, "entity": primary_entity},
            last_matched=last_seen,
        )
        count += 1

    return count


def mine_periodic_patterns(conn, lookback_days=90, min_months=2):
    """Find monthly recurring actions (e.g., bill review on the 1st)."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT day_of_month, action_category,
                  COUNT(*) AS freq,
                  COUNT(DISTINCT strftime('%%Y-%%m', timestamp)) AS months,
                  MAX(timestamp) AS last_seen
           FROM user_actions
           WHERE timestamp >= datetime('now', 'localtime', ?)
             AND action_category IN ('finance', 'email', 'tasks', 'calendar')
           GROUP BY day_of_month, action_category
           HAVING months >= ?""",
        (f"-{lookback_days} days", min_months),
    )
    rows = cursor.fetchall()

    months_in_window = max(lookback_days // 30, 1)

    count = 0
    for row in rows:
        dom = row["day_of_month"]
        cat = row["action_category"]
        freq = row["freq"]
        months = row["months"]
        last_seen = row["last_seen"]

        days_since = 0
        if last_seen:
            try:
                last_dt = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
                days_since = (datetime.now() - last_dt).days
            except Exception:
                pass

        confidence = _compute_confidence(months, months_in_window, days_since)

        verb = CATEGORY_VERBS.get(cat, cat)
        suffix = "th"
        if dom in (1, 21, 31):
            suffix = "st"
        elif dom in (2, 22):
            suffix = "nd"
        elif dom in (3, 23):
            suffix = "rd"
        desc = f"You usually {verb} around the {dom}{suffix} of each month"

        pattern_key = f"periodic:dom={dom}:cat={cat}"

        _upsert_pattern(
            conn,
            pattern_type="periodic",
            pattern_key=pattern_key,
            description=desc,
            frequency=freq,
            opportunities=months_in_window,
            confidence=confidence,
            predicted_action={"action_category": cat, "suggestion": desc},
            trigger_conditions={"day_of_month": dom},
            last_matched=last_seen,
        )
        count += 1

    return count


def run_pattern_mining(lookback_days=30, min_frequency=3):
    """Top-level mining entry point. Called nightly by scheduler."""
    try:
        conn = _get_db()

        t_count = mine_temporal_patterns(conn, lookback_days, min_frequency)
        s_count = mine_sequential_patterns(conn, lookback_days, min_frequency)
        e_count = mine_entity_temporal_patterns(conn, lookback_days, min_frequency=2)
        p_count = mine_periodic_patterns(conn, lookback_days=90, min_months=2)

        # Prune dead patterns: confidence near zero, not user-confirmed, not seen in 45+ days
        cursor = conn.cursor()
        cursor.execute(
            """DELETE FROM action_patterns
               WHERE confidence < 0.05
                 AND user_confirmed = 0
                 AND last_matched < datetime('now', 'localtime', '-45 days')"""
        )
        pruned = cursor.rowcount

        conn.commit()
        conn.close()

        logger.info(
            f"[Anticipation] Pattern mining complete: "
            f"temporal={t_count}, sequential={s_count}, entity={e_count}, "
            f"periodic={p_count}, pruned={pruned}"
        )
    except Exception as e:
        logger.error(f"[Anticipation] Pattern mining failed: {e}")


# ---------------------------------------------------------------------------
# Layer 3: Prediction & Matching
# ---------------------------------------------------------------------------

HOUR_BUCKET_RANGES = {
    "early_morning": (0, 6),
    "morning": (6, 9),
    "late_morning": (9, 12),
    "afternoon": (12, 14),
    "late_afternoon": (14, 17),
    "evening": (17, 20),
    "night": (20, 24),
}


def _current_hour_bucket():
    h = datetime.now().hour
    for bucket, (lo, hi) in HOUR_BUCKET_RANGES.items():
        if lo <= h < hi:
            return bucket
    return "night"


def get_matching_predictions(min_confidence=0.5, cooldown_hours=4):
    """Return patterns whose trigger conditions match right now, above confidence threshold."""
    now = datetime.now()
    current_dow = now.weekday()
    current_hour = now.hour
    current_dom = now.day
    current_bucket = _current_hour_bucket()

    conn = _get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM action_patterns WHERE is_active = 1 AND confidence >= ?",
        (min_confidence,),
    )
    patterns = cursor.fetchall()

    matches = []
    for p in patterns:
        try:
            trigger = json.loads(p["trigger_conditions"]) if p["trigger_conditions"] else {}
        except Exception:
            continue

        matched = False
        ptype = p["pattern_type"]

        if ptype == "temporal":
            if trigger.get("day_of_week") == current_dow and trigger.get("hour_bucket") == current_bucket:
                matched = True

        elif ptype == "periodic":
            trig_dom = trigger.get("day_of_month")
            if trig_dom and abs(current_dom - trig_dom) <= 1:
                matched = True

        elif ptype == "entity_temporal":
            if trigger.get("day_of_week") == current_dow:
                matched = True

        # Sequential patterns are checked separately via check_sequential_prediction()

        if not matched:
            continue

        # Cooldown: skip if we suggested this pattern recently
        cursor.execute(
            """SELECT COUNT(*) FROM anticipation_log
               WHERE pattern_id = ? AND suggested_at >= datetime('now', 'localtime', ?)""",
            (p["id"], f"-{cooldown_hours} hours"),
        )
        if cursor.fetchone()[0] > 0:
            continue

        # Skip if user already performed this action category today
        try:
            predicted = json.loads(p["predicted_action"]) if p["predicted_action"] else {}
        except Exception:
            predicted = {}

        pred_cat = predicted.get("action_category")
        if pred_cat:
            cursor.execute(
                """SELECT COUNT(*) FROM user_actions
                   WHERE action_category = ?
                     AND date(timestamp) = date('now', 'localtime')""",
                (pred_cat,),
            )
            if cursor.fetchone()[0] > 0:
                continue

        matches.append({
            "id": p["id"],
            "pattern_type": p["pattern_type"],
            "description": p["description"],
            "confidence": p["confidence"],
            "predicted_action": predicted,
            "suggestion_text": predicted.get("suggestion", p["description"]),
        })

    conn.close()
    return matches


def check_sequential_prediction(just_completed_category, min_confidence=0.5):
    """After a tool call completes, check if a sequential pattern predicts a follow-up."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT * FROM action_patterns
           WHERE pattern_type = 'sequential'
             AND is_active = 1
             AND confidence >= ?""",
        (min_confidence,),
    )
    patterns = cursor.fetchall()
    conn.close()

    for p in patterns:
        try:
            trigger = json.loads(p["trigger_conditions"]) if p["trigger_conditions"] else {}
        except Exception:
            continue
        if trigger.get("preceding_category") == just_completed_category:
            predicted = json.loads(p["predicted_action"]) if p["predicted_action"] else {}
            return {
                "id": p["id"],
                "description": p["description"],
                "confidence": p["confidence"],
                "suggestion_text": predicted.get("suggestion", p["description"]),
                "predicted_category": predicted.get("action_category"),
            }
    return None


def log_anticipation(pattern_id, suggestion_text, confidence):
    """Record that we surfaced a suggestion."""
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO anticipation_log (pattern_id, suggestion_text, confidence)
               VALUES (?, ?, ?)""",
            (pattern_id, suggestion_text, confidence),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"[Anticipation] Failed to log anticipation: {e}")


# ---------------------------------------------------------------------------
# Layer 4: Feedback Loop
# ---------------------------------------------------------------------------

def process_anticipation_feedback():
    """Check pending anticipations and mark as accepted/ignored based on user behavior."""
    try:
        conn = _get_db()
        cursor = conn.cursor()

        # Get pending anticipations older than 1 hour
        cursor.execute(
            """SELECT al.id, al.pattern_id, al.suggested_at, ap.predicted_action
               FROM anticipation_log al
               JOIN action_patterns ap ON al.pattern_id = ap.id
               WHERE al.user_response = 'pending'
                 AND al.suggested_at < datetime('now', 'localtime', '-1 hour')"""
        )
        pending = cursor.fetchall()

        for row in pending:
            ant_id = row["id"]
            pattern_id = row["pattern_id"]
            suggested_at = row["suggested_at"]

            try:
                predicted = json.loads(row["predicted_action"]) if row["predicted_action"] else {}
            except Exception:
                predicted = {}

            pred_cat = predicted.get("action_category")
            accepted = False

            if pred_cat:
                # Check if user performed the predicted action after the suggestion
                cursor.execute(
                    """SELECT COUNT(*) FROM user_actions
                       WHERE action_category = ?
                         AND timestamp > ?
                         AND timestamp < datetime(?, '+4 hours')""",
                    (pred_cat, suggested_at, suggested_at),
                )
                if cursor.fetchone()[0] > 0:
                    accepted = True

            if accepted:
                cursor.execute(
                    "UPDATE anticipation_log SET user_response = 'accepted' WHERE id = ?",
                    (ant_id,),
                )
                # Boost pattern confidence slightly
                cursor.execute(
                    """UPDATE action_patterns
                       SET confidence = MIN(1.0, confidence + 0.03)
                       WHERE id = ?""",
                    (pattern_id,),
                )
            else:
                hours_elapsed = 0
                try:
                    sug_dt = datetime.strptime(suggested_at, "%Y-%m-%d %H:%M:%S")
                    hours_elapsed = (datetime.now() - sug_dt).total_seconds() / 3600
                except Exception:
                    hours_elapsed = 5

                if hours_elapsed >= 4:
                    cursor.execute(
                        "UPDATE anticipation_log SET user_response = 'ignored' WHERE id = ?",
                        (ant_id,),
                    )
                    cursor.execute(
                        """UPDATE action_patterns
                           SET confidence = MAX(0.0, confidence - 0.02)
                           WHERE id = ? AND user_confirmed = 0""",
                        (pattern_id,),
                    )

        conn.commit()
        conn.close()

        if pending:
            logger.info(f"[Anticipation] Processed feedback for {len(pending)} anticipations")

    except Exception as e:
        logger.error(f"[Anticipation] Feedback processing failed: {e}")


# ---------------------------------------------------------------------------
# Stats / Read-only queries for API
# ---------------------------------------------------------------------------

def get_all_patterns():
    """Return all action patterns for API consumption."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, pattern_type, pattern_key, description, frequency,
                  total_opportunities, confidence, last_matched, first_seen,
                  predicted_action, trigger_conditions, is_active, user_confirmed
           FROM action_patterns
           ORDER BY confidence DESC"""
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_anticipation_history(limit=50):
    """Return recent anticipation suggestions and their outcomes."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT al.id, al.suggestion_text, al.confidence, al.suggested_at,
                  al.user_response, ap.pattern_type, ap.description AS pattern_description
           FROM anticipation_log al
           LEFT JOIN action_patterns ap ON al.pattern_id = ap.id
           ORDER BY al.suggested_at DESC
           LIMIT ?""",
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_anticipation_stats():
    """Return summary stats about the anticipation engine."""
    conn = _get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM user_actions")
    total_actions = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM action_patterns WHERE is_active = 1")
    active_patterns = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM anticipation_log")
    total_suggestions = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM anticipation_log WHERE user_response = 'accepted'"
    )
    accepted = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM anticipation_log WHERE user_response = 'ignored'"
    )
    ignored = cursor.fetchone()[0]

    hit_rate = round(accepted / max(accepted + ignored, 1) * 100, 1)

    conn.close()
    return {
        "total_actions_logged": total_actions,
        "active_patterns": active_patterns,
        "total_suggestions": total_suggestions,
        "accepted": accepted,
        "ignored": ignored,
        "hit_rate_pct": hit_rate,
    }
