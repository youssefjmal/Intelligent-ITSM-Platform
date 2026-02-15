"""Jira REST v3 client wrapper with retries."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import settings


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
