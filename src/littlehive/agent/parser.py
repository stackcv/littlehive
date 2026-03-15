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


def _extract_first_json_object(text: str) -> str | None:
    """Extract the first balanced JSON object from a string."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None


def _parse_args_dict(func_name: str, args_str: str) -> dict | None:
    """Parse function args into a dict, with repair/extraction fallbacks."""
    args_str = args_str.strip()

    # Best case: proper JSON object string
    try:
        parsed = json.loads(args_str)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Try repaired JSON directly
    repaired = _repair_json(args_str)
    if isinstance(repaired, dict):
        return repaired

    # Try extracting the first balanced object and parsing that
    extracted = _extract_first_json_object(args_str)
    if extracted:
        try:
            parsed = json.loads(extracted)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            repaired = _repair_json(extracted)
            if isinstance(repaired, dict):
                return repaired

    logger.warning(
        f"[Parser] Failed to parse args for '{func_name}': {args_str[:200]}"
    )
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
                                parsed_args = _parse_args_dict(item["name"], args)
                                args = parsed_args if parsed_args is not None else {}
                            calls.append({"name": item["name"], "arguments": args})
                    continue

            # Format 2: func_name[ARGS]{...}
            if "[ARGS]" in block:
                markers = list(re.finditer(r"([a-zA-Z0-9_-]+)\[ARGS\]", block))
                if markers:
                    for i, marker in enumerate(markers):
                        func_name = marker.group(1).strip()
                        if not re.match(r"^[a-zA-Z0-9_-]+$", func_name):
                            continue

                        args_start = marker.end()
                        args_end = (
                            markers[i + 1].start()
                            if i + 1 < len(markers)
                            else len(block)
                        )
                        args_str = block[args_start:args_end].strip()
                        args_dict = _parse_args_dict(func_name, args_str)
                        if args_dict is None:
                            continue

                        calls.append({"name": func_name, "arguments": args_dict})
                else:
                    # Fallback to single split behavior
                    func_name, args_str = block.split("[ARGS]", 1)
                    func_name = func_name.strip()
                    args_str = args_str.strip()
                    if not re.match(r"^[a-zA-Z0-9_-]+$", func_name):
                        continue
                    args_dict = _parse_args_dict(func_name, args_str)
                    if args_dict is None:
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
