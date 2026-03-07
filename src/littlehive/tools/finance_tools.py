import sqlite3
import json
from datetime import datetime

from littlehive.agent.paths import DB_PATH


def _init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor TEXT NOT NULL,
            amount REAL NOT NULL,
            due_date TEXT,
            invoice_number TEXT,
            status TEXT DEFAULT 'pending',
            date_added TEXT
        )
    """)
    conn.commit()
    conn.close()


_init_db()


def add_bill(
    vendor: str, amount: float, due_date: str, invoice_number: str = "Unknown"
) -> str:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        date_added = datetime.now().isoformat()
        c.execute(
            """
            INSERT INTO bills (vendor, amount, due_date, invoice_number, status, date_added)
            VALUES (?, ?, ?, ?, 'pending', ?)
        """,
            (vendor, amount, due_date, invoice_number, date_added),
        )
        bill_id = c.lastrowid
        conn.commit()
        conn.close()
        return json.dumps(
            {
                "status": "success",
                "message": "Bill recorded successfully.",
                "bill_id": bill_id,
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def list_bills(status: str = "pending") -> str:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if status.lower() == "all":
            c.execute("SELECT * FROM bills ORDER BY due_date ASC")
        else:
            c.execute(
                "SELECT * FROM bills WHERE status = ? ORDER BY due_date ASC",
                (status.lower(),),
            )

        rows = c.fetchall()
        conn.close()

        bills = [dict(row) for row in rows]
        if not bills:
            return json.dumps({"message": f"No {status} bills found."})
        return json.dumps({"bills": bills})
    except Exception as e:
        return json.dumps({"error": str(e)})


def mark_bill_paid(bill_id: int) -> str:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bills SET status = 'paid' WHERE id = ?", (bill_id,))
        if c.rowcount == 0:
            conn.close()
            return json.dumps({"error": f"No bill found with ID {bill_id}"})
        conn.commit()
        conn.close()
        return json.dumps(
            {"status": "success", "message": f"Bill #{bill_id} marked as paid."}
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def delete_bill(bill_id: int) -> str:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
        if c.rowcount == 0:
            conn.close()
            return json.dumps({"error": f"No bill found with ID {bill_id}"})
        conn.commit()
        conn.close()
        return json.dumps(
            {"status": "success", "message": f"Bill #{bill_id} deleted permanently."}
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


FINANCE_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "add_bill",
            "description": "Record a new pending bill or invoice to the database. Use this when you detect an incoming bill in the user's email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vendor": {
                        "type": "string",
                        "description": "Name of the company or service.",
                    },
                    "amount": {
                        "type": "number",
                        "description": "The total amount due.",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "The due date in YYYY-MM-DD format if known, otherwise best guess.",
                    },
                    "invoice_number": {
                        "type": "string",
                        "description": "The invoice or account number, if available.",
                    },
                },
                "required": ["vendor", "amount", "due_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_bills",
            "description": "Retrieve a list of tracked bills. Use this to check pending liabilities or find a bill ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["pending", "paid", "all"],
                        "description": "Filter by status. Default is pending.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_bill_paid",
            "description": "Mark a specific bill as paid in the database. Use this when you detect a payment receipt in the user's email or when the user explicitly says they paid it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bill_id": {
                        "type": "integer",
                        "description": "The numeric ID of the bill to mark as paid.",
                    }
                },
                "required": ["bill_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_bill",
            "description": "Delete a bill from the database permanently. Use this when the user asks to remove, archive, or ignore a false/placeholder bill entry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bill_id": {
                        "type": "integer",
                        "description": "The numeric ID of the bill to delete.",
                    }
                },
                "required": ["bill_id"],
            },
        },
    },
]


def execute_tool(name: str, args: dict) -> str:
    funcs = {
        "add_bill": add_bill,
        "list_bills": list_bills,
        "mark_bill_paid": mark_bill_paid,
        "delete_bill": delete_bill,
    }
    return (
        funcs[name](**args) if name in funcs else json.dumps({"error": "Unknown tool"})
    )
