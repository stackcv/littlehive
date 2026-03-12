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
    TASKS_TOOLS_SCHEMA,
    execute_tool as tasks_execute,
)
from littlehive.tools.web_tools import (
    WEB_TOOLS_SCHEMA,
    execute_tool as web_execute,
)
from littlehive.tools.memory_tools import (
    save_core_fact,
    search_past_conversations,
    delete_core_fact,
)

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


EA_PERSONA_TOOLS = (
    EMAIL_TOOLS_SCHEMA
    + CALENDAR_TOOLS_SCHEMA
    + FINANCE_TOOLS_SCHEMA
    + REMINDER_TOOLS_SCHEMA
    + STAKEHOLDER_TOOLS_SCHEMA
    + MEMORY_TOOLS_SCHEMA
    + MESSAGING_TOOLS_SCHEMA
    + QUEUE_TOOLS_SCHEMA
    + TASKS_TOOLS_SCHEMA
    + WEB_TOOLS_SCHEMA
)

ROUTE_SCHEMAS = {
    "calendar": EA_PERSONA_TOOLS,
    "email": EA_PERSONA_TOOLS,
    "finance": EA_PERSONA_TOOLS,
    "reminder": EA_PERSONA_TOOLS,
    "memory": EA_PERSONA_TOOLS,
    "tasks": EA_PERSONA_TOOLS,
    "web": EA_PERSONA_TOOLS,
}


def get_all_schemas() -> List[Dict[str, Any]]:
    """Returns all available schemas across all routes without duplicates."""
    all_tools = []
    seen_names = set()
    for schemas in ROUTE_SCHEMAS.values():
        for schema in schemas:
            name = schema["function"]["name"]
            if name not in seen_names:
                seen_names.add(name)
                all_tools.append(schema)
    return all_tools


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

    # 9. Google Tasks tools
    tasks_tool_names = [t["function"]["name"] for t in TASKS_TOOLS_SCHEMA]
    if tool_name in tasks_tool_names:
        return tasks_execute(tool_name, tool_args)

    # 10. Web search tools
    web_tool_names = [t["function"]["name"] for t in WEB_TOOLS_SCHEMA]
    if tool_name in web_tool_names:
        return web_execute(tool_name, tool_args)

    return json.dumps({"error": f"Tool '{tool_name}' not found in registry."})
