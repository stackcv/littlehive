"""
Self-Healing Engine
Classifies tool errors, retries transient failures, manages circuit breakers,
logs failure patterns, and enriches error messages for the LLM.

Inspired by:
- Reflexion (Shinn et al., NeurIPS 2023) — verbal self-reflection as semantic gradient
- PALADIN — explicit error taxonomy for recovery
- Production patterns — retry + classify + circuit breaker + fallback
"""

import json
import time
import random
import hashlib
import sqlite3
import logging
import threading
from datetime import datetime, timedelta

from littlehive.agent.paths import DB_PATH

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error Taxonomy
# ---------------------------------------------------------------------------

ERROR_TAXONOMY = {
    "transient": {
        "patterns": [
            "429", "rate limit", "rate_limit", "timeout", "timed out",
            "503", "502", "temporarily unavailable", "connection reset",
            "ECONNREFUSED", "quota exceeded", "try again", "too many requests",
            "service unavailable", "connection refused", "network",
        ],
        "strategy": "retry_with_backoff",
        "max_retries": 2,
    },
    "auth": {
        "patterns": [
            "401", "403", "unauthorized", "token expired", "invalid credentials",
            "access denied", "authentication", "forbidden", "not authorized",
            "credentials", "oauth", "refresh token",
        ],
        "strategy": "fail_fast_with_guidance",
    },
    "not_found": {
        "patterns": [
            "404", "not found", "no results", "does not exist", "no matching",
            "no emails found", "no events found", "no reminders",
            "no bills", "0 results",
        ],
        "strategy": "enrich_and_return",
    },
    "validation": {
        "patterns": [
            "invalid", "required field", "missing parameter", "bad request",
            "cannot set a reminder in the past", "malformed", "required",
            "must be", "expected", "wrong format", "type error",
            "missing required", "nothing to update",
        ],
        "strategy": "enrich_and_return",
    },
    "permanent": {
        "patterns": [
            "500", "internal server error", "unrecoverable",
            "not implemented", "deprecated",
        ],
        "strategy": "fail_with_context",
    },
}

# Map tools to the external service they depend on.
# Tools not listed default to "local" (SQLite-backed, never trips breaker).
TOOL_SERVICE_MAP = {
    "search_emails": "gmail",
    "read_full_email": "gmail",
    "send_email": "gmail",
    "reply_to_email": "gmail",
    "manage_email": "gmail",
    "get_events": "gcalendar",
    "create_event": "gcalendar",
    "update_event": "gcalendar",
    "delete_event": "gcalendar",
    "web_search": "ddgs",
    "fetch_webpage": "web",
    "call_api": "custom_api",
    "github_list_issues": "github",
    "github_create_issue": "github",
    "github_update_issue": "github",
    "github_add_comment": "github",
    "get_task_lists": "google_tasks",
}

# Alternative suggestions when a tool's primary approach fails
TOOL_ALTERNATIVES = {
    "web_search": "Try rephrasing the search query or using fetch_webpage with a direct URL.",
    "fetch_webpage": "The page may be down. Try web_search for cached or alternative sources.",
    "search_emails": "Try broadening the search query or checking with different keywords.",
    "read_full_email": "The email may have been deleted. Try search_emails to verify it exists.",
    "call_api": "The custom API may be down. Try web_search as a fallback.",
    "get_events": "Calendar service may be temporarily unavailable. Try again shortly.",
    "github_list_issues": "GitHub may be rate-limiting. Try with fewer results or wait.",
}


