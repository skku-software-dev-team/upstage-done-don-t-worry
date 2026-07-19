"""Jira Cloud REST integration (Basic auth: email + API token).

Statuses are mapped by Jira *statusCategory* (new / indeterminate / done) rather
than by display name, so the mapping survives renamed or extra columns (e.g. a
'검토 중' column still syncs to 진행중).
"""

import base64
import logging

import httpx

from app.models.compliance import Organization

logger = logging.getLogger(__name__)

ISSUE_TYPE_NAME = "작업"  # DDW standard Task type

# Dashboard status -> Jira statusCategory key
_STATUS_TO_CATEGORY = {
    "not_started": "new",
    "in_progress": "indeterminate",
    "completed": "done",
}
# Jira statusCategory key -> dashboard status
_CATEGORY_TO_STATUS = {
    "new": "not_started",
    "indeterminate": "in_progress",
    "done": "completed",
}
# Statuses that create a ticket when an item first reaches them (해당없음 excluded)
CREATE_STATUSES = {"not_started", "in_progress", "completed"}


class JiraError(Exception):
    pass


def is_connected(org: Organization | None) -> bool:
    return bool(
        org
        and org.jira_base_url
        and org.jira_email
        and org.jira_api_token
        and org.jira_project_key
    )


def category_to_status(category_key: str) -> str | None:
    return _CATEGORY_TO_STATUS.get(category_key)


async def resolve_cloud_id(base_url: str) -> str | None:
    """Resolve a site's numeric cloudId from its URL (unauthenticated public endpoint).

    Scoped API tokens only authenticate against the api.atlassian.com/ex/jira/{cloudId}
    gateway, not the site URL directly, so we need the cloudId.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{base_url.rstrip('/')}/_edge/tenant_info")
            if r.status_code < 300:
                return r.json().get("cloudId")
    except Exception:
        logger.exception("cloudId resolution failed for %s", base_url)
    return None


def _client(org: Organization) -> httpx.AsyncClient:
    if not org.jira_cloud_id:
        raise JiraError("Jira cloudId not resolved; reconnect the Jira integration.")
    token = base64.b64encode(f"{org.jira_email}:{org.jira_api_token}".encode()).decode()
    return httpx.AsyncClient(
        base_url=f"https://api.atlassian.com/ex/jira/{org.jira_cloud_id}",
        headers={
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=20.0,
    )


async def _transition_to_category(client: httpx.AsyncClient, key: str, category: str) -> None:
    """Move an issue to the first transition whose target statusCategory matches."""
    r = await client.get(f"/rest/api/3/issue/{key}/transitions")
    if r.status_code >= 300:
        raise JiraError(f"list transitions failed for {key}: {r.status_code} {r.text}")
    transitions = r.json().get("transitions", [])
    match = next(
        (t for t in transitions if t["to"]["statusCategory"]["key"] == category), None
    )
    if match is None:
        raise JiraError(f"no transition to category '{category}' for {key}")
    r2 = await client.post(
        f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": match["id"]}}
    )
    if r2.status_code >= 300:
        raise JiraError(f"transition {key} failed: {r2.status_code} {r2.text}")


async def create_issue(org: Organization, summary: str, target_status: str) -> str:
    """Create a Task in the org's project and move it to match target_status.

    Returns the new issue key (e.g. 'DDW-42'). Raises JiraError on failure.
    """
    async with _client(org) as client:
        r = await client.post(
            "/rest/api/3/issue",
            json={
                "fields": {
                    "project": {"key": org.jira_project_key},
                    "summary": summary[:250],
                    "issuetype": {"name": ISSUE_TYPE_NAME},
                }
            },
        )
        if r.status_code >= 300:
            raise JiraError(f"create issue failed: {r.status_code} {r.text}")
        key = r.json()["key"]

        # New issues start in 'new' (할 일); transition only if target differs.
        category = _STATUS_TO_CATEGORY.get(target_status)
        if category and category != "new":
            await _transition_to_category(client, key, category)
        return key


async def get_statuses(org: Organization, keys: list[str]) -> dict[str, str]:
    """Fetch current dashboard-mapped status for each issue key.

    Returns {issue_key: dashboard_status}. Keys that error or map to an unknown
    category are omitted.
    """
    if not keys:
        return {}
    unique = sorted(set(keys))
    jql = f"key in ({','.join(unique)})"
    async with _client(org) as client:
        r = await client.get(
            "/rest/api/3/search/jql",
            params={"jql": jql, "fields": "status", "maxResults": 100},
        )
        if r.status_code >= 300:
            raise JiraError(f"search failed: {r.status_code} {r.text}")
        out: dict[str, str] = {}
        for issue in r.json().get("issues", []):
            category = issue["fields"]["status"]["statusCategory"]["key"]
            mapped = _CATEGORY_TO_STATUS.get(category)
            if mapped:
                out[issue["key"]] = mapped
        return out
