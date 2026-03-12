import json
from googleapiclient.discovery import build
from littlehive.tools.google_auth import get_credentials
from littlehive.tools.task_queue import queue_task


def get_tasks_service():
    creds = get_credentials()
    if not creds:
        return None
    try:
        return build("tasks", "v1", credentials=creds)
    except Exception:
        return None


def get_task_lists() -> str:
    """Fetch all task lists (e.g., 'StackCV', 'LittleHive')."""
    service = get_tasks_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        results = service.tasklists().list().execute()
        items = results.get("items", [])
        return json.dumps(
            [{"id": i["id"], "title": i["title"]} for i in items]
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def _live_get_tasks(tasklist_id: str = "@default", show_completed: bool = False) -> str:
    """Fetch tasks from a specific list using the Google API."""
    service = get_tasks_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        results = (
            service.tasks()
            .list(tasklist=tasklist_id, showCompleted=show_completed)
            .execute()
        )
        items = results.get("items", [])
        return json.dumps(
            [
                {
                    "id": i["id"],
                    "list_id": tasklist_id,
                    "title": i["title"],
                    "notes": i.get("notes", ""),
                    "status": i["status"],
                    "due": i.get("due"),
                    "updated": i.get("updated"),
                }
                for i in items
            ]
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_tasks(tasklist_id: str = None, status: str = None) -> str:
    """Fetch tasks from local cache."""
    from littlehive.agent.local_cache import query_cached_tasks
    return query_cached_tasks(list_id=tasklist_id, status=status)


def create_task(title: str, notes: str = None, due: str = None, tasklist_id: str = "@default") -> str:
    """Queue a new task to be created in Google Tasks."""
    args = {
        "title": title,
        "notes": notes,
        "due": due,
        "tasklist_id": tasklist_id
    }
    return queue_task("create_task", args)


def _actual_create_task(title: str, notes: str = None, due: str = None, tasklist_id: str = "@default") -> str:
    """The background executor for creating a task."""
    service = get_tasks_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        task = {"title": title}
        if notes:
            task["notes"] = notes
        if due:
            task["due"] = due
        
        result = service.tasks().insert(tasklist=tasklist_id, body=task).execute()
        return json.dumps({"status": "success", "id": result.get("id")})
    except Exception as e:
        return json.dumps({"error": str(e)})


def update_task(task_id: str, title: str = None, notes: str = None, status: str = None, due: str = None, tasklist_id: str = "@default") -> str:
    """Queue a task update (e.g., mark as completed)."""
    args = {
        "task_id": task_id,
        "title": title,
        "notes": notes,
        "status": status,
        "due": due,
        "tasklist_id": tasklist_id
    }
    # Clean out None values
    args = {k: v for k, v in args.items() if v is not None}
    return queue_task("update_task", args)


def _actual_update_task(task_id: str, tasklist_id: str = "@default", **kwargs) -> str:
    """The background executor for updating a task."""
    service = get_tasks_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        # Patch is safer than update as it only changes provided fields
        result = service.tasks().patch(tasklist=tasklist_id, task=task_id, body=kwargs).execute()
        return json.dumps({"status": "updated", "id": result.get("id")})
    except Exception as e:
        return json.dumps({"error": str(e)})


def delete_task(task_id: str, tasklist_id: str = "@default") -> str:
    """Queue a task deletion."""
    return queue_task("delete_task", {"task_id": task_id, "tasklist_id": tasklist_id})


def _actual_delete_task(task_id: str, tasklist_id: str = "@default") -> str:
    """The background executor for deleting a task."""
    service = get_tasks_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        service.tasks().delete(tasklist=tasklist_id, task=task_id).execute()
        return json.dumps({"status": "deleted"})
    except Exception as e:
        return json.dumps({"error": str(e)})


TASKS_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_task_lists",
            "description": "Get all task lists (e.g. 'StackCV', 'LittleHive'). Use this to find list IDs.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_tasks",
            "description": "Fetch tasks from local cache. Filter by list_id or status ('needsAction', 'completed').",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasklist_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["needsAction", "completed"]}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Add a new task to a specific Google Tasks list (for project/to-do management). Do NOT use this for timed personal alarms or reminders (use set_reminder instead).",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "notes": {"type": "string"},
                    "due": {"type": "string", "description": "RFC 3339 timestamp (e.g. 2026-03-09T12:00:00Z)"},
                    "tasklist_id": {"type": "string", "default": "@default"}
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
                    "tasklist_id": {"type": "string", "default": "@default"},
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


def execute_tool(name: str, args: dict) -> str:
    funcs = {
        "get_task_lists": get_task_lists,
        "get_tasks": get_tasks,
        "create_task": create_task,
        "update_task": update_task,
        "delete_task": delete_task,
    }
    return funcs[name](**args) if name in funcs else json.dumps({"error": "Unknown tool"})
