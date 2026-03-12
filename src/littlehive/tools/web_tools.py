import json
from littlehive.agent.logger_setup import logger


WEB_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information. Use this for recent events, "
                "news, prices, live scores, weather, or any fact you are not confident about. "
                "Returns titles and short snippets from top results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query (e.g. 'latest car launches 2026 India').",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results to return (default 3, max 5).",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def web_search(query: str, max_results: int = 3) -> str:
    """Search the web via DuckDuckGo and return compact results."""
    max_results = min(max_results or 3, 5)
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))

        if not raw:
            return json.dumps({"results": [], "message": "No results found."})

        results = []
        for r in raw:
            results.append({
                "title": r.get("title", ""),
                "snippet": (r.get("body") or "")[:250],
                "url": r.get("href", ""),
            })

        return json.dumps({"query": query, "results": results})

    except ImportError:
        return json.dumps({
            "error": "The 'ddgs' package is not installed. Run: pip install ddgs"
        })
    except Exception as e:
        logger.warning(f"[WebSearch] Failed: {e}")
        return json.dumps({"error": f"Search failed: {str(e)}"})


def execute_tool(tool_name: str, tool_args: dict) -> str:
    if tool_name == "web_search":
        return web_search(
            query=tool_args.get("query", ""),
            max_results=tool_args.get("max_results", 3),
        )
    return json.dumps({"error": f"Unknown web tool: {tool_name}"})
