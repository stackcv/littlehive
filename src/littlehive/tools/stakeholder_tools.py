import sqlite3
import json
import random

from littlehive.agent.paths import DB_PATH


_FUN_FACTS = [
    "Honey never spoils — archaeologists found 3,000-year-old honey in Egyptian tombs that was still edible.",
    "Octopuses have three hearts and blue blood.",
    "A group of flamingos is called a 'flamboyance'.",
    "Bananas are berries, but strawberries aren't.",
    "The shortest war in history lasted 38 minutes (Britain vs. Zanzibar, 1896).",
    "Wombat droppings are cube-shaped.",
    "Venus is the only planet that spins clockwise.",
    "A jiffy is an actual unit of time — 1/100th of a second.",
    "The inventor of the Pringles can is buried in one.",
    "Sea otters hold hands while sleeping to keep from drifting apart.",
    "The Eiffel Tower can be 15 cm taller during summer due to thermal expansion.",
    "Scotland's national animal is the unicorn.",
    "There are more possible iterations of a game of chess than atoms in the observable universe.",
    "An astronaut's footprint on the Moon could last for 100 million years.",
    "Cows have best friends and get stressed when separated.",
]


def pick_fun_fact() -> str:
    return random.choice(_FUN_FACTS)


def _init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS stakeholders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            alias TEXT,
            email TEXT,
            phone TEXT,
            telegram TEXT,
            relationship TEXT,
            preferences TEXT,
            date_added TEXT,
            auto_respond INTEGER DEFAULT 0
        )
    """)
    # Migrate existing tables that lack auto_respond
    try:
        c.execute("ALTER TABLE stakeholders ADD COLUMN auto_respond INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


_init_db()


def add_stakeholder(
    name: str,
    alias: str = "",
    email: str = "",
    phone: str = "",
    telegram: str = "",
    relationship: str = "",
    preferences: str = "",
    auto_respond: bool = False,
) -> str:
    """Add a new stakeholder/contact to the database."""
    try:
        from datetime import datetime

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        date_added = datetime.now().isoformat()

        c.execute(
            """
            INSERT INTO stakeholders (name, alias, email, phone, telegram, relationship, preferences, date_added, auto_respond)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                name,
                alias,
                email,
                phone,
                telegram,
                relationship,
                preferences,
                date_added,
                1 if auto_respond else 0,
            ),
        )

        stakeholder_id = c.lastrowid
        conn.commit()
        conn.close()

        return json.dumps(
            {
                "status": "success",
                "message": f"Stakeholder '{name}' added successfully.",
                "stakeholder_id": stakeholder_id,
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def lookup_stakeholder(query: str) -> str:
    """Search for a stakeholder by name, alias, email, phone, telegram, or relationship."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        search_term = f"%{query}%"
        c.execute(
            """
            SELECT * FROM stakeholders 
            WHERE name LIKE ? 
               OR alias LIKE ? 
               OR email LIKE ? 
               OR phone LIKE ? 
               OR telegram LIKE ?
               OR relationship LIKE ?
        """,
            (
                search_term,
                search_term,
                search_term,
                search_term,
                search_term,
                search_term,
            ),
        )

        rows = c.fetchall()
        conn.close()

        results = [dict(row) for row in rows]
        if not results:
            return json.dumps({"message": f"No stakeholder found matching '{query}'."})
        return json.dumps({"stakeholders": results})
    except Exception as e:
        return json.dumps({"error": str(e)})


def remove_stakeholder(stakeholder_id: int) -> str:
    """Remove a stakeholder by their ID."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM stakeholders WHERE id = ?", (stakeholder_id,))
        if c.rowcount == 0:
            conn.close()
            return json.dumps(
                {"error": f"No stakeholder found with ID {stakeholder_id}"}
            )
        conn.commit()
        conn.close()
        return json.dumps(
            {
                "status": "success",
                "message": f"Stakeholder #{stakeholder_id} removed permanently.",
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def update_stakeholder(
    stakeholder_id: int,
    name: str = None,
    alias: str = None,
    email: str = None,
    phone: str = None,
    telegram: str = None,
    relationship: str = None,
    preferences: str = None,
    auto_respond: bool = None,
) -> str:
    """Update an existing stakeholder's details."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("SELECT * FROM stakeholders WHERE id = ?", (stakeholder_id,))
        if not c.fetchone():
            conn.close()
            return json.dumps(
                {"error": f"No stakeholder found with ID {stakeholder_id}"}
            )

        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if alias is not None:
            updates.append("alias = ?")
            params.append(alias)
        if email is not None:
            updates.append("email = ?")
            params.append(email)
        if phone is not None:
            updates.append("phone = ?")
            params.append(phone)
        if telegram is not None:
            updates.append("telegram = ?")
            params.append(telegram)
        if relationship is not None:
            updates.append("relationship = ?")
            params.append(relationship)
        if preferences is not None:
            updates.append("preferences = ?")
            params.append(preferences)
        if auto_respond is not None:
            updates.append("auto_respond = ?")
            params.append(1 if auto_respond else 0)

        if not updates:
            conn.close()
            return json.dumps({"error": "No fields provided to update."})

        query = f"UPDATE stakeholders SET {', '.join(updates)} WHERE id = ?"
        params.append(stakeholder_id)

        c.execute(query, tuple(params))
        conn.commit()
        conn.close()

        return json.dumps(
            {
                "status": "success",
                "message": f"Stakeholder #{stakeholder_id} updated successfully.",
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_auto_respond_contacts() -> list[dict]:
    """Return stakeholders that have auto_respond enabled, with their email and preferences."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id, name, alias, email, relationship, preferences FROM stakeholders WHERE auto_respond = 1 AND email IS NOT NULL AND email != ''"
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


STAKEHOLDER_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "add_stakeholder",
            "description": "Add a new key person/stakeholder to your relationship map. Use this when the user introduces someone new, specifies an alias, or gives preferences on how to communicate with them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Full name of the person.",
                    },
                    "alias": {
                        "type": "string",
                        "description": "Nickname or alternative name (e.g. 'Aish').",
                    },
                    "email": {"type": "string", "description": "Email address."},
                    "phone": {"type": "string", "description": "Phone number."},
                    "telegram": {
                        "type": "string",
                        "description": "Telegram handle or username.",
                    },
                    "relationship": {
                        "type": "string",
                        "description": "Role or relationship to the user (e.g., 'Wife', 'CEO', 'VIP Client').",
                    },
                    "preferences": {
                        "type": "string",
                        "description": "Specific instructions or context on how to deal with this person (e.g., 'Keep it short', 'Never schedule before 10 AM').",
                    },
                    "auto_respond": {
                        "type": "boolean",
                        "description": "Enable automatic draft-and-approve replies for emails from this person. Default false.",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_stakeholder",
            "description": "Search the stakeholder relationship map to get exact details like email, phone, relationship, and communication preferences for a person. STRICT RULE: Always use this tool FIRST to get a person's exact email address before using search_emails. Never search Gmail using just a first name or alias (like 'from:Aish'), as it will miss emails. Get their exact email from here first, then search Gmail with 'from:exact@email.com'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Name, alias, email, or role to search for (e.g., 'Aish', 'Boss', 'david@company.com').",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_stakeholder",
            "description": "Delete a person from the stakeholder relationship map. Use this if the user asks to forget someone or remove a redundant entry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "stakeholder_id": {
                        "type": "integer",
                        "description": "The numeric ID of the stakeholder to remove. Use lookup_stakeholder first to find their ID if you don't know it.",
                    }
                },
                "required": ["stakeholder_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_stakeholder",
            "description": "Update an existing person/stakeholder in your relationship map. Use this to change their preferences, email, phone, alias, or auto-respond setting. You MUST use lookup_stakeholder first to get their exact stakeholder_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "stakeholder_id": {
                        "type": "integer",
                        "description": "The numeric ID of the stakeholder to update.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Full name of the person (optional).",
                    },
                    "alias": {
                        "type": "string",
                        "description": "Nickname or alternative name (optional).",
                    },
                    "email": {
                        "type": "string",
                        "description": "Email address (optional).",
                    },
                    "phone": {
                        "type": "string",
                        "description": "Phone number (optional).",
                    },
                    "telegram": {
                        "type": "string",
                        "description": "Telegram handle (optional).",
                    },
                    "relationship": {
                        "type": "string",
                        "description": "Role or relationship (optional).",
                    },
                    "preferences": {
                        "type": "string",
                        "description": "Specific instructions or context on how to deal with this person (optional).",
                    },
                    "auto_respond": {
                        "type": "boolean",
                        "description": "Enable or disable automatic draft-and-approve replies for this person (optional).",
                    },
                },
                "required": ["stakeholder_id"],
            },
        },
    },
]


def execute_tool(name: str, args: dict) -> str:
    funcs = {
        "add_stakeholder": add_stakeholder,
        "lookup_stakeholder": lookup_stakeholder,
        "remove_stakeholder": remove_stakeholder,
        "update_stakeholder": update_stakeholder,
    }
    return (
        funcs[name](**args) if name in funcs else json.dumps({"error": "Unknown tool"})
    )
