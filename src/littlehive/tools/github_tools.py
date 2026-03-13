"""
GitHub integration tools for LittleHive.
Uses the GitHub REST API directly via requests — no extra dependencies.
"""

import json

import requests
from littlehive.agent.config import get_config
from littlehive.agent.logger_setup import logger

API_BASE = "https://api.github.com"


def _headers() -> dict:
    config = get_config()
    token = config.get("github_token", "")
    if not token:
        return {}
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _resolve_repo(repo: str | None) -> str | None:
    """Return the repo in 'owner/name' format, falling back to config default."""
    if repo:
        return repo
    config = get_config()
    return config.get("github_default_repo", "")


GITHUB_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "github_create_issue",
            "description": (
                "Create a new issue on a GitHub repository. "
                "Requires a title. Body, labels, and assignees are optional."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Issue title.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Issue body / description (markdown).",
                    },
                    "repo": {
                        "type": "string",
                        "description": "Repository in 'owner/repo' format. Uses default repo if omitted.",
                    },
                    "labels": {
                        "type": "string",
                        "description": "Comma-separated label names (e.g. 'bug,urgent').",
                    },
                    "assignees": {
                        "type": "string",
                        "description": "Comma-separated GitHub usernames to assign.",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_list_issues",
            "description": (
                "List issues from a GitHub repository. "
                "Returns up to 10 issues matching the filters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository in 'owner/repo' format. Uses default repo if omitted.",
                    },
                    "state": {
                        "type": "string",
                        "description": "Filter by state: 'open', 'closed', or 'all'. Default 'open'.",
                    },
                    "labels": {
                        "type": "string",
                        "description": "Comma-separated label names to filter by.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_update_issue",
            "description": (
                "Update an existing GitHub issue. Can change title, body, "
                "state (open/closed), labels, or assignees."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_number": {
                        "type": "integer",
                        "description": "The issue number to update.",
                    },
                    "repo": {
                        "type": "string",
                        "description": "Repository in 'owner/repo' format. Uses default repo if omitted.",
                    },
                    "state": {
                        "type": "string",
                        "description": "Set to 'open' or 'closed'.",
                    },
                    "title": {
                        "type": "string",
                        "description": "New title for the issue.",
                    },
                    "body": {
                        "type": "string",
                        "description": "New body for the issue.",
                    },
                    "labels": {
                        "type": "string",
                        "description": "Comma-separated label names to set.",
                    },
                },
                "required": ["issue_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_add_comment",
            "description": (
                "Add a comment to an existing GitHub issue or pull request."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_number": {
                        "type": "integer",
                        "description": "The issue or PR number.",
                    },
                    "body": {
                        "type": "string",
                        "description": "The comment text (markdown supported).",
                    },
                    "repo": {
                        "type": "string",
                        "description": "Repository in 'owner/repo' format. Uses default repo if omitted.",
                    },
                },
                "required": ["issue_number", "body"],
            },
        },
    },
]


def _check_token() -> str | None:
    """Return an error JSON string if the token is missing, else None."""
    hdrs = _headers()
    if not hdrs:
        return json.dumps({
            "error": "GitHub token not configured. Set it in Settings > GitHub."
        })
    return None


def github_create_issue(
    title: str,
    body: str = "",
    repo: str = None,
    labels: str = "",
    assignees: str = "",
) -> str:
    err = _check_token()
    if err:
        return err

    repo = _resolve_repo(repo)
    if not repo:
        return json.dumps({"error": "No repository specified and no default repo configured."})

    payload = {"title": title}
    if body:
        payload["body"] = body
    if labels:
        payload["labels"] = [lbl.strip() for lbl in labels.split(",") if lbl.strip()]
    if assignees:
        payload["assignees"] = [a.strip() for a in assignees.split(",") if a.strip()]

    try:
        resp = requests.post(
            f"{API_BASE}/repos/{repo}/issues",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"[GitHub] Created issue #{data['number']} in {repo}")
        return json.dumps({
            "success": True,
            "issue_number": data["number"],
            "title": data["title"],
            "url": data["html_url"],
            "state": data["state"],
        })
    except requests.RequestException as e:
        logger.warning(f"[GitHub] Create issue failed: {e}")
        error_body = ""
        if hasattr(e, "response") and e.response is not None:
            error_body = e.response.text[:300]
        return json.dumps({"error": f"GitHub API error: {e}", "details": error_body})


