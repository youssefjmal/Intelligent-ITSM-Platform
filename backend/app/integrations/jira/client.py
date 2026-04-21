"""Jira REST v3 client wrapper with retries."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class JiraClient:
    def __init__(self) -> None:
        config_error = settings.jira_config_error
        if config_error is not None:
            raise ValueError(config_error)
        self.base_url = settings.JIRA_BASE_URL.rstrip("/")
        self.email = settings.JIRA_EMAIL
        self.api_token = settings.JIRA_API_TOKEN
        self.timeout = 25.0
        self.max_retries = 3

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        backoff = 0.5
        with httpx.Client(
            timeout=self.timeout,
            auth=(self.email, self.api_token),
            headers={"Accept": "application/json"},
        ) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = client.request(method, url, **kwargs)
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                    response.raise_for_status()
                    data = response.json()
                    return data if isinstance(data, dict) else {}
                except httpx.HTTPError:
                    if attempt >= self.max_retries:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
        return {}

    def _request_list(self, method: str, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        url = f"{self.base_url}{path}"
        backoff = 0.5
        with httpx.Client(
            timeout=self.timeout,
            auth=(self.email, self.api_token),
            headers={"Accept": "application/json"},
        ) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = client.request(method, url, **kwargs)
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                    response.raise_for_status()
                    data = response.json()
                    if isinstance(data, list):
                        return [item for item in data if isinstance(item, dict)]
                    return []
                except httpx.HTTPError:
                    if attempt >= self.max_retries:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
        return []

    def _request_empty(self, method: str, path: str, **kwargs: Any) -> bool:
        url = f"{self.base_url}{path}"
        backoff = 0.5
        with httpx.Client(
            timeout=self.timeout,
            auth=(self.email, self.api_token),
            headers={"Accept": "application/json"},
        ) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = client.request(method, url, **kwargs)
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                    response.raise_for_status()
                    return True
                except httpx.HTTPError:
                    if attempt >= self.max_retries:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
        return False

    def get_issue(self, issue_key: str, *, fields: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/rest/api/3/issue/{issue_key}",
            params={"fields": fields},
        )

    def get_issue_comments(self, issue_key: str, *, start_at: int = 0, max_results: int = 100) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/rest/api/3/issue/{issue_key}/comment",
            params={"startAt": start_at, "maxResults": max_results},
        )

    def search_jql(
        self,
        *,
        jql: str,
        start_at: int = 0,
        max_results: int | None = None,
        fields: str,
    ) -> dict[str, Any]:
        limit = max_results or settings.JIRA_SYNC_PAGE_SIZE
        return self._request(
            "GET",
            "/rest/api/3/search/jql",
            params={
                "jql": jql,
                "startAt": start_at,
                "maxResults": limit,
                "fields": fields,
            },
        )

    # Backward-compatible helper used by outbound sync code paths.
    def search_updated_issues(
        self,
        *,
        since_iso: str,
        start_at: int = 0,
        max_results: int | None = None,
        project_key: str | None = None,
    ) -> dict[str, Any]:
        project_clause = f'project = "{project_key}" AND ' if project_key else ""
        jql = f'{project_clause}updated >= "{since_iso}" ORDER BY updated ASC'
        return self.search_jql(
            jql=jql,
            start_at=start_at,
            max_results=max_results,
            fields="summary,description,status,priority,issuetype,labels,assignee,reporter,created,updated,duedate,comment,customfield_10010",
        )

    def _build_issue_sla_path(self, issue_key: str) -> str:
        # TODO: confirm alternate endpoint variants if Jira/JSM API versions differ by tenant.
        return f"/rest/servicedeskapi/request/{issue_key}/sla"

    def get_issue_sla(self, issue_key: str) -> dict[str, Any]:
        key = (issue_key or "").strip()
        if not key:
            return {}

        url = f"{self.base_url}{self._build_issue_sla_path(key)}"
        backoff = 0.5
        with httpx.Client(
            timeout=30.0,
            auth=(self.email, self.api_token),
            headers={"Accept": "application/json"},
        ) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = client.get(url)
                except httpx.HTTPError:
                    if attempt >= self.max_retries:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                if response.status_code in {401, 403, 404}:
                    logger.warning(
                        "Jira SLA endpoint unavailable for %s (status=%s). Returning empty payload.",
                        key,
                        response.status_code,
                    )
                    return {}

                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {}

        return {}

    def search_users(self, query: str, *, max_results: int = 20) -> list[dict[str, Any]]:
        value = (query or "").strip()
        if not value:
            return []

        url = f"{self.base_url}/rest/api/3/user/search"
        backoff = 0.5
        with httpx.Client(
            timeout=self.timeout,
            auth=(self.email, self.api_token),
            headers={"Accept": "application/json"},
        ) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = client.get(url, params={"query": value, "maxResults": max(1, min(max_results, 100))})
                except httpx.HTTPError:
                    if attempt >= self.max_retries:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                response.raise_for_status()
                data = response.json()
                if isinstance(data, list):
                    return [item for item in data if isinstance(item, dict)]
                return []

        return []

    def search_assignable_users(
        self,
        query: str,
        *,
        project_key: str | None = None,
        issue_key: str | None = None,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        value = (query or "").strip()
        if not value:
            return []

        url = f"{self.base_url}/rest/api/3/user/assignable/search"
        params: dict[str, Any] = {"query": value, "maxResults": max(1, min(max_results, 100))}
        if project_key:
            params["project"] = str(project_key).strip()
        if issue_key:
            params["issueKey"] = str(issue_key).strip()
        backoff = 0.5
        with httpx.Client(
            timeout=self.timeout,
            auth=(self.email, self.api_token),
            headers={"Accept": "application/json"},
        ) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = client.get(url, params=params)
                except httpx.HTTPError:
                    if attempt >= self.max_retries:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                response.raise_for_status()
                data = response.json()
                if isinstance(data, list):
                    return [item for item in data if isinstance(item, dict)]
                return []

        return []

    def create_customer(self, *, display_name: str, email: str) -> dict[str, Any]:
        payload = {
            "displayName": str(display_name or "").strip() or str(email or "").strip(),
            "email": str(email or "").strip(),
        }
        return self._request("POST", "/rest/servicedeskapi/customer", json=payload)

    def get_myself(self) -> dict[str, Any]:
        return self._request("GET", "/rest/api/3/myself")

    def get_service_desks(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/rest/servicedeskapi/servicedesk")
        rows = payload.get("values")
        if not isinstance(rows, list):
            return []
        return [item for item in rows if isinstance(item, dict)]

    def get_request_types(self, service_desk_id: str) -> list[dict[str, Any]]:
        value = (service_desk_id or "").strip()
        if not value:
            return []
        payload = self._request("GET", f"/rest/servicedeskapi/servicedesk/{value}/requesttype")
        rows = payload.get("values")
        if not isinstance(rows, list):
            return []
        return [item for item in rows if isinstance(item, dict)]

    def create_customer_request(
        self,
        *,
        service_desk_id: str,
        request_type_id: str,
        request_field_values: dict[str, Any],
        raise_on_behalf_of: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "serviceDeskId": str(service_desk_id).strip(),
            "requestTypeId": str(request_type_id).strip(),
            "requestFieldValues": request_field_values,
        }
        reporter = str(raise_on_behalf_of or "").strip()
        if reporter:
            payload["raiseOnBehalfOf"] = reporter
        return self._request("POST", "/rest/servicedeskapi/request", json=payload)

    def get_project_components(self, project_key: str) -> list[dict[str, Any]]:
        value = (project_key or "").strip()
        if not value:
            return []
        return self._request_list("GET", f"/rest/api/3/project/{value}/components")

    def create_project_component(
        self,
        *,
        project_key: str,
        name: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "project": str(project_key).strip(),
            "name": str(name).strip(),
        }
        desc = str(description or "").strip()
        if desc:
            payload["description"] = desc
        return self._request("POST", "/rest/api/3/component", json=payload)

    def get_project_roles(self, project_key: str) -> dict[str, str]:
        value = (project_key or "").strip()
        if not value:
            return {}
        payload = self._request("GET", f"/rest/api/3/project/{value}/role")
        return {str(key): str(val) for key, val in payload.items() if isinstance(key, str) and isinstance(val, str)}

    def get_project_role(self, project_key: str, role_id: str) -> dict[str, Any]:
        project = (project_key or "").strip()
        role = (role_id or "").strip()
        if not project or not role:
            return {}
        return self._request("GET", f"/rest/api/3/project/{project}/role/{role}")

    def add_project_role_users(self, project_key: str, role_id: str, account_ids: list[str]) -> bool:
        project = (project_key or "").strip()
        role = (role_id or "").strip()
        users = [str(account_id).strip() for account_id in account_ids if str(account_id).strip()]
        if not project or not role or not users:
            return False
        self._request("POST", f"/rest/api/3/project/{project}/role/{role}", json={"user": users})
        return True

    def remove_project_role_users(self, project_key: str, role_id: str, account_ids: list[str]) -> bool:
        project = (project_key or "").strip()
        role = (role_id or "").strip()
        users = [str(account_id).strip() for account_id in account_ids if str(account_id).strip()]
        if not project or not role or not users:
            return False
        params = [("user", account_id) for account_id in users]
        return self._request_empty("DELETE", f"/rest/api/3/project/{project}/role/{role}", params=params)

    def update_issue_fields(self, issue_key: str, fields: dict[str, Any]) -> bool:
        key = (issue_key or "").strip()
        if not key:
            return False
        url = f"{self.base_url}/rest/api/3/issue/{key}"
        backoff = 0.5
        with httpx.Client(
            timeout=self.timeout,
            auth=(self.email, self.api_token),
            headers={"Accept": "application/json"},
        ) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = client.put(url, json={"fields": fields})
                except httpx.HTTPError:
                    if attempt >= self.max_retries:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                response.raise_for_status()
                return True
        return False

    def get_issue_transitions(self, issue_key: str) -> list[dict[str, Any]]:
        key = (issue_key or "").strip()
        if not key:
            return []
        payload = self._request("GET", f"/rest/api/3/issue/{key}/transitions")
        rows = payload.get("transitions")
        if not isinstance(rows, list):
            return []
        return [item for item in rows if isinstance(item, dict)]

    def transition_issue(self, issue_key: str, transition_id: str) -> bool:
        key = (issue_key or "").strip()
        value = (transition_id or "").strip()
        if not key or not value:
            return False
        url = f"{self.base_url}/rest/api/3/issue/{key}/transitions"
        backoff = 0.5
        with httpx.Client(
            timeout=self.timeout,
            auth=(self.email, self.api_token),
            headers={"Accept": "application/json"},
        ) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = client.post(url, json={"transition": {"id": value}})
                except httpx.HTTPError:
                    if attempt >= self.max_retries:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                response.raise_for_status()
                return True
        return False

    def add_issue_comment(self, issue_key: str, body: dict[str, Any]) -> bool:
        key = (issue_key or "").strip()
        if not key:
            return False
        url = f"{self.base_url}/rest/api/3/issue/{key}/comment"
        backoff = 0.5
        with httpx.Client(
            timeout=self.timeout,
            auth=(self.email, self.api_token),
            headers={"Accept": "application/json"},
        ) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = client.post(url, json={"body": body})
                except httpx.HTTPError:
                    if attempt >= self.max_retries:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                response.raise_for_status()
                return True
        return False

    def update_issue_comment(self, issue_key: str, comment_id: str, body: dict[str, Any]) -> bool:
        key = (issue_key or "").strip()
        value = (comment_id or "").strip()
        if not key or not value:
            return False
        url = f"{self.base_url}/rest/api/3/issue/{key}/comment/{value}"
        backoff = 0.5
        with httpx.Client(
            timeout=self.timeout,
            auth=(self.email, self.api_token),
            headers={"Accept": "application/json"},
        ) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = client.put(url, json={"body": body})
                except httpx.HTTPError:
                    if attempt >= self.max_retries:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                response.raise_for_status()
                return True
        return False

    def create_kb_article(
        self,
        project_key: str,
        title: str,
        body_text: str,
        source_ticket_id: str,
    ) -> dict:
        """Create a Jira issue in the KB project to represent a published knowledge article.

        Tagged with kb_article and kb_source_{ticket_id} labels for KB indexer identification.
        """
        description_adf = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": body_text}],
                }
            ],
        }
        safe_ticket_id = source_ticket_id.replace(" ", "_")[:50]
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": title[:255],
                "issuetype": {"name": settings.JIRA_KB_ARTICLE_ISSUE_TYPE},
                "description": description_adf,
                "labels": [f"kb_source_{safe_ticket_id}", "kb_article"],
            }
        }
        return self._request("POST", "/rest/api/3/issue", json=payload)

    def create_confluence_kb_article(
        self,
        space_key: str,
        title: str,
        body_html: str,
        source_ticket_id: str,
    ) -> dict:
        """Publish a knowledge article as a native Confluence page in the JSM-linked space.

        The article appears immediately in the JSM Knowledge Base sidebar because it is
        created directly in the Confluence space that is linked to the service project.

        Uses the same JIRA_EMAIL + JIRA_API_TOKEN credentials — Atlassian Cloud shares
        one identity layer across Jira and Confluence on the same site.

        Returns a dict with:
            ``id``  — Confluence page ID (numeric string, stored as jira_issue_key)
            ``url`` — full browser URL of the published page
        """
        payload = {
            "type": "page",
            "title": title[:255],
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body_html,
                    "representation": "storage",
                }
            },
            "metadata": {
                "properties": {
                    "content-appearance-draft": {"value": "full-width"},
                    "content-appearance-published": {"value": "full-width"},
                }
            },
        }
        # Confluence REST API lives at /wiki/rest/api/content on the same Atlassian domain.
        result = self._request("POST", "/wiki/rest/api/content", json=payload)
        page_id = str(result.get("id", ""))
        links = result.get("_links", {})
        base = links.get("base", self.base_url)
        webui = links.get("webui", f"/wiki/spaces/{space_key}/pages/{page_id}")
        return {"id": page_id, "url": f"{base}{webui}"}