# ---------------------------------------------------------------------------
# Circuit Breaker (per service)
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """
    Three-state circuit breaker: closed -> open -> half_open -> closed.
    Prevents hammering a failing external service.
    """

    def __init__(self, service_name, failure_threshold=5, window_seconds=120,
                 cooldown_seconds=60):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self._failures = []
        self._state = "closed"
        self._opened_at = None
        self._lock = threading.Lock()

    def is_open(self):
        with self._lock:
            if self._state == "closed":
                return False
            if self._state == "open":
                elapsed = (datetime.now() - self._opened_at).total_seconds()
                if elapsed >= self.cooldown_seconds:
                    self._state = "half_open"
                    logger.info(f"[CircuitBreaker] {self.service_name}: open -> half_open (probing)")
                    return False
                return True
            # half_open: allow one request through
            return False

    def record_success(self):
        with self._lock:
            if self._state == "half_open":
                self._state = "closed"
                self._failures.clear()
                logger.info(f"[CircuitBreaker] {self.service_name}: half_open -> closed (recovered)")
            # Prune old failures from window
            cutoff = datetime.now() - timedelta(seconds=self.window_seconds)
            self._failures = [t for t in self._failures if t > cutoff]

    def record_failure(self):
        with self._lock:
            now = datetime.now()
            self._failures.append(now)
            # Prune outside window
            cutoff = now - timedelta(seconds=self.window_seconds)
            self._failures = [t for t in self._failures if t > cutoff]

            if self._state == "half_open":
                self._state = "open"
                self._opened_at = now
                logger.warning(f"[CircuitBreaker] {self.service_name}: half_open -> open (probe failed)")
            elif len(self._failures) >= self.failure_threshold:
                self._state = "open"
                self._opened_at = now
                logger.warning(
                    f"[CircuitBreaker] {self.service_name}: closed -> open "
                    f"({len(self._failures)} failures in {self.window_seconds}s)"
                )

    @property
    def state(self):
        with self._lock:
            return self._state


# One breaker per known external service
_circuit_breakers = {}
_breaker_lock = threading.Lock()


def _get_breaker(service_name):
    with _breaker_lock:
        if service_name not in _circuit_breakers:
            _circuit_breakers[service_name] = CircuitBreaker(service_name)
        return _circuit_breakers[service_name]


# ---------------------------------------------------------------------------
# Error Classifier
# ---------------------------------------------------------------------------

def classify_error(tool_result):
    """
    Inspect a tool result string. If it contains an error, classify it.
    Returns None for success, or dict with type/message/strategy.
    """
    if not isinstance(tool_result, str):
        return None

    # Try to parse as JSON and look for "error" key
    error_text = None
    try:
        parsed = json.loads(tool_result)
        if isinstance(parsed, dict):
            err = parsed.get("error")
            if err:
                error_text = str(err)
    except (json.JSONDecodeError, TypeError):
        pass

    if not error_text:
        return None

    error_lower = error_text.lower()

    for error_type, spec in ERROR_TAXONOMY.items():
        for pattern in spec["patterns"]:
            if pattern.lower() in error_lower:
                return {
                    "type": error_type,
                    "message": error_text,
                    "strategy": spec["strategy"],
                    "max_retries": spec.get("max_retries", 0),
                }

    # Unclassified error — default to permanent (don't retry unknowns)
    return {
        "type": "unknown",
        "message": error_text,
        "strategy": "enrich_and_return",
        "max_retries": 0,
    }


# ---------------------------------------------------------------------------
# Failure Memory
# ---------------------------------------------------------------------------

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _args_hash(tool_args):
    """Deterministic hash of tool arguments for dedup."""
    try:
        canonical = json.dumps(tool_args, sort_keys=True, default=str)
    except Exception:
        canonical = str(tool_args)
    return hashlib.md5(canonical.encode()).hexdigest()[:16]


def _error_signature(error_type, error_message):
    """Normalized signature for grouping similar errors."""
    # Strip numbers and IDs to group similar errors
    import re
    normalized = re.sub(r'\d+', 'N', error_message[:100]).lower().strip()
    return f"{error_type}:{hashlib.md5(normalized.encode()).hexdigest()[:12]}"


