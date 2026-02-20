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
            fields="summary,description,status,priority,issuetype,labels,assignee,reporter,created,updated,comment",
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