def github_list_issues(
    repo: str = None,
    state: str = "open",
    labels: str = "",
) -> str:
    err = _check_token()
    if err:
        return err

    repo = _resolve_repo(repo)
    if not repo:
        return json.dumps({"error": "No repository specified and no default repo configured."})

    params = {"state": state or "open", "per_page": 10, "sort": "updated", "direction": "desc"}
    if labels:
        params["labels"] = labels

    try:
        resp = requests.get(
            f"{API_BASE}/repos/{repo}/issues",
            headers=_headers(),
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()

        issues = []
        for item in raw:
            if item.get("pull_request"):
                continue
            issues.append({
                "number": item["number"],
                "title": item["title"],
                "state": item["state"],
                "labels": [lbl["name"] for lbl in item.get("labels", [])],
                "assignees": [a["login"] for a in item.get("assignees", [])],
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
                "url": item["html_url"],
            })

        return json.dumps({"repo": repo, "state": state, "issues": issues, "count": len(issues)})
    except requests.RequestException as e:
        logger.warning(f"[GitHub] List issues failed: {e}")
        return json.dumps({"error": f"GitHub API error: {e}"})


def github_update_issue(
    issue_number: int,
    repo: str = None,
    state: str = None,
    title: str = None,
    body: str = None,
    labels: str = None,
) -> str:
    err = _check_token()
    if err:
        return err

    repo = _resolve_repo(repo)
    if not repo:
        return json.dumps({"error": "No repository specified and no default repo configured."})

    payload = {}
    if state:
        payload["state"] = state
    if title:
        payload["title"] = title
    if body:
        payload["body"] = body
    if labels is not None:
        payload["labels"] = [lbl.strip() for lbl in labels.split(",") if lbl.strip()]

    if not payload:
        return json.dumps({"error": "Nothing to update — provide at least one field to change."})

    try:
        resp = requests.patch(
            f"{API_BASE}/repos/{repo}/issues/{issue_number}",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"[GitHub] Updated issue #{issue_number} in {repo}")
        return json.dumps({
            "success": True,
            "issue_number": data["number"],
            "title": data["title"],
            "state": data["state"],
            "url": data["html_url"],
        })
    except requests.RequestException as e:
        logger.warning(f"[GitHub] Update issue failed: {e}")
        error_body = ""
        if hasattr(e, "response") and e.response is not None:
            error_body = e.response.text[:300]
        return json.dumps({"error": f"GitHub API error: {e}", "details": error_body})


def github_add_comment(
    issue_number: int,
    body: str,
    repo: str = None,
) -> str:
    err = _check_token()
    if err:
        return err

    repo = _resolve_repo(repo)
    if not repo:
        return json.dumps({"error": "No repository specified and no default repo configured."})

    if not body or not body.strip():
        return json.dumps({"error": "Comment body cannot be empty."})

    try:
        resp = requests.post(
            f"{API_BASE}/repos/{repo}/issues/{issue_number}/comments",
            headers=_headers(),
            json={"body": body},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"[GitHub] Added comment to #{issue_number} in {repo}")
        return json.dumps({
            "success": True,
            "comment_id": data["id"],
            "issue_number": issue_number,
            "url": data["html_url"],
        })
    except requests.RequestException as e:
        logger.warning(f"[GitHub] Add comment failed: {e}")
        return json.dumps({"error": f"GitHub API error: {e}"})


def execute_tool(tool_name: str, tool_args: dict) -> str:
    if tool_name == "github_create_issue":
        return github_create_issue(
            title=tool_args.get("title", ""),
            body=tool_args.get("body", ""),
            repo=tool_args.get("repo"),
            labels=tool_args.get("labels", ""),
            assignees=tool_args.get("assignees", ""),
        )
    elif tool_name == "github_list_issues":
        return github_list_issues(
            repo=tool_args.get("repo"),
            state=tool_args.get("state", "open"),
            labels=tool_args.get("labels", ""),
        )
    elif tool_name == "github_update_issue":
        return github_update_issue(
            issue_number=tool_args.get("issue_number", 0),
            repo=tool_args.get("repo"),
            state=tool_args.get("state"),
            title=tool_args.get("title"),
            body=tool_args.get("body"),
            labels=tool_args.get("labels"),
        )
    elif tool_name == "github_add_comment":
        return github_add_comment(
            issue_number=tool_args.get("issue_number", 0),
            body=tool_args.get("body", ""),
            repo=tool_args.get("repo"),
        )
    else:
        return json.dumps({"error": f"Unknown GitHub tool: {tool_name}"})
