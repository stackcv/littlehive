import re
import json
import markdown
from littlehive.agent.logger_setup import logger
import base64
from email.message import EmailMessage
from googleapiclient.discovery import build
from littlehive.tools.google_auth import get_credentials


_EMAIL_CSS = (
    "body { font-family: -apple-system, Helvetica, Arial, sans-serif; "
    "font-size: 14px; line-height: 1.5; color: #222; } "
    "p { margin: 0 0 10px; } "
    "blockquote { border-left: 3px solid #ccc; padding-left: 12px; color: #555; }"
)


def _md_to_html(body: str) -> str:
    """Convert a markdown email body to a styled HTML document."""
    html_fragment = markdown.markdown(body, extensions=["extra", "nl2br"])
    return (
        f"<html><head><style>{_EMAIL_CSS}</style></head>"
        f"<body>{html_fragment}</body></html>"
    )


def get_gmail_service():
    creds = get_credentials()
    if not creds:
        return None
    try:
        return build("gmail", "v1", credentials=creds)
    except Exception:
        return None


def _live_search_emails(query: str = "is:unread", max_results: int = 10) -> str:
    """Search inbox using Gmail syntax. Returns high-level summaries."""
    service = get_gmail_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        # Use partial response (fields) to only fetch the exact IDs needed from the list
        results = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=max_results,
                fields="messages(id,threadId)",
            )
            .execute()
        )
        messages = results.get("messages", [])
        if not messages:
            return json.dumps(
                {"emails": [], "message": "No emails found matching query."}
            )

        email_list = []

        def batch_callback(request_id, response, exception):
            if exception is not None:
                logger.error(f"[Email Batch Error] {exception}")
                return

            headers = response.get("payload", {}).get("headers", [])
            subject = next(
                (h["value"] for h in headers if h["name"].lower() == "subject"),
                "No Subject",
            )
            sender = next(
                (h["value"] for h in headers if h["name"].lower() == "from"),
                "Unknown Sender",
            )
            date = next(
                (h["value"] for h in headers if h["name"].lower() == "date"),
                "Unknown Date",
            )
            
            # Extract internal date for cache ordering
            internal_date = int(response.get("internalDate", "0"))

            # Check for one-click unsubscribe links
            unsubscribe_header = next(
                (
                    h["value"]
                    for h in headers
                    if h["name"].lower() == "list-unsubscribe"
                ),
                None,
            )
            unsubscribe_link = None
            if unsubscribe_header:
                match = re.search(r"<(https?://[^>]+)>", unsubscribe_header)
                if match:
                    unsubscribe_link = match.group(1)
            
            # Determine if unread based on labels
            label_ids = response.get("labelIds", [])
            is_read = "UNREAD" not in label_ids

            email_info = {
                "id": response["id"],
                "thread_id": response["threadId"],
                "sender": sender,
                "subject": subject,
                "date": date,
                "snippet": response.get("snippet", ""),
                "is_read": is_read,
                "timestamp_ms": internal_date
            }
            if unsubscribe_link:
                email_info["unsubscribe_link"] = unsubscribe_link

            email_list.append(email_info)

        # Execute all get requests in a single HTTP batch
        batch = service.new_batch_http_request(callback=batch_callback)
        for msg in messages:
            # Use fields mask to severely restrict the payload size returned by Google
            req = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date", "List-Unsubscribe"],
                    fields="id,threadId,snippet,payload/headers,internalDate,labelIds",
                )
            )
            batch.add(req)

        batch.execute()

        return json.dumps({"emails": email_list})
    except Exception as e:
        return json.dumps({"error": str(e)})

def search_emails(query: str = "is:unread", max_results: int = 10) -> str:
    """Search inbox using local cache."""
    from littlehive.agent.local_cache import query_cached_emails
    return query_cached_emails(query, max_results)