def log_failure(tool_name, tool_args, error_info, attempts=1):
    """Record a tool failure for pattern learning."""
    try:
        conn = _get_db()
        cursor = conn.cursor()
        sig = _error_signature(error_info["type"], error_info["message"])
        ah = _args_hash(tool_args)

        cursor.execute(
            "SELECT id, occurrence_count FROM tool_failure_memory WHERE tool_name = ? AND error_signature = ?",
            (tool_name, sig),
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                """UPDATE tool_failure_memory
                   SET occurrence_count = occurrence_count + 1,
                       last_seen = datetime('now', 'localtime'),
                       is_recurring = CASE WHEN occurrence_count >= 2 THEN 1 ELSE 0 END
                   WHERE id = ?""",
                (existing["id"],),
            )
        else:
            cursor.execute(
                """INSERT INTO tool_failure_memory
                   (tool_name, error_type, error_signature, args_hash, occurrence_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (tool_name, error_info["type"], sig, ah, 1),
            )

        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"[SelfHealing] Failed to log failure: {e}")


def is_known_recurring_failure(tool_name, tool_args):
    """Check if this exact tool+args combination is a known recurring failure."""
    try:
        conn = _get_db()
        cursor = conn.cursor()
        ah = _args_hash(tool_args)
        cursor.execute(
            """SELECT occurrence_count FROM tool_failure_memory
               WHERE tool_name = ? AND args_hash = ? AND is_recurring = 1
                 AND last_seen >= datetime('now', 'localtime', '-1 hour')""",
            (tool_name, ah),
        )
        row = cursor.fetchone()
        conn.close()
        if row and row["occurrence_count"] >= 3:
            return True
    except Exception:
        pass
    return False


def log_resolution(tool_name, error_signature, resolution_text):
    """Record what worked when recovering from a failure."""
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE tool_failure_memory SET resolution = ?
               WHERE tool_name = ? AND error_signature = ?""",
            (resolution_text, tool_name, error_signature),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Error Enrichment for LLM
# ---------------------------------------------------------------------------

def enrich_error_for_llm(tool_name, raw_result, error_info, attempts=1):
    """Transform a raw tool error into an LLM-actionable enriched response."""
    enriched = {
        "error": error_info["message"],
        "error_type": error_info["type"],
        "tool": tool_name,
        "attempts": attempts,
    }

    etype = error_info["type"]

    if etype == "transient":
        enriched["system_note"] = (
            f"The {tool_name} service is temporarily unavailable after {attempts} "
            f"automatic retry attempt(s). Inform the user about the temporary issue "
            f"and offer to try again later."
        )

    elif etype == "auth":
        enriched["system_note"] = (
            f"Authentication failed for {tool_name}. Do NOT retry this tool. "
            f"Ask the user to check their credentials or re-authenticate in Settings."
        )

    elif etype == "not_found":
        alt = TOOL_ALTERNATIVES.get(tool_name, "")
        suggestion = f" {alt}" if alt else ""
        enriched["system_note"] = (
            f"No results found for {tool_name}.{suggestion} "
            f"Consider rephrasing or trying a different approach."
        )

    elif etype == "validation":
        enriched["system_note"] = (
            f"Input validation failed for {tool_name}: {error_info['message']}. "
            f"Review and correct the parameters before trying again."
        )

    elif etype == "permanent":
        enriched["system_note"] = (
            f"{tool_name} encountered a permanent error. Do NOT retry. "
            f"Inform the user and suggest an alternative approach if possible."
        )

    else:
        alt = TOOL_ALTERNATIVES.get(tool_name, "")
        suggestion = f" {alt}" if alt else ""
        enriched["system_note"] = (
            f"{tool_name} returned an error.{suggestion}"
        )

    return json.dumps(enriched)


# ---------------------------------------------------------------------------
# Resilient Dispatch (main entry point)
# ---------------------------------------------------------------------------

def resilient_dispatch_tool(dispatch_fn, tool_name, tool_args, max_retries=2):
    """
    Wraps the raw dispatch_tool with error classification, retry, and enrichment.

    Args:
        dispatch_fn: the original dispatch_tool function
        tool_name: name of the tool to call
        tool_args: arguments dict
        max_retries: max automatic retries for transient errors

    Returns:
        str: the tool result (original on success, enriched on unrecoverable failure)
    """
    service = TOOL_SERVICE_MAP.get(tool_name, "local")
    breaker = _get_breaker(service)

    # Circuit breaker check
    if service != "local" and breaker.is_open():
        logger.warning(f"[SelfHealing] Circuit open for {service}, failing fast for {tool_name}")
        return json.dumps({
            "error": f"The {service} service is temporarily unavailable (circuit breaker open).",
            "error_type": "circuit_open",
            "tool": tool_name,
            "system_note": (
                f"The {service} service is experiencing repeated failures and has been "
                f"temporarily disabled to prevent further errors. All tools using {service} "
                f"are affected. Inform the user and suggest trying again in a minute or two."
            ),
        })

    # Known recurring failure check — skip retries entirely
    if is_known_recurring_failure(tool_name, tool_args):
        logger.info(f"[SelfHealing] Known recurring failure for {tool_name}, executing once without retry")
        max_retries = 0

    last_result = None
    last_error_info = None

    for attempt in range(max_retries + 1):
        try:
            result = dispatch_fn(tool_name, tool_args)
        except Exception as e:
            result = json.dumps({"error": f"Internal exception: {str(e)}"})

        error_info = classify_error(result)

        if error_info is None:
            # Success
            if service != "local":
                breaker.record_success()
            if attempt > 0:
                logger.info(
                    f"[SelfHealing] {tool_name} succeeded on attempt {attempt + 1}"
                )
            return result

        last_result = result
        last_error_info = error_info

        # Only retry transient errors
        if error_info["type"] != "transient" or attempt >= max_retries:
            break

        # Exponential backoff with jitter
        delay = (2 ** attempt) * 0.5 + random.uniform(0, 0.5)
        logger.info(
            f"[SelfHealing] {tool_name} transient error on attempt {attempt + 1}, "
            f"retrying in {delay:.1f}s: {error_info['message'][:80]}"
        )
        time.sleep(delay)

    # All attempts exhausted or non-retryable error
    total_attempts = min(attempt + 1, max_retries + 1)

    if service != "local":
        breaker.record_failure()

    log_failure(tool_name, tool_args, last_error_info, attempts=total_attempts)

    logger.warning(
        f"[SelfHealing] {tool_name} failed after {total_attempts} attempt(s): "
        f"[{last_error_info['type']}] {last_error_info['message'][:100]}"
    )

    return enrich_error_for_llm(tool_name, last_result, last_error_info, attempts=total_attempts)


# ---------------------------------------------------------------------------
# Stats / API queries
# ---------------------------------------------------------------------------

def get_failure_stats():
    """Return failure memory data for API consumption."""
    try:
        conn = _get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_failure_memory'"
        )
        if not cursor.fetchone():
            conn.close()
            return {"failures": [], "summary": {}}

        cursor.execute(
            """SELECT tool_name, error_type, error_signature, occurrence_count,
                      first_seen, last_seen, resolution, is_recurring
               FROM tool_failure_memory
               ORDER BY last_seen DESC
               LIMIT 100"""
        )
        failures = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            "SELECT COUNT(*) FROM tool_failure_memory"
        )
        total = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM tool_failure_memory WHERE is_recurring = 1"
        )
        recurring = cursor.fetchone()[0]

        cursor.execute(
            """SELECT tool_name, SUM(occurrence_count) as total_failures
               FROM tool_failure_memory
               GROUP BY tool_name
               ORDER BY total_failures DESC
               LIMIT 5"""
        )
        top_failing = [dict(r) for r in cursor.fetchall()]

        conn.close()

        return {
            "failures": failures,
            "summary": {
                "total_failure_patterns": total,
                "recurring_patterns": recurring,
                "top_failing_tools": top_failing,
            },
            "circuit_breakers": {
                name: breaker.state
                for name, breaker in _circuit_breakers.items()
            },
        }
    except Exception as e:
        return {"error": str(e), "failures": [], "summary": {}}


def cleanup_old_failures(days=14):
    """Remove failure entries older than N days. Called by nightly cleanup."""
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_failure_memory'"
        )
        if cursor.fetchone():
            cursor.execute(
                "DELETE FROM tool_failure_memory WHERE last_seen < datetime('now', 'localtime', ?)",
                (f"-{days} days",),
            )
            pruned = cursor.rowcount
            conn.commit()
            if pruned:
                logger.info(f"[SelfHealing] Pruned {pruned} old failure memory entries")
        conn.close()
    except Exception as e:
        logger.debug(f"[SelfHealing] Failure cleanup error: {e}")
