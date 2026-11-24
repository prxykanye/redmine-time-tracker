from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
import requests

from redmine_time_tracker.redmine_client import (
    RedmineAuthError,
    RedmineClient,
    RedmineConnectionError,
    RedmineResponseError,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: dict[str, Any] | None = None,
        text: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        if text is not None:
            self.text = text
        else:
            self.text = json.dumps(payload) if payload is not None else ""

    def json(self) -> dict[str, Any]:
        if self.payload is None:
            raise ValueError("no json")
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(session: FakeSession) -> RedmineClient:
    return RedmineClient("https://redmine.example.com", "test-key", session=session)


def test_create_time_entry_sends_payload() -> None:
    session = FakeSession([FakeResponse(payload={"time_entry": {"id": 99}})])
    client = make_client(session)

    result = client.create_time_entry(
        issue_id=12,
        hours=0.5,
        comments="work",
        spent_on=date(2026, 1, 5),
        activity_id=9,
    )

    assert result["time_entry"]["id"] == 99
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://redmine.example.com/time_entries.json"
    assert call["headers"]["X-Redmine-API-Key"] == "test-key"
    assert call["json"]["time_entry"]["issue_id"] == 12
    assert call["json"]["time_entry"]["spent_on"] == "2026-01-05"


def test_pagination_reads_all_pages() -> None:
    first_page = [{"id": i, "subject": f"Issue {i}"} for i in range(100)]
    second_page = [{"id": i, "subject": f"Issue {i}"} for i in range(100, 150)]
    session = FakeSession(
        [
            FakeResponse(payload={"issues": first_page, "total_count": 150}),
            FakeResponse(payload={"issues": second_page, "total_count": 150}),
        ]
    )
    client = make_client(session)

    issues = client.get_assigned_open_issues(5)

    assert len(issues) == 150
    assert len(session.calls) == 2
    assert session.calls[0]["params"]["offset"] == 0
    assert session.calls[1]["params"]["offset"] == 100


def test_pagination_stops_on_empty_page() -> None:
    first_page = [{"id": i, "subject": f"Issue {i}"} for i in range(100)]
    session = FakeSession(
        [
            FakeResponse(payload={"issues": first_page, "total_count": 500}),
            FakeResponse(payload={"issues": [], "total_count": 500}),
        ]
    )
    client = make_client(session)

    issues = client.get_assigned_open_issues(5)

    assert len(issues) == 100
    assert len(session.calls) == 2


def test_rejected_key_raises_auth_error() -> None:
    session = FakeSession([FakeResponse(status_code=401, text="Unauthorized")])
    client = make_client(session)

    with pytest.raises(RedmineAuthError):
        client.get_current_user()


def test_timeout_raises_connection_error() -> None:
    session = FakeSession([requests.Timeout("too slow")])
    client = make_client(session)

    with pytest.raises(RedmineConnectionError):
        client.get_current_user()


def test_html_response_raises_response_error() -> None:
    session = FakeSession([FakeResponse(status_code=200, text="<html>login</html>")])
    client = make_client(session)

    with pytest.raises(RedmineResponseError):
        client.get_current_user()


def test_empty_key_is_rejected() -> None:
    with pytest.raises(RedmineAuthError):
        RedmineClient("https://redmine.example.com", "   ")


def test_entry_mapping() -> None:
    payload = {
        "time_entry": {
            "id": 7,
            "issue": {"id": 42},
            "user": {"id": 3},
            "hours": 1.5,
            "comments": "note",
            "spent_on": "2026-01-05",
            "activity": {"id": 9, "name": "Development"},
            "created_on": "2026-01-05T10:00:00Z",
            "updated_on": "2026-01-05T10:30:00Z",
        }
    }
    session = FakeSession([FakeResponse(payload=payload)])
    client = make_client(session)

    entry = client.get_time_entry(7)

    assert entry is not None
    assert entry.issue_id == 42
    assert entry.hours == 1.5
    assert entry.activity_name == "Development"
    assert entry.spent_on == date(2026, 1, 5)


def entry_payload(entry_id: int, issue_id: int) -> dict[str, Any]:
    return {
        "id": entry_id,
        "issue": {"id": issue_id},
        "user": {"id": 1},
        "hours": 1.0,
        "comments": "",
        "spent_on": "2026-01-05",
        "activity": {"id": 9, "name": "Development"},
        "created_on": "2026-01-05T10:00:00",
        "updated_on": "2026-01-05T10:00:00",
    }


def test_entries_for_many_issues_uses_one_filtered_request() -> None:
    session = FakeSession(
        [
            FakeResponse(
                payload={
                    "time_entries": [
                        entry_payload(20, 2),
                        entry_payload(10, 1),
                        entry_payload(11, 1),
                    ],
                    "total_count": 3,
                }
            )
        ]
    )
    client = make_client(session)

    result = client.get_time_entries_for_issues([1, 2], limit_per_issue=1)

    assert len(session.calls) == 1
    assert session.calls[0]["params"]["issue_id"] == "1,2"
    assert [entry.id for entry in result[1]] == [10]
    assert [entry.id for entry in result[2]] == [20]


def test_entries_for_issues_stops_when_every_issue_is_satisfied() -> None:
    first_page = [entry_payload(entry_id, 1) for entry_id in range(100)]
    session = FakeSession([FakeResponse(payload={"time_entries": first_page, "total_count": 500})])
    client = make_client(session)

    result = client.get_time_entries_for_issues([1], limit_per_issue=1)

    assert len(session.calls) == 1
    assert [entry.id for entry in result[1]] == [0]


def test_entries_for_issues_chunks_long_issue_lists() -> None:
    issue_ids = list(range(1, 61))
    session = FakeSession(
        [
            FakeResponse(payload={"time_entries": [], "total_count": 0}),
            FakeResponse(payload={"time_entries": [], "total_count": 0}),
        ]
    )
    client = make_client(session)

    client.get_time_entries_for_issues(issue_ids)

    assert len(session.calls) == 2
    first = session.calls[0]["params"]["issue_id"].split(",")
    second = session.calls[1]["params"]["issue_id"].split(",")
    assert len(first) == 50
    assert len(second) == 10
