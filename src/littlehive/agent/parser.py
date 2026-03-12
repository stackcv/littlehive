import json
import re

def parse_mistral_tool_calls(response_text):
    """
    Standard parser for Mistral [TOOL_CALLS] output.
    Cleans up hallucinations and validates function names.
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
            if "[ARGS]" in block:
                func_name, args_str = block.split("[ARGS]")
                func_name = func_name.strip()
                args_str = args_str.strip()

                # Basic validation: function names should only have [a-zA-Z0-9_-]
                if not re.match(r"^[a-zA-Z0-9_-]+$", func_name):
                    continue

                try:
                    args_dict = json.loads(args_str)
                    calls.append({"name": func_name, "arguments": args_dict})
                except json.JSONDecodeError:
                    # In some cases, Mistral might output parameterless tools without a proper JSON object
                    # or it might have hallucinated XML/trailing text.
                    # If it's a valid function name but failed JSON, we try a fallback.
                    calls.append({"name": func_name, "arguments": {}})
            else:
                # Parameterless tool call without [ARGS]
                func_name = block.strip()
                if re.match(r"^[a-zA-Z0-9_-]+$", func_name):
                    calls.append({"name": func_name, "arguments": {}})
        except Exception:
            continue

    return calls
