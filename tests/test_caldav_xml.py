"""Tests for caldav_xml.py — CalDAV XML parsers and builders."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from pytodo_qt.web.caldav_xml import (
    CALDAV,
    DAV,
    build_multistatus,
    make_response,
    make_response_404,
    parse_propfind,
    parse_report,
    prop_calendar_data,
    prop_calendar_home_set,
    prop_current_user_principal,
    prop_resourcetype_calendar,
    prop_resourcetype_collection,
    prop_supported_components,
)


class TestParsePropfind:
    def test_empty_body_returns_empty_set(self):
        assert parse_propfind(b"") == set()

    def test_whitespace_body(self):
        assert parse_propfind(b"   \n  ") == set()

    def test_malformed_xml(self):
        assert parse_propfind(b"<not valid") == set()

    def test_propfind_with_specific_props(self):
        body = (
            b'<?xml version="1.0" ?>'
            b'<D:propfind xmlns:D="DAV:">'
            b"<D:prop><D:displayname/><D:getetag/></D:prop>"
            b"</D:propfind>"
        )
        props = parse_propfind(body)
        assert f"{{{DAV}}}displayname" in props
        assert f"{{{DAV}}}getetag" in props

    def test_propfind_no_prop_element(self):
        body = b'<?xml version="1.0" ?><D:propfind xmlns:D="DAV:"><D:allprop/></D:propfind>'
        assert parse_propfind(body) == set()


class TestParseReport:
    def test_malformed_xml(self):
        rt, hrefs, props, token = parse_report(b"<not valid")
        assert rt == "unknown"
        assert hrefs == []
        assert props == set()
        assert token == ""

    def test_calendar_multiget(self):
        body = (
            b'<?xml version="1.0" ?>'
            b'<C:calendar-multiget xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
            b"<D:prop><D:getetag/></D:prop>"
            b"<D:href>/cal/list/item1.ics</D:href>"
            b"<D:href>/cal/list/item2.ics</D:href>"
            b"</C:calendar-multiget>"
        )
        rt, hrefs, props, token = parse_report(body)
        assert rt == "calendar-multiget"
        assert hrefs == ["/cal/list/item1.ics", "/cal/list/item2.ics"]
        assert f"{{{DAV}}}getetag" in props

    def test_calendar_query(self):
        body = (
            b'<?xml version="1.0" ?>'
            b'<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
            b"<D:prop><D:getetag/></D:prop>"
            b"</C:calendar-query>"
        )
        rt, _, _, _ = parse_report(body)
        assert rt == "calendar-query"

    def test_sync_collection_with_token(self):
        body = (
            b'<?xml version="1.0" ?>'
            b'<D:sync-collection xmlns:D="DAV:">'
            b"<D:sync-token>http://example.com/sync/123</D:sync-token>"
            b"<D:prop><D:getetag/></D:prop>"
            b"</D:sync-collection>"
        )
        rt, _, _, token = parse_report(body)
        assert rt == "sync-collection"
        assert token == "http://example.com/sync/123"


class TestResponseBuilders:
    def test_make_response_with_string_props(self):
        resp = make_response("/test", {f"{{{DAV}}}displayname": "Test List"})
        assert resp.tag == f"{{{DAV}}}response"
        # Should contain href and propstat
        href = resp.find(f"{{{DAV}}}href")
        assert href is not None
        assert href.text == "/test"

    def test_make_response_with_element_props(self):
        rt = prop_resourcetype_collection()
        resp = make_response("/cal/", {f"{{{DAV}}}resourcetype": rt})
        propstat = resp.find(f"{{{DAV}}}propstat")
        assert propstat is not None

    def test_make_response_404(self):
        resp = make_response_404("/cal/deleted.ics")
        assert resp.tag == f"{{{DAV}}}response"
        status = resp.find(f"{{{DAV}}}status")
        assert status is not None
        assert "404" in (status.text or "")

    def test_build_multistatus_basic(self):
        resp = make_response("/x", {f"{{{DAV}}}displayname": "X"})
        body = build_multistatus([resp])
        assert b"multistatus" in body
        assert b"<?xml" in body

    def test_build_multistatus_with_sync_token(self):
        resp = make_response("/x", {f"{{{DAV}}}displayname": "X"})
        body = build_multistatus([resp], sync_token="http://example.com/token/42")
        assert b"sync-token" in body
        assert b"http://example.com/token/42" in body

    def test_multistatus_parses_back(self):
        resp = make_response("/cal/list/", {f"{{{DAV}}}displayname": "My List"})
        body = build_multistatus([resp])
        parsed = ET.fromstring(body)
        assert parsed.tag == f"{{{DAV}}}multistatus"


class TestPropertyHelpers:
    def test_resourcetype_collection(self):
        el = prop_resourcetype_collection()
        assert el.tag == f"{{{DAV}}}resourcetype"
        assert el.find(f"{{{DAV}}}collection") is not None

    def test_resourcetype_calendar(self):
        el = prop_resourcetype_calendar()
        assert el.find(f"{{{DAV}}}collection") is not None
        assert el.find(f"{{{CALDAV}}}calendar") is not None

    def test_supported_components(self):
        el = prop_supported_components()
        comp = el.find(f"{{{CALDAV}}}comp")
        assert comp is not None
        assert comp.get("name") == "VTODO"

    def test_current_user_principal(self):
        el = prop_current_user_principal("/principals/user/")
        href = el.find(f"{{{DAV}}}href")
        assert href is not None
        assert href.text == "/principals/user/"

    def test_calendar_home_set(self):
        el = prop_calendar_home_set("/cal/")
        href = el.find(f"{{{DAV}}}href")
        assert href is not None
        assert href.text == "/cal/"

    def test_calendar_data(self):
        ics = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"
        el = prop_calendar_data(ics)
        assert el.text is not None
        assert "VCALENDAR" in el.text
