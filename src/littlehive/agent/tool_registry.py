import json
from typing import Dict, Any, List

# --- Import tool modules here ---
from littlehive.tools.calendar_tools import (
    CALENDAR_TOOLS_SCHEMA,
    execute_tool as calendar_execute,
)
from littlehive.tools.email_tools import (
    EMAIL_TOOLS_SCHEMA,
    execute_tool as email_execute,
)
from littlehive.tools.finance_tools import (
    FINANCE_TOOLS_SCHEMA,
    execute_tool as finance_execute,
)
from littlehive.tools.reminder_tools import (
    REMINDER_TOOLS_SCHEMA,
    execute_tool as reminder_execute,
)
from littlehive.tools.stakeholder_tools import (
    STAKEHOLDER_TOOLS_SCHEMA,
    execute_tool as stakeholder_execute,
)
from littlehive.tools.task_queue import QUEUE_TOOLS_SCHEMA, execute_queue_tool
from littlehive.tools.messaging_tools import (
    MESSAGING_TOOLS_SCHEMA,
    execute_tool as messaging_execute,
)
from littlehive.tools.google_tasks import (
    TASKS_TOOLS_SCHEMA as GOOGLE_TASKS_SCHEMA,
    execute_tool as google_tasks_execute,
)
from littlehive.tools.web_tools import (
    WEB_TOOLS_SCHEMA,
    execute_tool as web_execute,
)
from littlehive.tools.api_registry_tools import (
    API_REGISTRY_TOOLS_SCHEMA,
    execute_tool as api_registry_execute,
)
from littlehive.tools.shell_tools import (
    SHELL_TOOLS_SCHEMA,
    execute_tool as shell_execute,
)
from littlehive.tools.github_tools import (
    GITHUB_TOOLS_SCHEMA,
    execute_tool as github_execute,
)
from littlehive.tools.memory_tools import (
    save_core_fact,
    search_past_conversations,
    delete_core_fact,
)

INTERNAL_TASKS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_tasks",
            "description": "Fetch tasks from the local TODO list. Filter by status ('needsAction', 'completed').",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["needsAction", "completed"]}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Add a new task to the local TODO list (for project/to-do management). Do NOT use this for timed personal alarms or reminders (use set_reminder instead).",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "notes": {"type": "string"},
                    "due": {"type": "string", "description": "RFC 3339 timestamp (e.g. 2026-03-09T12:00:00Z)"},
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Modify a task or mark it completed (status='completed').",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "title": {"type": "string"},
                    "notes": {"type": "string"},
                    "status": {"type": "string", "enum": ["needsAction", "completed"]},
                    "due": {"type": "string"}
                },
                "required": ["task_id"]
            }
        }
    }
]


def _internal_tasks_execute(tool_name: str, args: Dict[str, Any]) -> str:
    from littlehive.agent.local_cache import (
        internal_create_todo,
        internal_get_todos,
        internal_update_todo,
        internal_delete_todo,
    )
    try:
        if tool_name == "get_tasks":
            return json.dumps(internal_get_todos(status=args.get("status")))
        elif tool_name == "create_task":
            return json.dumps(internal_create_todo(
                title=args["title"],
                notes=args.get("notes", ""),
                due=args.get("due", ""),
            ))
        elif tool_name == "update_task":
            return json.dumps(internal_update_todo(
                todo_id=args["task_id"],
                title=args.get("title"),
                notes=args.get("notes"),
                status=args.get("status"),
                due=args.get("due"),
            ))
        elif tool_name == "delete_task":
            return json.dumps(internal_delete_todo(todo_id=args["task_id"]))
        else:
            return json.dumps({"error": f"Unknown task tool: {tool_name}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _get_tasks_schema():
    from littlehive.agent.config import get_config
    provider = get_config().get("todo_provider", "internal")
    if provider == "google_tasks":
        return GOOGLE_TASKS_SCHEMA
    return INTERNAL_TASKS_SCHEMA


def _tasks_dispatch(tool_name: str, args: Dict[str, Any]) -> str:
    from littlehive.agent.config import get_config
    provider = get_config().get("todo_provider", "internal")
    if provider == "google_tasks":
        return google_tasks_execute(tool_name, args)
    return _internal_tasks_execute(tool_name, args)


MEMORY_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "save_core_fact",
            "description": "Saves an important long-term fact into core memory. Only use when the user EXPLICITLY tells you something personal (name, family, birthday, preference) that should be remembered permanently. Do NOT save transient topics, task details, or conversational context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "The fact to remember (e.g., 'User's sister is Jenna', 'User prefers concise answers').",
                    }
                },
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_core_fact",
            "description": "Deletes a fact from core memory. Use this when the user tells you to forget something, or corrects a previously saved fact. It searches for and deletes any facts containing the given query string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A keyword or phrase to search for and delete (e.g., 'Jenna' or 'sister').",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_past_conversations",
            "description": "Searches the archival chat history for past conversations. Useful when the user asks about something discussed previously that is no longer in the immediate context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to look for in past conversations.",
                    }
                },
                "required": ["query"],
            },
        },
    },
]


