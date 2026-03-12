import json
import re

from littlehive.agent.logger_setup import logger


def _repair_json(text: str) -> dict | None:
    """Attempt to repair common JSON issues from LLM output."""
    text = text.strip()

    # Strip trailing incomplete content (truncated generation)
    if text.count('"') % 2 != 0:
        last_quote = text.rfind('"')
        text = text[:last_quote + 1]

    # Try to close unclosed braces/brackets
    open_braces = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")
    text += "}" * max(0, open_braces)
    text += "]" * max(0, open_brackets)

    # Remove trailing commas before closing braces
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def parse_mistral_tool_calls(response_text):
    """
    Standard parser for Mistral [TOOL_CALLS] output.
    Handles both [ARGS]-separated format and JSON array format.
    """
    if "[TOOL_CALLS]" not in response_text:
        return []

    clean_text = response_text.replace("</s>", "").strip()
    blocks = clean_text.split("[TOOL_CALLS]")
    calls = []

    for block in blocks[1:]:
        block = block.strip()
        if not block:
            continue

        try:
            # Format 1: JSON array — [{"name": "...", "arguments": {...}}]
            if block.startswith("["):
                parsed = _repair_json(block)
                if parsed is None:
                    parsed = json.loads(block)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict) and "name" in item:
                            args = item.get("arguments", {})
                            if isinstance(args, str):
                                args = json.loads(args)
                            calls.append({"name": item["name"], "arguments": args})
                    continue

            # Format 2: func_name[ARGS]{...}
            if "[ARGS]" in block:
                func_name, args_str = block.split("[ARGS]", 1)
                func_name = func_name.strip()
                args_str = args_str.strip()

                if not re.match(r"^[a-zA-Z0-9_-]+$", func_name):
                    continue

                try:
                    args_dict = json.loads(args_str)
                except json.JSONDecodeError:
                    args_dict = _repair_json(args_str)
                    if args_dict is None:
                        logger.warning(
                            f"[Parser] Failed to parse args for '{func_name}': {args_str[:200]}"
                        )
                        continue

                calls.append({"name": func_name, "arguments": args_dict})
            else:
                # Parameterless tool call
                func_name = block.strip()
                if re.match(r"^[a-zA-Z0-9_-]+$", func_name):
                    calls.append({"name": func_name, "arguments": {}})
        except Exception as e:
            logger.warning(f"[Parser] Exception parsing tool call block: {e}")
            continue

    return calls
