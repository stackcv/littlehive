import os
from littlehive.agent.logger_setup import logger
import sys
import warnings
import logging
from io import StringIO

# Aggressively suppress warnings and logs
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["MLX_DISABLE_PROGRESS_BAR"] = "1"
os.environ["TQDM_DISABLE"] = "1"

warnings.filterwarnings("ignore")

# Force internal loggers to be quiet
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("semantic_router").setLevel(logging.ERROR)

from semantic_router import Route, SemanticRouter
from semantic_router.encoders import HuggingFaceEncoder
import semantic_router.utils.logger

semantic_router.utils.logger.logger.setLevel(logging.ERROR)

from littlehive.agent.tool_registry import ROUTE_SCHEMAS

# 1. Define Routes based on user utterances
# As you add more tools, create a new Route and add it to the `routes` list.
calendar_route = Route(
    name="calendar",
    utterances=[
        "schedule a meeting",
        "what is on my agenda?",
        "book a time",
        "check my calendar",
        "when am I free?",
        "do I have any meetings today?",
        "create an event",
        "upcoming events",
        "add to my calendar",
        "whats on my calendar for today",
        "show me my schedule",
        "what's my day look like",
        "any appointments right now",
        "do I have anything planned",
        "cancel my meeting",
        "delete an event",
        "remove this from my calendar",
        "can you cancel my",
        "reschedule my appointment",
        "update my meeting",
        "change the time of my",
        "cancel my health slot",
        "cancel my appointment",
        "clear my afternoon",
    ],
)

email_route = Route(
    name="email",
    utterances=[
        "check my email",
        "any new emails",
        "read my messages",
        "send an email to",
        "reply to that email",
        "archive my newsletters",
        "mark as read",
        "did I get any messages from",
        "read the email from",
        "draft an email",
        "check my inbox",
        "clear my inbox",
        "trash that email",
    ],
)

finance_route = Route(
    name="finance",
    utterances=[
        "i got a new bill",
        "record this invoice",
        "save this bill",
        "what bills do I owe?",
        "how much are my pending bills?",
        "did I pay my AWS bill?",
        "mark this bill as paid",
        "I just paid the verizon bill",
        "show me my liabilities",
        "track this payment",
    ],
)

reminder_route = Route(
    name="reminder",
    utterances=[
        "remind me to",
        "set a reminder",
        "remind me tomorrow about",
        "what are my reminders",
        "show my pending tasks",
        "I finished that reminder",
        "mark the reminder as done",
        "I paid the bill, you can close the reminder",
        "delete reminder",
        "wake me up at",
        "ping me later about",
    ],
)

memory_route = Route(
    name="memory",
    utterances=[
        "remember that",
        "save this fact",
        "my sister is",
        "i prefer to",
        "never forget that",
        "what did we talk about yesterday",
        "did I ask you about",
        "search your memory",
        "what was the name of that",
        "do you remember when",
        "who is my",
        "what is my favorite",
    ],
)

web_route = Route(
    name="web",
    utterances=[
        "search the web",
        "google this",
        "look it up online",
        "what is the latest news",
        "what happened today in the world",
        "current weather",
        "latest car launches",
        "search for information about",
        "find out about",
        "what is trending",
        "news about",
        "recent developments in",
        "who won the match",
        "live score",
        "stock price of",
        "what time is it in",
        "convert currency",
        "how much does",
        "best restaurants near",
        "flight status",
    ],
)

routes = [calendar_route, email_route, finance_route, reminder_route, memory_route, web_route]

# 2. Initialize the ultra-fast local embedding model
logger.info(
    "Loading semantic router encoder (sentence-transformers/all-MiniLM-L6-v2)..."
)

# Capture stdout and stderr to silence MLX and HuggingFace C++ level load reports
old_stdout = sys.stdout
old_stderr = sys.stderr
sys.stdout = StringIO()
sys.stderr = StringIO()

try:
    encoder = HuggingFaceEncoder(name="sentence-transformers/all-MiniLM-L6-v2")
finally:
    # Restore stdout and stderr immediately after loading
    sys.stdout = old_stdout
    sys.stderr = old_stderr

# 3. Create the router layer and explicitly add routes to populate the index
# We pass top_k=1 and we can lower the threshold to make it trigger more easily.
# By default, semantic router is quite strict. Let's make it more flexible.
router_layer = SemanticRouter(encoder=encoder)
router_layer.add(routes)
# 0.4 is a good general threshold. Default is often higher depending on the encoder.
router_layer.set_threshold(0.3)


def get_active_tools(user_input: str) -> list:
    """
    Takes the user's input, finds the most semantically relevant persona,
    and returns the corresponding tool schemas from the registry.
    Defaults to the EA Persona tools to ensure core functionality is always available.
    """
    route_choice = router_layer(user_input)

    # If we matched a specific persona route (e.g., developer, system) use those tools
    if route_choice and route_choice.name in ROUTE_SCHEMAS:
        return ROUTE_SCHEMAS[route_choice.name]

    # Default to the core EA Persona if no specific route is matched,
    # or if we are just having a normal conversation (Mistral will just ignore the tools).
    # We grab it from any of the EA routes since they all point to the EA_PERSONA_TOOLS bundle now.
    return ROUTE_SCHEMAS["email"]
