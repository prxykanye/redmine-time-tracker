"""Redmine REST API client.

Only the endpoints needed by the tracker are implemented. Failures are mapped
to a small exception hierarchy so the GUI can show something meaningful for a
timeout, a rejected key or an unexpected HTML response.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Activity, Issue, TimeEntry


class RedmineError(Exception):
    """Base class for every Redmine failure."""


class RedmineAuthError(RedmineError):
    """The API key is missing, expired or lacks permissions."""


class RedmineConnectionError(RedmineError):
    """The server is unreachable, too slow or dropped the connection."""


class RedmineResponseError(RedmineError):
    """The server answered with an error status or an unparsable body."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _default_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class RedmineClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        verify: bool | str = True,
    ) -> None:
        base = base_url.strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            raise RedmineResponseError("Redmine URL must start with http:// or https://")
        if not api_key.strip():
            raise RedmineAuthError("REDMINE_API_KEY is not configured")
        self.base_url = base
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.verify = verify
        self._session = session or _default_session()

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {
            "X-Redmine-API-Key": self.api_key,
            "Accept": "application/json",
        }
        headers.update(kwargs.pop("headers", {}) or {})
        if "json" in kwargs:
            headers["Content-Type"] = "application/json"
        try:
            response = self._session.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                timeout=self.timeout,
                verify=self.verify,
                **kwargs,
            )
        except requests.Timeout as exc:
            raise RedmineConnectionError(f"Redmine не ответил за {self.timeout:.0f} с") from exc
        except requests.RequestException as exc:
            raise RedmineConnectionError(f"Нет связи с Redmine: {exc}") from exc

        if response.status_code in (401, 403):
            raise RedmineAuthError("Redmine отклонил API-ключ")
        if response.status_code >= 400:
            body = (response.text or "").strip()[:500]
            raise RedmineResponseError(
                f"Redmine вернул {response.status_code}: {body or 'пустой ответ'}",
                status_code=response.status_code,
            )
        if not response.text:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise RedmineResponseError(
                "Redmine вернул не JSON. Проверьте URL: возможно, это страница входа."
            ) from exc
        if not isinstance(payload, dict):
            raise RedmineResponseError("Неожиданный формат ответа Redmine")
        return payload

    def _paginate(
        self,
        path: str,
        key: str,
        params: dict[str, Any],
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = self._request("GET", path, params={**params, "offset": offset, "limit": limit})
            items = data.get(key) or []
            if not items:
                break
            results.extend(items)
            offset += len(items)
            total = data.get("total_count")
            if len(items) < limit or (isinstance(total, int) and offset >= total):
                break
        return results

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------
    def get_current_user(self) -> dict[str, Any]:
        return self._request("GET", "/users/current.json").get("user", {})

    def get_activities(self) -> list[Activity]:
        data = self._request("GET", "/enumerations/time_entry_activities.json")
        return [
            Activity(
                id=item["id"],
                name=item["name"],
                is_default=bool(item.get("is_default", False)),
            )
            for item in data.get("time_entry_activities", [])
        ]

    def get_assigned_open_issues(self, user_id: int | str) -> list[Issue]:
        raw = self._paginate(
            "/issues.json",
            "issues",
            {"assigned_to_id": user_id, "status_id": "open"},
        )
        return [
            Issue(
                id=item["id"],
                subject=item["subject"],
                estimated_hours=item.get("estimated_hours"),
                total_spent_hours=float(item.get("spent_hours", 0.0) or 0.0),
            )
            for item in raw
        ]

    def get_time_entries_for_issue(self, issue_id: int, limit: int = 5) -> list[TimeEntry]:
        data = self._request(
            "GET",
            "/time_entries.json",
            params={"issue_id": issue_id, "limit": limit, "sort": "updated_on:desc"},
        )
        return [
            self._entry_from_json(item, default_issue_id=issue_id)
            for item in data.get("time_entries", [])
        ]

    def get_time_entries(
        self,
        user_id: int | str,
        spent_on_from: date | None = None,
        spent_on_to: date | None = None,
    ) -> list[TimeEntry]:
        params: dict[str, Any] = {"user_id": user_id}
        if spent_on_from:
            params["from"] = spent_on_from.isoformat()
        if spent_on_to:
            params["to"] = spent_on_to.isoformat()
        raw = self._paginate("/time_entries.json", "time_entries", params)
        return [self._entry_from_json(item) for item in raw]

    def get_time_entry(self, entry_id: int) -> TimeEntry | None:
        data = self._request("GET", f"/time_entries/{entry_id}.json")
        item = data.get("time_entry")
        return self._entry_from_json(item) if item else None

    def create_time_entry(
        self,
        issue_id: int,
        hours: float,
        comments: str,
        spent_on: date,
        activity_id: int,
    ) -> dict[str, Any]:
        payload = {
            "time_entry": {
                "issue_id": issue_id,
                "hours": hours,
                "comments": comments,
                "spent_on": spent_on.isoformat(),
                "activity_id": activity_id,
            }
        }
        return self._request("POST", "/time_entries.json", json=payload)

    def update_time_entry(
        self,
        time_entry_id: int,
        hours: float,
        comments: str,
        spent_on: date,
        activity_id: int,
    ) -> dict[str, Any]:
        payload = {
            "time_entry": {
                "hours": hours,
                "comments": comments,
                "spent_on": spent_on.isoformat(),
                "activity_id": activity_id,
            }
        }
        return self._request("PUT", f"/time_entries/{time_entry_id}.json", json=payload)

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------
    @staticmethod
    def _entry_from_json(item: dict[str, Any], default_issue_id: int = 0) -> TimeEntry:
        issue = item.get("issue") or {}
        user = item.get("user") or {}
        activity = item.get("activity") or {}
        return TimeEntry(
            id=int(item["id"]),
            issue_id=int(issue.get("id") or default_issue_id or 0),
            user_id=int(user.get("id") or 0),
            hours=float(item.get("hours") or 0.0),
            comments=item.get("comments") or "",
            spent_on=date.fromisoformat(item["spent_on"]),
            activity_id=int(activity.get("id") or 0),
            activity_name=activity.get("name") or "",
            created_on=datetime.fromisoformat(item["created_on"]),
            updated_on=datetime.fromisoformat(item["updated_on"]),
        )
