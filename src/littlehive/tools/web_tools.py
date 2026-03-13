import json
import re
from html import unescape
from urllib.parse import urlparse

import requests
from littlehive.agent.logger_setup import logger

MAX_EXTRACT_CHARS = 3000
MIN_ACCEPTABLE_EXTRACT_CHARS = 250
BROWSER_LIKE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

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
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": (
                "Fetches a webpage URL and extracts the main text content. "
                "Use this when the user gives you a URL and asks you to read, "
                "summarize, or analyze a webpage. Returns clean text, not raw HTML."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL to fetch (e.g. 'https://stackcv.com').",
                    },
                },
                "required": ["url"],
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


def fetch_webpage(url: str) -> str:
    """Fetch a URL and extract clean text content using trafilatura."""
    if not url or not url.startswith(("http://", "https://")):
        return json.dumps({"error": "Invalid URL. Must start with http:// or https://"})

    try:
        from trafilatura import fetch_url, extract

        def _extract_clean_text(html_or_text: str) -> str:
            text = extract(
                html_or_text,
                include_comments=False,
                include_tables=True,
                output_format="txt",
                favor_recall=True,
            )
            return (text or "").strip()

        def _rough_html_to_text(html: str) -> str:
            no_script = re.sub(
                r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S
            )
            no_tags = re.sub(r"<[^>]+>", " ", no_script)
            plain = unescape(no_tags)
            plain = re.sub(r"\s+", " ", plain).strip()
            return plain

        logger.info(f"[WebFetch] Fetching: {url}")
        downloaded = fetch_url(url)

        text = _extract_clean_text(downloaded or "")
        fetched_via = "trafilatura"

        needs_fallback = downloaded is None or len(text) < MIN_ACCEPTABLE_EXTRACT_CHARS
        if needs_fallback:
            parsed = urlparse(url)
            headers = dict(BROWSER_LIKE_HEADERS)
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
            try:
                response = requests.get(url, headers=headers, timeout=12)
                if response.status_code == 200 and response.text:
                    fallback_text = _extract_clean_text(response.text)
                    if len(fallback_text) > len(text):
                        text = fallback_text
                        fetched_via = "requests-browser-headers"

                    if len(text) < MIN_ACCEPTABLE_EXTRACT_CHARS:
                        rough_text = _rough_html_to_text(response.text)
                        if len(rough_text) > len(text):
                            text = rough_text
                            fetched_via = "requests-rough-html"
                else:
                    logger.info(
                        f"[WebFetch] Fallback HTTP status for {url}: {response.status_code}"
                    )
            except Exception as fallback_error:
                logger.info(
                    f"[WebFetch] Fallback request failed for {url}: {fallback_error}"
                )

        if not text or not text.strip():
            return json.dumps({
                "url": url,
                "error": (
                    "Could not extract useful page text. "
                    "The site may block bots or rely heavily on JavaScript rendering."
                ),
            })

        truncated = len(text) > MAX_EXTRACT_CHARS
        clean_text = text[:MAX_EXTRACT_CHARS]

        result = {"url": url, "content": clean_text, "fetched_via": fetched_via}
        if truncated:
            result["note"] = (
                f"Content truncated to {MAX_EXTRACT_CHARS} chars "
                f"(full page was {len(text)} chars)."
            )
        logger.info(
            f"[WebFetch] Extracted {len(clean_text)} chars from {url}"
            f"{' (truncated)' if truncated else ''}"
        )
        return json.dumps(result)

    except ImportError:
        return json.dumps({
            "error": "The 'trafilatura' package is not installed. Run: pip install trafilatura"
        })
    except Exception as e:
        logger.warning(f"[WebFetch] Failed for {url}: {e}")
        return json.dumps({"url": url, "error": f"Extraction failed: {str(e)}"})


def execute_tool(tool_name: str, tool_args: dict) -> str:
    if tool_name == "web_search":
        return web_search(
            query=tool_args.get("query", ""),
            max_results=tool_args.get("max_results", 3),
        )
    if tool_name == "fetch_webpage":
        return fetch_webpage(url=tool_args.get("url", ""))
    return json.dumps({"error": f"Unknown web tool: {tool_name}"})
