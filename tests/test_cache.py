from __future__ import annotations

from datetime import date, datetime

from redmine_time_tracker.models import Activity, Issue, TimeEntry


def make_entry(entry_id: int, issue_id: int, hours: float = 1.0) -> TimeEntry:
    return TimeEntry(
        id=entry_id,
        issue_id=issue_id,
        user_id=7,
        hours=hours,
        comments="note",
        spent_on=date(2026, 1, 5),
        activity_id=9,
        activity_name="Development",
        created_on=datetime(2026, 1, 5, 10, 0, 0),
        updated_on=datetime(2026, 1, 5, 11, 0, 0),
    )


def test_cache_roundtrip(db) -> None:
    issue = Issue(
        id=42,
        subject="Cached issue",
        estimated_hours=4.0,
        total_spent_hours=1.5,
        time_entries=[make_entry(1, 42, 1.5)],
    )
    activity = Activity(id=9, name="Development", is_default=True)
    fetched_at = datetime(2026, 1, 5, 12, 0, 0)

    db.replace_cache([issue], [activity], fetched_at)

    issues, activities, last_sync = db.load_cached()
    assert last_sync == fetched_at
    assert [item.id for item in issues] == [42]
    assert issues[0].subject == "Cached issue"
    assert issues[0].estimated_hours == 4.0
    assert issues[0].total_spent_hours == 1.5
    assert len(issues[0].time_entries) == 1
    assert issues[0].time_entries[0].hours == 1.5
    assert [item.name for item in activities] == ["Development"]
    assert activities[0].is_default is True


def test_cache_is_replaced_not_appended(db) -> None:
    db.replace_cache(
        [Issue(id=1, subject="Old", estimated_hours=None, total_spent_hours=0.0)],
        [Activity(id=9, name="Dev")],
        datetime(2026, 1, 5, 12, 0, 0),
    )
    db.replace_cache(
        [Issue(id=2, subject="New", estimated_hours=None, total_spent_hours=0.0)],
        [Activity(id=9, name="Dev")],
        datetime(2026, 1, 6, 12, 0, 0),
    )

    issues, _, last_sync = db.load_cached()
    assert [item.id for item in issues] == [2]
    assert last_sync == datetime(2026, 1, 6, 12, 0, 0)


def test_clear_cache(db) -> None:
    db.replace_cache(
        [Issue(id=1, subject="Old", estimated_hours=None, total_spent_hours=0.0)],
        [Activity(id=9, name="Dev")],
        datetime(2026, 1, 5, 12, 0, 0),
    )
    db.clear_cache()

    issues, activities, last_sync = db.load_cached()
    assert issues == []
    assert activities == []
    assert last_sync is None


def test_empty_cache(db) -> None:
    issues, activities, last_sync = db.load_cached()
    assert issues == []
    assert activities == []
    assert last_sync is None
