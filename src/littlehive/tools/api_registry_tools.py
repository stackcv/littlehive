import json
import re

import requests
from littlehive.agent.logger_setup import logger
from littlehive.agent.paths import DB_PATH

import sqlite3


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


API_REGISTRY_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "call_api",
            "description": (
                "Call a registered custom API by name. Use this to invoke external "
                "services the user has configured (weather, stock prices, smart home, etc). "
                "Pass any required parameters as key-value pairs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The registered API name (e.g. 'get_weather', 'stock_price').",
                    },
                    "params": {
                        "type": "object",
                        "description": "Key-value parameters to fill into the URL or body template.",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "register_api",
            "description": (
                "Register a new custom API endpoint. After registration the agent "
                "can call it with call_api. Use {placeholder} in the URL or body "
                "for dynamic parameters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short unique name (e.g. 'get_weather', 'stock_price').",
                    },
                    "url": {
                        "type": "string",
                        "description": "Full URL with optional {placeholders} (e.g. 'https://api.example.com/quote/{symbol}').",
                    },
                    "method": {
                        "type": "string",
                        "description": "HTTP method: GET or POST. Default GET.",
                    },
                    "headers": {
                        "type": "object",
                        "description": "Optional HTTP headers as key-value pairs (e.g. {\"Authorization\": \"Bearer xyz\"}).",
                    },
                    "body_template": {
                        "type": "string",
                        "description": "Optional JSON body template for POST requests with {placeholders}.",
                    },
                    "description": {
                        "type": "string",
                        "description": "What this API does (shown to the agent for future calls).",
                    },
                },
                "required": ["name", "url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_apis",
            "description": (
                "List all registered custom APIs with their names, URLs, and descriptions."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


def _parse_response(response, content_type: str):
    """Parse the HTTP response based on content type, with RSS/XML support."""
    if "json" in content_type:
        try:
            return response.json()
        except Exception:
            return response.text[:2000]

    if "xml" in content_type or "rss" in content_type:
        return _xml_to_text(response.text)

    # Fallback: try JSON, then check if it looks like XML, else raw text
    try:
        return response.json()
    except Exception:
        text = response.text
        if text.strip().startswith("<?xml") or text.strip().startswith("<rss"):
            return _xml_to_text(text)
        return text[:2000]


def _xml_to_text(xml_str: str) -> str:
    """Convert XML/RSS into a clean text summary for the LLM."""
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_str)

        # RSS feed: look for channel/item elements
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        if items:
            entries = []
            for item in items[:10]:
                title = (
                    item.findtext("title")
                    or item.findtext("{http://www.w3.org/2005/Atom}title")
                    or ""
                )
                desc = (
                    item.findtext("description")
                    or item.findtext("{http://www.w3.org/2005/Atom}summary")
                    or ""
                )
                link = (
                    item.findtext("link")
                    or ""
                )
                if not link:
                    link_el = item.find("{http://www.w3.org/2005/Atom}link")
                    if link_el is not None:
                        link = link_el.get("href", "")

                desc_clean = re.sub(r"<[^>]+>", "", desc)[:200]
                entry = f"- {title}"
                if desc_clean:
                    entry += f": {desc_clean}"
                if link:
                    entry += f" ({link})"
                entries.append(entry)

            feed_title = (
                root.findtext(".//channel/title")
                or root.findtext(".//{http://www.w3.org/2005/Atom}title")
                or "RSS Feed"
            )
            return f"{feed_title}\n" + "\n".join(entries)

        # Generic XML: extract all text content
        texts = []
        for elem in root.iter():
            if elem.text and elem.text.strip():
                texts.append(elem.text.strip())
        return " ".join(texts)[:2000]

    except Exception:
        clean = re.sub(r"<[^>]+>", " ", xml_str)
        return re.sub(r"\s+", " ", clean).strip()[:2000]


def _fill_template(template: str, params: dict) -> str:
    """Replace {key} placeholders with values from params."""
    def replacer(match):
        key = match.group(1)
        return str(params.get(key, match.group(0)))
    return re.sub(r"\{(\w+)\}", replacer, template)


def call_api(name: str, params: dict = None) -> str:
    """Look up a registered API by name, fill templates, execute the request."""
    params = params or {}
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM custom_apis WHERE name = ?", (name,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            available = _list_api_names()
            return json.dumps({
                "error": f"No API registered with name '{name}'.",
                "available_apis": available,
            })

        url = _fill_template(row["url"], params)
        method = (row["method"] or "GET").upper()

        headers_raw = row["headers"] or "{}"
        try:
            headers = json.loads(headers_raw)
        except json.JSONDecodeError:
            headers = {}
        headers["User-Agent"] = "LittleHive/1.0"

        logger.info(f"[CustomAPI] Calling {method} {url}")

        if method == "POST":
            body_tmpl = row["body_template"] or ""
            body_str = _fill_template(body_tmpl, params) if body_tmpl else None
            try:
                body_json = json.loads(body_str) if body_str else None
            except json.JSONDecodeError:
                body_json = None

            if body_json:
                headers.setdefault("Content-Type", "application/json")
                response = requests.post(url, json=body_json, headers=headers, timeout=15)
            else:
                response = requests.post(url, data=body_str, headers=headers, timeout=15)
        else:
            response = requests.get(url, headers=headers, timeout=15)

        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        result = _parse_response(response, content_type)

        logger.info(f"[CustomAPI] {name} returned {response.status_code}")
        return json.dumps({"api": name, "status": response.status_code, "data": result})

    except requests.RequestException as e:
        logger.warning(f"[CustomAPI] Request failed for '{name}': {e}")
        return json.dumps({"error": f"API request failed: {str(e)}"})
    except Exception as e:
        logger.warning(f"[CustomAPI] Error calling '{name}': {e}")
        return json.dumps({"error": str(e)})


def register_api(
    name: str,
    url: str,
    method: str = "GET",
    headers: dict = None,
    body_template: str = "",
    description: str = "",
) -> str:
    """Register a new custom API endpoint."""
    if not name or not url:
        return json.dumps({"error": "Both 'name' and 'url' are required."})

    name = name.strip().lower().replace(" ", "_")
    method = (method or "GET").upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        return json.dumps({"error": f"Unsupported method: {method}"})

    headers_json = json.dumps(headers) if headers else "{}"

    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO custom_apis (name, url, method, headers, body_template, description)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                url=excluded.url,
                method=excluded.method,
                headers=excluded.headers,
                body_template=excluded.body_template,
                description=excluded.description
            """,
            (name, url, method, headers_json, body_template or "", description or ""),
        )
        conn.commit()
        conn.close()
        logger.info(f"[CustomAPI] Registered API: {name}")
        return json.dumps({
            "success": True,
            "message": f"API '{name}' registered. You can now call it with call_api.",
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def list_apis() -> str:
    """Return all registered custom APIs."""
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, url, method, description, created_at FROM custom_apis ORDER BY name"
        )
        rows = cursor.fetchall()
        conn.close()

        apis = [
            {
                "name": r["name"],
                "url": r["url"],
                "method": r["method"],
                "description": r["description"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
        return json.dumps({"apis": apis, "count": len(apis)})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _list_api_names() -> list:
    """Return just the names of registered APIs (internal helper)."""
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM custom_apis ORDER BY name")
        rows = cursor.fetchall()
        conn.close()
        return [r["name"] for r in rows]
    except Exception:
        return []


def get_api_descriptions() -> str:
    """Return a compact summary for system prompt injection."""
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name, description FROM custom_apis ORDER BY name")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return ""
        lines = [f"- {r['name']}: {r['description']}" for r in rows]
        return "\n".join(lines)
    except Exception:
        return ""


def delete_api(name: str) -> str:
    """Delete a registered custom API by name."""
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM custom_apis WHERE name = ?", (name,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted:
            return json.dumps({"success": True, "message": f"API '{name}' deleted."})
        return json.dumps({"error": f"No API found with name '{name}'."})
    except Exception as e:
        return json.dumps({"error": str(e)})


def execute_tool(tool_name: str, tool_args: dict) -> str:
    if tool_name == "call_api":
        return call_api(
            name=tool_args.get("name", ""),
            params=tool_args.get("params", {}),
        )
    if tool_name == "register_api":
        return register_api(
            name=tool_args.get("name", ""),
            url=tool_args.get("url", ""),
            method=tool_args.get("method", "GET"),
            headers=tool_args.get("headers"),
            body_template=tool_args.get("body_template", ""),
            description=tool_args.get("description", ""),
        )
    if tool_name == "list_apis":
        return list_apis()
    return json.dumps({"error": f"Unknown API registry tool: {tool_name}"})