def memory_execute(tool_name: str, args: Dict[str, Any]) -> str:
    try:
        if tool_name == "save_core_fact":
            return save_core_fact(args.get("fact", ""))
        elif tool_name == "delete_core_fact":
            return delete_core_fact(args.get("query", ""))
        elif tool_name == "search_past_conversations":
            return search_past_conversations(args.get("query", ""))
        else:
            return json.dumps({"error": f"Unknown memory tool: {tool_name}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _build_tool_list() -> List[Dict[str, Any]]:
    """Build the tool schema list, conditionally including optional tools."""
    from littlehive.agent.config import get_config
    tools = (
        EMAIL_TOOLS_SCHEMA
        + CALENDAR_TOOLS_SCHEMA
        + FINANCE_TOOLS_SCHEMA
        + REMINDER_TOOLS_SCHEMA
        + STAKEHOLDER_TOOLS_SCHEMA
        + MEMORY_TOOLS_SCHEMA
        + MESSAGING_TOOLS_SCHEMA
        + QUEUE_TOOLS_SCHEMA
        + _get_tasks_schema()
        + WEB_TOOLS_SCHEMA
        + API_REGISTRY_TOOLS_SCHEMA
    )
    config = get_config()
    if config.get("shell_enabled", False):
        tools = tools + SHELL_TOOLS_SCHEMA
    if config.get("github_token", ""):
        tools = tools + GITHUB_TOOLS_SCHEMA
    return tools


EA_PERSONA_TOOLS = _build_tool_list()

def get_all_schemas() -> List[Dict[str, Any]]:
    """Returns all available tool schemas."""
    return list(EA_PERSONA_TOOLS)


def dispatch_tool(tool_name: str, tool_args: Dict[str, Any]) -> str:
    """
    Global executor that checks all tools and runs the correct one.
    """
    # 1. Calendar tools
    calendar_tool_names = [t["function"]["name"] for t in CALENDAR_TOOLS_SCHEMA]
    if tool_name in calendar_tool_names:
        return calendar_execute(tool_name, tool_args)

    # 2. Email tools
    email_tool_names = [t["function"]["name"] for t in EMAIL_TOOLS_SCHEMA]
    if tool_name in email_tool_names:
        return email_execute(tool_name, tool_args)

    # 3. Finance tools
    finance_tool_names = [t["function"]["name"] for t in FINANCE_TOOLS_SCHEMA]
    if tool_name in finance_tool_names:
        return finance_execute(tool_name, tool_args)

    # 4. Reminder tools
    reminder_tool_names = [t["function"]["name"] for t in REMINDER_TOOLS_SCHEMA]
    if tool_name in reminder_tool_names:
        return reminder_execute(tool_name, tool_args)

    # 5. Stakeholder tools
    stakeholder_tool_names = [t["function"]["name"] for t in STAKEHOLDER_TOOLS_SCHEMA]
    if tool_name in stakeholder_tool_names:
        return stakeholder_execute(tool_name, tool_args)

    # 6. Memory tools
    memory_tool_names = [t["function"]["name"] for t in MEMORY_TOOLS_SCHEMA]
    if tool_name in memory_tool_names:
        return memory_execute(tool_name, tool_args)

    # 7. Queue tools
    queue_tool_names = [t["function"]["name"] for t in QUEUE_TOOLS_SCHEMA]
    if tool_name in queue_tool_names:
        return execute_queue_tool(tool_name, tool_args)

    # 8. Messaging tools
    messaging_tool_names = [t["function"]["name"] for t in MESSAGING_TOOLS_SCHEMA]
    if tool_name in messaging_tool_names:
        return messaging_execute(tool_name, tool_args)

    # 9. Tasks tools (internal or Google Tasks based on config)
    tasks_tool_names = [t["function"]["name"] for t in _get_tasks_schema()]
    if tool_name in tasks_tool_names:
        return _tasks_dispatch(tool_name, tool_args)

    # 10. Web search tools
    web_tool_names = [t["function"]["name"] for t in WEB_TOOLS_SCHEMA]
    if tool_name in web_tool_names:
        return web_execute(tool_name, tool_args)

    # 11. Custom API registry tools
    api_tool_names = [t["function"]["name"] for t in API_REGISTRY_TOOLS_SCHEMA]
    if tool_name in api_tool_names:
        return api_registry_execute(tool_name, tool_args)

    # 12. Shell / file / TTS tools (only dispatches if shell_enabled)
    shell_tool_names = [t["function"]["name"] for t in SHELL_TOOLS_SCHEMA]
    if tool_name in shell_tool_names:
        from littlehive.agent.config import get_config
        if not get_config().get("shell_enabled", False):
            return json.dumps({"error": "Shell tools are disabled. Enable them in Settings."})
        return shell_execute(tool_name, tool_args)

    # 13. GitHub tools
    github_tool_names = [t["function"]["name"] for t in GITHUB_TOOLS_SCHEMA]
    if tool_name in github_tool_names:
        return github_execute(tool_name, tool_args)

    return json.dumps({"error": f"Tool '{tool_name}' not found in registry."})
