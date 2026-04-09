"""Tests for caldav_handler.py pure helper functions."""

from __future__ import annotations

from uuid import uuid4

from pytodo_qt.core.models import TodoItem, create_todo_list
from pytodo_qt.web.caldav_handler import (
    _calendar_props,
    _ctag,
    _etag,
    _item_href,
    _item_props,
    _sync_token,
)
from pytodo_qt.web.caldav_xml import (
    CALDAV,
    DAV,
)

_GETETAG = f"{{{DAV}}}getetag"
_GETCTAG = "{http://calendarserver.org/ns/}getctag"
_DISPLAYNAME = f"{{{DAV}}}displayname"
_RESOURCETYPE = f"{{{DAV}}}resourcetype"
_SUPPORTED = f"{{{CALDAV}}}supported-calendar-component-set"


class TestEtag:
    def test_format(self):
        item = TodoItem(reminder="Test")
        item.updated_at = 1234567890
        assert _etag(item) == '"1234567890"'

    def test_changes_with_updated_at(self):
        item = TodoItem(reminder="Test")
        item.updated_at = 1
        a = _etag(item)
        item.updated_at = 2
        b = _etag(item)
        assert a != b


class TestCtag:
    def test_format(self):
        lst = create_todo_list("Test")
        lst.updated_at = 9876543210
        assert _ctag(lst) == "ctag-9876543210"


class TestSyncToken:
    def test_format(self):
        lst = create_todo_list("Test")
        lst.updated_at = 555
        assert _sync_token(lst) == "sync-token-555"


class TestItemHref:
    def test_format(self):
        list_id = uuid4()
        item_id = uuid4()
        href = _item_href(list_id, item_id)
        assert href.startswith("/caldav/user/calendars/")
        assert str(list_id) in href
        assert str(item_id) in href
        assert href.endswith(".ics")


class TestCalendarProps:
    def test_includes_required_keys(self):
        lst = create_todo_list("My List")
        props = _calendar_props(lst)
        assert _DISPLAYNAME in props
        assert _RESOURCETYPE in props
        assert _SUPPORTED in props
        assert _GETCTAG in props

    def test_displayname_matches(self):
        lst = create_todo_list("My List")
        props = _calendar_props(lst)
        assert props[_DISPLAYNAME] == "My List"


class TestItemProps:
    def test_basic_no_data(self):
        item = TodoItem(reminder="Test")
        list_id = uuid4()
        props = _item_props(item, list_id, include_data=False)
        assert _GETETAG in props
        # No calendar-data when include_data=False
        assert f"{{{CALDAV}}}calendar-data" not in props

    def test_with_data(self):
        item = TodoItem(reminder="Test")
        list_id = uuid4()
        props = _item_props(item, list_id, include_data=True)
        assert _GETETAG in props
        assert f"{{{CALDAV}}}calendar-data" in props
