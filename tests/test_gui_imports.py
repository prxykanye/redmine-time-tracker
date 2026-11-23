from __future__ import annotations

import typing


def test_widget_annotations_resolve() -> None:
    """Regression test: TimeEntry used to be referenced without an import.

    On Python 3.13 that made ``import gui.widgets`` fail, on 3.14 the lazy
    annotation hid the bug until something inspected it.
    """
    from redmine_time_tracker.gui import widgets
    from redmine_time_tracker.models import TimeEntry

    hints = typing.get_type_hints(widgets.ExistingEntryWidget.__init__)
    assert hints["entry"] is TimeEntry

    hints = typing.get_type_hints(widgets.IssueWidget.set_existing_entries)
    assert typing.get_origin(hints["entries"]) is list


def test_all_gui_modules_import() -> None:
    from redmine_time_tracker.gui import dialogs, main_window, widgets  # noqa: F401