def read_full_email(message_id: str) -> str:
    """Fetch the full raw text body of a specific email."""
    service = get_gmail_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        payload = msg.get("payload", {})

        # Recursive function to dig through multipart emails to find the plain text
        def get_text(payload):
            mime_type = payload.get("mimeType")
            if mime_type == "text/plain":
                data = payload.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8")
            elif "parts" in payload:
                for part in payload["parts"]:
                    text = get_text(part)
                    if text:
                        return text
            return ""

        body_text = get_text(payload)
        if not body_text:
            body_text = msg.get("snippet", "No readable text body found.")

        headers = payload.get("headers", [])
        subject = next(
            (h["value"] for h in headers if h["name"].lower() == "subject"),
            "No Subject",
        )
        sender = next(
            (h["value"] for h in headers if h["name"].lower() == "from"),
            "Unknown Sender",
        )

        return json.dumps(
            {"id": message_id, "sender": sender, "subject": subject, "body": body_text}
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def _update_email_cache_after_action(message_ids: list, action: str):
    """Immediately reflect manage_email actions in the local cache so searches stay consistent."""
    try:
        from littlehive.agent.local_cache import _get_db
        conn = _get_db()
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in message_ids)

        if action == "mark_read":
            cur.execute(
                f"UPDATE cached_emails SET is_read = 1 WHERE id IN ({placeholders})",
                message_ids,
            )
        elif action == "mark_unread":
            cur.execute(
                f"UPDATE cached_emails SET is_read = 0 WHERE id IN ({placeholders})",
                message_ids,
            )
        elif action in ("archive", "trash"):
            cur.execute(
                f"DELETE FROM cached_emails WHERE id IN ({placeholders})",
                message_ids,
            )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Cache update after {action} failed: {e}")


