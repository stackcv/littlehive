import json
import datetime
from googleapiclient.discovery import build
from littlehive.tools.google_auth import get_credentials


def get_calendar_service():
    creds = get_credentials()
    if not creds:
        return None
    try:
        return build("calendar", "v3", credentials=creds)
    except Exception:
        return None


def get_events(
    time_min: str = None, time_max: str = None, max_results: int = 10
) -> str:
    """Fetch events within a timeframe. Returns IDs for updates/deletes."""
    service = get_calendar_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        if not time_min:
            time_min = datetime.datetime.utcnow().isoformat() + "Z"
        kwargs = {
            "calendarId": "primary",
            "timeMin": time_min,
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_max:
            kwargs["timeMax"] = time_max
        events_result = service.events().list(**kwargs).execute()
        events = events_result.get("items", [])
        return json.dumps(
            [
                {
                    "id": e["id"],
                    "summary": e.get("summary", "No Title"),
                    "start": e["start"].get("dateTime", e["start"].get("date")),
                    "end": e["end"].get("dateTime", e["end"].get("date")),
                    "attendees": [a.get("email") for a in e.get("attendees", [])],
                }
                for e in events
            ]
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def _actual_create_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    attendees: list = None,
    recurrence_rule: str = None,
    is_important: bool = False,
) -> str:
    """Creates an event. recurrence_rule follows iCal format (e.g. 'RRULE:FREQ=WEEKLY;BYDAY=TH,SA')."""
    service = get_calendar_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        event = {
            "summary": f"{'IMPORTANT: ' if is_important else ''}{summary}",
            "description": description,
            "start": {"dateTime": start_time},
            "end": {"dateTime": end_time},
            "colorId": "11" if is_important else None,
        }
        if attendees:
            event["attendees"] = [{"email": email} for email in attendees]
        if recurrence_rule:
            event["recurrence"] = [recurrence_rule]

        # sendUpdates='all' triggers email invites to attendees
        event = (
            service.events()
            .insert(
                calendarId="primary",
                body=event,
                sendUpdates="all" if attendees else "none",
            )
            .execute()
        )
        return json.dumps(
            {"status": "success", "id": event.get("id"), "link": event.get("htmlLink")}
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def _actual_update_event(
    event_id: str,
    summary: str = None,
    start_time: str = None,
    end_time: str = None,
    description: str = None,
    attendees: list = None,
) -> str:
    """Updates an existing event by ID. Only provided fields are changed."""
    service = get_calendar_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
        if summary:
            event["summary"] = summary
        if start_time:
            event["start"] = {"dateTime": start_time}
        if end_time:
            event["end"] = {"dateTime": end_time}
        if description:
            event["description"] = description
        if attendees:
            event["attendees"] = [{"email": email} for email in attendees]

        updated_event = (
            service.events()
            .update(
                calendarId="primary",
                eventId=event_id,
                body=event,
                sendUpdates="all" if attendees else "none",
            )
            .execute()
        )
        return json.dumps({"status": "updated", "link": updated_event.get("htmlLink")})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _actual_delete_event(event_id: str) -> str:
    """Deletes an event or a series by ID."""
    service = get_calendar_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        service.events().delete(
            calendarId="primary", eventId=event_id, sendUpdates="all"
        ).execute()
        return json.dumps({"status": "deleted"})
    except Exception as e:
        return json.dumps({"error": str(e)})


CALENDAR_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_events",
            "description": "Fetch events. Use time_min/time_max for specific days. Returns event IDs needed for updates/deletes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_min": {
                        "type": "string",
                        "description": "ISO 8601 (e.g. 2026-03-04T00:00:00Z)",
                    },
                    "time_max": {
                        "type": "string",
                        "description": "ISO 8601 (e.g. 2026-03-04T23:59:59Z)",
                    },
                    "max_results": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Create events/meetings. Supports invites, recurrence, and importance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "start_time": {
                        "type": "string",
                        "description": "ISO 8601 format WITH timezone offset (e.g. 2026-03-05T08:00:00+05:30 for IST)",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "ISO 8601 format WITH timezone offset (e.g. 2026-03-05T09:00:00+05:30 for IST)",
                    },
                    "description": {"type": "string"},
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of guest emails",
                    },
                    "recurrence_rule": {
                        "type": "string",
                        "description": "iCal RRULE (e.g. 'RRULE:FREQ=WEEKLY;BYDAY=MO,WE')",
                    },
                    "is_important": {
                        "type": "boolean",
                        "description": "If true, marks event as red and adds IMPORTANT prefix.",
                    },
                },
                "required": ["summary", "start_time", "end_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_event",
            "description": "Modify an existing event. Requires an event_id (get this from get_events first).",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "start_time": {
                        "type": "string",
                        "description": "ISO 8601 format WITH timezone offset",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "ISO 8601 format WITH timezone offset",
                    },
                    "description": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_event",
            "description": "Cancel/Delete an event. Requires an event_id.",
            "parameters": {
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
                "required": ["event_id"],
            },
        },
    },
]


from littlehive.tools.task_queue import queue_task


def create_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    attendees: list = None,
    recurrence_rule: str = None,
    is_important: bool = False,
) -> str:
    args = {
        "summary": summary,
        "start_time": start_time,
        "end_time": end_time,
        "description": description,
        "attendees": attendees,
        "recurrence_rule": recurrence_rule,
        "is_important": is_important,
    }
    return queue_task("create_event", args)


def update_event(
    event_id: str,
    summary: str = None,
    start_time: str = None,
    end_time: str = None,
    description: str = None,
    attendees: list = None,
) -> str:
    args = {
        "event_id": event_id,
        "summary": summary,
        "start_time": start_time,
        "end_time": end_time,
        "description": description,
        "attendees": attendees,
    }
    # Clean out None values
    args = {k: v for k, v in args.items() if v is not None}
    return queue_task("update_event", args)


def delete_event(event_id: str) -> str:
    return queue_task("delete_event", {"event_id": event_id})


def execute_tool(name: str, args: dict) -> str:

    funcs = {
        "get_events": get_events,
        "create_event": create_event,
        "update_event": update_event,
        "delete_event": delete_event,
    }
    return (
        funcs[name](**args) if name in funcs else json.dumps({"error": "Unknown tool"})
    )
