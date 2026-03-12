import os

USER_HOME = os.path.expanduser("~")
LITTLEHIVE_DIR = os.getenv("LITTLEHIVE_HOME", os.path.join(USER_HOME, ".littlehive"))

DB_DIR = os.path.join(LITTLEHIVE_DIR, "db")
CONFIG_DIR = os.path.join(LITTLEHIVE_DIR, "config")

DB_PATH = os.path.join(DB_DIR, "littlehive.db")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
TOKEN_PATH = os.path.join(CONFIG_DIR, "token.json")
CREDENTIALS_PATH = os.path.join(CONFIG_DIR, "credentials.json")


def ensure_paths():
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(os.path.join(LITTLEHIVE_DIR, "logs"), exist_ok=True)


# Create directories immediately on import so all modules
# that reference DB_PATH, CONFIG_PATH, etc. work on fresh installs.
ensure_paths()