def _actual_manage_email(message_id: str | list, action: str) -> str:
    """Perform actions like archiving, trashing, starring, marking read, or unsubscribing. Supports single or multiple IDs."""
    service = get_gmail_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        # Handle list of IDs
        if isinstance(message_id, list):
            message_ids = message_id
        else:
            message_ids = [message_id]

        results = []
        if action == "unsubscribe":
            # Unsubscribe requires analyzing headers per email, so we still iterate but we can use field masks
            for m_id in message_ids:
                msg_data = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=m_id,
                        format="metadata",
                        metadataHeaders=["List-Unsubscribe"],
                        fields="payload/headers",
                    )
                    .execute()
                )
                headers = msg_data.get("payload", {}).get("headers", [])
                unsubscribe_header = next(
                    (
                        h["value"]
                        for h in headers
                        if h["name"].lower() == "list-unsubscribe"
                    ),
                    None,
                )

                if not unsubscribe_header:
                    results.append(
                        {
                            "id": m_id,
                            "error": "No unsubscribe link found in the email headers.",
                        }
                    )
                    continue

                import re
                import urllib.request

                match = re.search(r"<(https?://[^>]+)>", unsubscribe_header)
                if not match:
                    results.append(
                        {"id": m_id, "error": "No HTTP unsubscribe link found."}
                    )
                    continue

                unsubscribe_url = match.group(1)
                try:
                    req = urllib.request.Request(
                        unsubscribe_url, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    with urllib.request.urlopen(req) as response:
                        status = response.getcode()

                    service.users().messages().modify(
                        userId="me", id=m_id, body={"addLabelIds": ["TRASH"]}
                    ).execute()
                    results.append(
                        {
                            "id": m_id,
                            "status": "success",
                            "action": "unsubscribed and trashed",
                            "url": unsubscribe_url,
                            "http_status": status,
                        }
                    )
                except Exception as e:
                    results.append(
                        {
                            "id": m_id,
                            "error": f"Failed to hit unsubscribe URL: {str(e)}",
                        }
                    )

            if len(results) == 1:
                return json.dumps(results[0])
            return json.dumps({"results": results})

        # For all standard label modifications, use batchModify for bulk performance
        add_labels = []
        remove_labels = []
        if action == "mark_read":
            remove_labels.append("UNREAD")
        elif action == "mark_unread":
            add_labels.append("UNREAD")
        elif action == "archive":
            remove_labels.append("INBOX")
            remove_labels.append("UNREAD")
        elif action == "trash":
            add_labels.append("TRASH")
        elif action == "star":
            add_labels.append("STARRED")
        elif action == "unstar":
            remove_labels.append("STARRED")
        else:
            return json.dumps({"error": f"Unknown action: {action}"})

        body = {
            "ids": message_ids,
            "addLabelIds": add_labels,
            "removeLabelIds": remove_labels,
        }

        if len(message_ids) > 0:
            service.users().messages().batchModify(userId="me", body=body).execute()
            for m_id in message_ids:
                results.append({"id": m_id, "status": "success", "action": action})

            _update_email_cache_after_action(message_ids, action)

        if len(results) == 1:
            return json.dumps(results[0])
        return json.dumps({"results": results})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _actual_send_email(
    to: str, subject: str, body: str, send_as_pdf: bool = False
) -> str:
    """Compose and send a brand new email, optionally with the body as a PDF attachment."""
    service = get_gmail_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        message = EmailMessage()

        if send_as_pdf:
            # The email body becomes a simple cover letter
            message.set_content("Please find the requested document attached.")

            # Convert the Markdown body to PDF using xhtml2pdf
            import markdown
            from xhtml2pdf import pisa
            import io

            # Convert markdown to HTML with 'extra' features (tables, etc.)
            html_text = markdown.markdown(body, extensions=["extra"])

            # Wrap in basic CSS for professional formatting
            styled_html = f"<html><head><style>body {{ font-family: Helvetica, sans-serif; padding: 30px; font-size: 12pt; line-height: 1.6; color: #333; }} h1, h2, h3 {{ color: #000; border-bottom: 1px solid #eee; padding-bottom: 10px; }} code {{ background: #f4f4f4; padding: 2px 4px; border-radius: 3px; }} pre {{ background: #f4f4f4; padding: 10px; border-radius: 5px; }} blockquote {{ border-left: 5px solid #ccc; padding-left: 15px; color: #666; }}</style></head><body>{html_text}</body></html>"

            pdf_buffer = io.BytesIO()
            pisa.CreatePDF(io.StringIO(styled_html), dest=pdf_buffer)
            pdf_data = pdf_buffer.getvalue()

            # Attach the PDF
            safe_filename = "".join(
                c if c.isalnum() or c in " _-" else "_" for c in subject
            )
            message.add_attachment(
                pdf_data,
                maintype="application",
                subtype="pdf",
                filename=f"{safe_filename}.pdf",
            )
        else:
            message.set_content(body)
            message.add_alternative(_md_to_html(body), subtype="html")

        message["To"] = to
        message["Subject"] = subject

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {"raw": encoded_message}

        sent_message = (
            service.users().messages().send(userId="me", body=create_message).execute()
        )
        return json.dumps(
            {
                "status": "success",
                "message_id": sent_message["id"],
                "format": "pdf" if send_as_pdf else "html",
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def _actual_reply_to_email(message_id: str, body: str) -> str:
    """Reply directly to an existing email thread."""
    service = get_gmail_service()
    if not service:
        return json.dumps({"error": "Auth failed"})
    try:
        # Fetch metadata to get the Message-ID and sender to correctly thread the reply
        orig_msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["Message-ID", "References", "Subject", "From", "To"],
            )
            .execute()
        )
        headers = orig_msg["payload"]["headers"]

        orig_msg_id = next(
            (h["value"] for h in headers if h["name"].lower() == "message-id"), ""
        )
        references = next(
            (h["value"] for h in headers if h["name"].lower() == "references"), ""
        )
        orig_subject = next(
            (h["value"] for h in headers if h["name"].lower() == "subject"), ""
        )
        orig_sender = next(
            (h["value"] for h in headers if h["name"].lower() == "from"), ""
        )

        subject = (
            orig_subject
            if orig_subject.lower().startswith("re:")
            else f"Re: {orig_subject}"
        )

        message = EmailMessage()
        message.set_content(body)
        message.add_alternative(_md_to_html(body), subtype="html")
        message["To"] = orig_sender
        message["Subject"] = subject
        message["In-Reply-To"] = orig_msg_id
        message["References"] = (
            f"{references} {orig_msg_id}".strip() if references else orig_msg_id
        )

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {"raw": encoded_message, "threadId": orig_msg["threadId"]}

        sent_message = (
            service.users().messages().send(userId="me", body=create_message).execute()
        )
        return json.dumps(
            {
                "status": "success",
                "message_id": sent_message["id"],
                "thread_id": sent_message["threadId"],
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


EMAIL_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_emails",
            "description": "Search inbox using Gmail query syntax (e.g., 'is:unread', 'from:john', 'subject:invoice'). Returns summary list with IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Standard Gmail search string. Use simple queries like 'is:unread'. NEVER use ISO 8601 timestamps (e.g. 2026-03-05T00:00:00) in Gmail queries; if you must filter by date, use 'after:YYYY/MM/DD' instead.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Limit results. Default 10.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_full_email",
            "description": "Fetch the full text body of a specific email. Requires message_id.",
            "parameters": {
                "type": "object",
                "properties": {"message_id": {"type": "string"}},
                "required": ["message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_email",
            "description": "Execute actions on an email: 'mark_read', 'mark_unread', 'archive', 'trash', 'star', 'unstar', 'unsubscribe'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "A single message ID string, or an array of message ID strings to process in bulk.",
                    },
                    "action": {
                        "type": "string",
                        "enum": [
                            "mark_read",
                            "mark_unread",
                            "archive",
                            "trash",
                            "star",
                            "unstar",
                            "unsubscribe",
                        ],
                    },
                },
                "required": ["message_id", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Compose and send a brand new email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string"},
                    "body": {
                        "type": "string",
                        "description": "Email body content. ALWAYS use standard Markdown styling for formatting.",
                    },
                    "next_run_at": {"type": "string", "description": "Optional: Schedule for later (YYYY-MM-DD HH:MM:SS format)"},
                    "send_as_pdf": {
                        "type": "boolean",
                        "description": "If true, converts the body from markdown into a formatted PDF attachment.",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reply_to_email",
            "description": "Reply to an existing email thread. Requires message_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The ID of the message you are replying to",
                    },
                    "body": {
                        "type": "string",
                        "description": "Your reply message text",
                    },
                },
                "required": ["message_id", "body"],
            },
        },
    },
]


from littlehive.tools.task_queue import queue_task


def send_email(to: str, subject: str, body: str, send_as_pdf: bool = False, next_run_at: str = None) -> str:
    """Compose and schedule an email to be sent asynchronously."""
    return queue_task(
        "send_email",
        {"to": to, "subject": subject, "body": body, "send_as_pdf": send_as_pdf},
        next_run_at=next_run_at
    )


def execute_tool(name: str, args: dict) -> str:

    funcs = {
        "search_emails": search_emails,
        "read_full_email": read_full_email,
        "manage_email": manage_email,
        "send_email": send_email,
        "reply_to_email": reply_to_email,
    }
    return (
        funcs[name](**args) if name in funcs else json.dumps({"error": "Unknown tool"})
    )


def manage_email(message_id: str | list, action: str, next_run_at: str = None) -> str:
    """Queue an action on an email to be executed asynchronously."""
    return queue_task("manage_email", {"message_id": message_id, "action": action}, next_run_at=next_run_at)


def reply_to_email(message_id: str, body: str, next_run_at: str = None) -> str:
    """Queue a reply to an email to be executed asynchronously."""
    return queue_task("reply_to_email", {"message_id": message_id, "body": body}, next_run_at=next_run_at)
