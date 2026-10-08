"""Read Jira Cloud issues using the enhanced, token-paginated search API."""
from urllib.parse import urlsplit

import httpx

from kedb.application.incidents import incident_from_row


def jira_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "text" in value:
            return value["text"]
        if value.get("type") == "hardBreak":
            return "\n"
        if "content" in value:
            text = "".join(jira_text(node) for node in value["content"])
            return text + ("\n" if value.get("type") in {"paragraph", "heading", "listItem"} else "")
        return value.get("name", "")
    raise ValueError("Unsupported Jira text field")


def fetch_incidents(settings, jql=None):
    base = settings.jira_base_url.rstrip("/")
    url = urlsplit(base)
    if url.scheme != "https" or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError("Set JIRA_BASE_URL to your Jira Cloud HTTPS URL")
    if not settings.jira_email or not settings.jira_api_token:
        raise ValueError("Configure JIRA_EMAIL and JIRA_API_TOKEN on the server")
    query = (jql or settings.jira_jql).strip()
    if not query:
        raise ValueError("A Jira JQL query is required")
    resolution_field = settings.jira_resolution_field
    body = {"jql": query, "maxResults": 100,
            "fields": list(dict.fromkeys(["summary", "description", "status", resolution_field]))}
    incidents, tokens = [], set()
    with httpx.Client(auth=(settings.jira_email, settings.jira_api_token), timeout=60) as client:
        while True:
            response = client.post(base + "/rest/api/3/search/jql", json=body)
            response.raise_for_status()
            page = response.json()
            if not isinstance(page, dict) or not isinstance(page.get("issues"), list):
                raise ValueError("Invalid Jira search response")
            for issue in page["issues"]:
                fields = issue["fields"]
                status = fields.get("status") or {}
                done = (status.get("statusCategory") or {}).get("key") == "done"
                incidents.append(incident_from_row({
                    "ticket_id": issue["key"], "subject": fields.get("summary"),
                    "description": jira_text(fields.get("description")),
                    "resolution": jira_text(fields.get(resolution_field)).strip(),
                    "status": "Resolved" if done else status.get("name", ""),
                }))
            token = page.get("nextPageToken")
            if page.get("isLast") is True or not token:
                break
            if token in tokens:
                raise ValueError("Jira returned a repeated pagination token")
            tokens.add(token)
            body["nextPageToken"] = token
    return incidents
