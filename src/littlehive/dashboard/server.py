import http.server
from littlehive.agent.logger_setup import logger
import socketserver
import json
import sqlite3
import os
import threading
import webbrowser
import time
import queue

# Resolve paths
from littlehive.agent.paths import DB_PATH, CONFIG_PATH, TOKEN_PATH

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))


def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    inbox = None
    outbox = None

    def log_message(self, format, *args):
        # Suppress logging to keep the console clean
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DASHBOARD_DIR, **kwargs)

    def end_headers(self):
        if self.path.startswith("/api/"):
            self.send_header(
                "Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"
            )
        super().end_headers()

    def do_GET(self):
        if self.path == "/api/dashboard":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()

            try:
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = dict_factory
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='bills'"
                )
                if cursor.fetchone():
                    cursor.execute(
                        "SELECT * FROM bills WHERE status != 'paid' ORDER BY due_date ASC"
                    )
                    bills = cursor.fetchall()
                else:
                    bills = []

                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='reminders'"
                )
                if cursor.fetchone():
                    cursor.execute(
                        "SELECT * FROM reminders WHERE status = 'pending' ORDER BY priority DESC, deadline ASC"
                    )
                    reminders = cursor.fetchall()
                else:
                    reminders = []

                conn.close()

                # Fetch unread emails
                unread_emails = []
                try:

                    from littlehive.tools.email_tools import search_emails

                    email_res_str = search_emails(
                        query="is:unread in:inbox", max_results=5
                    )
                    email_res = json.loads(email_res_str)
                    unread_emails = email_res.get("emails", [])
                except Exception:
                    pass

                self.wfile.write(
                    json.dumps(
                        {
                            "bills": bills,
                            "reminders": reminders,
                            "emails": unread_emails,
                        }
                    ).encode()
                )
            except Exception as e:
                self.wfile.write(
                    json.dumps(
                        {"error": str(e), "bills": [], "reminders": [], "emails": []}
                    ).encode()
                )
            return

        elif self.path == "/api/health":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
            return

        elif self.path == "/api/chat/poll":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            if self.outbox:
                try:
                    # Wait up to 30 seconds for a new message
                    msg = self.outbox.get(timeout=30)
                    self.wfile.write(json.dumps(msg).encode())
                except queue.Empty:
                    # Return empty response to let client reconnect
                    self.wfile.write(json.dumps({}).encode())
            else:
                self.wfile.write(json.dumps({"error": "No outbox queue"}).encode())
            return

        elif self.path == "/api/memories":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()

            try:
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = dict_factory
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='core_memory'"
                )
                if cursor.fetchone():
                    cursor.execute(
                        "SELECT id, fact_text, datetime(timestamp, 'localtime') as timestamp FROM core_memory ORDER BY timestamp DESC"
                    )
                    memories = cursor.fetchall()
                else:
                    memories = []

                conn.close()
                self.wfile.write(json.dumps({"memories": memories}).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e), "memories": []}).encode())
            return

        elif self.path == "/api/contacts":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()

            try:
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = dict_factory
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='stakeholders'"
                )
                if cursor.fetchone():
                    cursor.execute("SELECT * FROM stakeholders ORDER BY name ASC")
                    contacts = cursor.fetchall()
                else:
                    contacts = []

                conn.close()
                self.wfile.write(json.dumps(contacts).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        elif self.path == "/api/tools":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()

            try:

                from littlehive.agent.tool_registry import ROUTE_SCHEMAS

                tools_list = []
                for route, schemas in ROUTE_SCHEMAS.items():
                    for schema in schemas:
                        tools_list.append(
                            {
                                "name": schema["function"]["name"],
                                "description": schema["function"]["description"],
                                "category": route,
                            }
                        )

                self.wfile.write(json.dumps(tools_list).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        elif self.path == "/api/config":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()

            try:
                with open(CONFIG_PATH, "r") as f:
                    config = json.load(f)

                # Check for google auth token
                config["has_google_auth"] = os.path.exists(TOKEN_PATH)

                self.wfile.write(json.dumps(config).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/chat/send":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data.decode("utf-8"))
                user_msg = data.get("message", "")

                if self.inbox and user_msg.strip():
                    self.inbox.put({"source": "web", "text": user_msg})

                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        elif self.path == "/api/contacts":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode("utf-8"))
                from littlehive.tools.stakeholder_tools import add_stakeholder

                res = add_stakeholder(
                    name=data.get("name", ""),
                    alias=data.get("alias", ""),
                    email=data.get("email", ""),
                    phone=data.get("phone", ""),
                    telegram=data.get("telegram", ""),
                    relationship=data.get("relationship", ""),
                    preferences=data.get("preferences", ""),
                )
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(res.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        elif self.path == "/api/config":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)

            try:
                new_config = json.loads(post_data.decode("utf-8"))
                if "has_google_auth" in new_config:
                    del new_config["has_google_auth"]

                with open(CONFIG_PATH, "r") as f:
                    config = json.load(f)

                config.update(new_config)

                with open(CONFIG_PATH, "w") as f:
                    json.dump(config, f, indent=4)

                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

    def do_PUT(self):
        if self.path.startswith("/api/contacts/"):
            try:
                stakeholder_id = int(self.path.split("/")[-1])
                content_length = int(self.headers["Content-Length"])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode("utf-8"))

                from littlehive.tools.stakeholder_tools import update_stakeholder

                res = update_stakeholder(
                    stakeholder_id=stakeholder_id,
                    name=data.get("name"),
                    alias=data.get("alias"),
                    email=data.get("email"),
                    phone=data.get("phone"),
                    telegram=data.get("telegram"),
                    relationship=data.get("relationship"),
                    preferences=data.get("preferences"),
                )
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(res.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        if self.path.startswith("/api/contacts/"):
            try:
                stakeholder_id = int(self.path.split("/")[-1])
                from littlehive.tools.stakeholder_tools import remove_stakeholder

                res = remove_stakeholder(stakeholder_id)
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(res.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        self.send_response(404)
        self.end_headers()


def start_dashboard_server(port=8080, inbox=None, outbox=None):
    DashboardHandler.inbox = inbox
    DashboardHandler.outbox = outbox

    try:
        httpd = ThreadedHTTPServer(("", port), DashboardHandler)
        logger.info(f"[Dashboard] Running on http://localhost:{port}")

        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()

        time.sleep(1)
        webbrowser.open(f"http://localhost:{port}")

    except OSError as e:
        logger.error(f"[Dashboard] Could not start server on port {port}: {e}")


if __name__ == "__main__":
    start_dashboard_server()
    # Keep main thread alive if run directly
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
