"""caldav_xml.py

XML namespace constants, PROPFIND/REPORT request parsers, and
multistatus response builders for the embedded CalDAV server.

Uses xml.etree.ElementTree (stdlib) — no external XML library needed.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

# ---------------------------------------------------------------------------
# Namespace constants
# ---------------------------------------------------------------------------

DAV = "DAV:"
CALDAV = "urn:ietf:params:xml:ns:caldav"
CS = "http://calendarserver.org/ns/"

# Register namespace prefixes for clean output
ET.register_namespace("D", DAV)
ET.register_namespace("C", CALDAV)
ET.register_namespace("CS", CS)

# Common property QNames
_PROP = f"{{{DAV}}}prop"
_PROPFIND = f"{{{DAV}}}propfind"
_MULTISTATUS = f"{{{DAV}}}multistatus"
_RESPONSE = f"{{{DAV}}}response"
_HREF = f"{{{DAV}}}href"
_PROPSTAT = f"{{{DAV}}}propstat"
_STATUS = f"{{{DAV}}}status"
_COLLECTION = f"{{{DAV}}}collection"
_RESOURCETYPE = f"{{{DAV}}}resourcetype"
_DISPLAYNAME = f"{{{DAV}}}displayname"
_GETETAG = f"{{{DAV}}}getetag"
_GETCONTENTTYPE = f"{{{DAV}}}getcontenttype"
_CURRENT_USER_PRINCIPAL = f"{{{DAV}}}current-user-principal"
_CALENDAR_HOME_SET = f"{{{CALDAV}}}calendar-home-set"
_CALENDAR = f"{{{CALDAV}}}calendar"
_SUPPORTED_CALENDAR_COMPONENT_SET = f"{{{CALDAV}}}supported-calendar-component-set"
_COMP = f"{{{CALDAV}}}comp"
_CALENDAR_DATA = f"{{{CALDAV}}}calendar-data"
_GETCTAG = f"{{{CS}}}getctag"
_SYNC_TOKEN = f"{{{DAV}}}sync-token"
_SYNC_COLLECTION = f"{{{DAV}}}sync-collection"
_CALENDAR_MULTIGET = f"{{{CALDAV}}}calendar-multiget"
_CALENDAR_QUERY = f"{{{CALDAV}}}calendar-query"


# ---------------------------------------------------------------------------
# Request parsers
# ---------------------------------------------------------------------------


def parse_propfind(body: bytes) -> set[str]:
    """Parse a PROPFIND request body and return requested property QNames.

    Returns an empty set for allprop or if the body is empty/malformed
    (treat as allprop per RFC 4918 Section 9.1).
    """
    if not body or not body.strip():
        return set()  # Empty body = allprop
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return set()

    prop_el = root.find(_PROP)
    if prop_el is None:
        # Could be <D:allprop/> or malformed — treat as allprop
        return set()

    return {child.tag for child in prop_el}


def parse_report(body: bytes) -> tuple[str, list[str], set[str], str]:
    """Parse a REPORT request body.

    Returns (report_type, hrefs, requested_props, sync_token):
    - report_type: 'calendar-multiget', 'calendar-query', 'sync-collection'
    - hrefs: list of href values (for multiget)
    - requested_props: set of property QNames
    - sync_token: previous sync token (for sync-collection)
    """
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return ("unknown", [], set(), "")

    report_type = "unknown"
    if root.tag == _CALENDAR_MULTIGET:
        report_type = "calendar-multiget"
    elif root.tag == _CALENDAR_QUERY:
        report_type = "calendar-query"
    elif root.tag == _SYNC_COLLECTION:
        report_type = "sync-collection"

    # Extract requested properties
    props: set[str] = set()
    prop_el = root.find(_PROP)
    if prop_el is not None:
        props = {child.tag for child in prop_el}

    # Extract hrefs (for multiget)
    hrefs = [el.text or "" for el in root.findall(_HREF) if el.text]

    # Extract sync-token (for sync-collection)
    sync_token = ""
    token_el = root.find(_SYNC_TOKEN)
    if token_el is not None and token_el.text:
        sync_token = token_el.text

    return report_type, hrefs, props, sync_token


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _make_propstat(props: dict[str, Any], status: str = "HTTP/1.1 200 OK") -> ET.Element:
    """Build a <D:propstat> element with properties and status."""
    propstat = ET.Element(_PROPSTAT)
    prop_el = ET.SubElement(propstat, _PROP)

    for qname, value in props.items():
        if isinstance(value, ET.Element):
            prop_el.append(value)
        elif isinstance(value, str):
            el = ET.SubElement(prop_el, qname)
            el.text = value
        elif value is None:
            ET.SubElement(prop_el, qname)
        # else: skip

    status_el = ET.SubElement(propstat, _STATUS)
    status_el.text = status
    return propstat


def make_response(href: str, props: dict[str, Any]) -> ET.Element:
    """Build a <D:response> element for a resource."""
    response = ET.Element(_RESPONSE)
    href_el = ET.SubElement(response, _HREF)
    href_el.text = href
    response.append(_make_propstat(props))
    return response


def make_response_404(href: str) -> ET.Element:
    """Build a <D:response> with 404 status (for deleted items in sync)."""
    response = ET.Element(_RESPONSE)
    href_el = ET.SubElement(response, _HREF)
    href_el.text = href
    status_el = ET.SubElement(response, _STATUS)
    status_el.text = "HTTP/1.1 404 Not Found"
    return response


def build_multistatus(responses: list[ET.Element], sync_token: str | None = None) -> bytes:
    """Build a complete <D:multistatus> XML response body."""
    root = ET.Element(_MULTISTATUS)
    for resp in responses:
        root.append(resp)
    if sync_token:
        token_el = ET.SubElement(root, _SYNC_TOKEN)
        token_el.text = sync_token
    return ET.tostring(root, encoding="unicode", xml_declaration=True).encode("utf-8")


# ---------------------------------------------------------------------------
# Property helpers
# ---------------------------------------------------------------------------


def prop_resourcetype_collection() -> ET.Element:
    """Build <D:resourcetype><D:collection/></D:resourcetype>."""
    rt = ET.Element(_RESOURCETYPE)
    ET.SubElement(rt, _COLLECTION)
    return rt


def prop_resourcetype_calendar() -> ET.Element:
    """Build <D:resourcetype><D:collection/><C:calendar/></D:resourcetype>."""
    rt = ET.Element(_RESOURCETYPE)
    ET.SubElement(rt, _COLLECTION)
    ET.SubElement(rt, _CALENDAR)
    return rt


def prop_supported_components() -> ET.Element:
    """Build <C:supported-calendar-component-set><C:comp name="VTODO"/></C:...>."""
    el = ET.Element(_SUPPORTED_CALENDAR_COMPONENT_SET)
    comp = ET.SubElement(el, _COMP)
    comp.set("name", "VTODO")
    return el


def prop_current_user_principal(href: str) -> ET.Element:
    """Build <D:current-user-principal><D:href>...</D:href></D:...>."""
    el = ET.Element(_CURRENT_USER_PRINCIPAL)
    h = ET.SubElement(el, _HREF)
    h.text = href
    return el


def prop_calendar_home_set(href: str) -> ET.Element:
    """Build <C:calendar-home-set><D:href>...</D:href></C:...>."""
    el = ET.Element(_CALENDAR_HOME_SET)
    h = ET.SubElement(el, _HREF)
    h.text = href
    return el


def prop_calendar_data(ics_bytes: bytes) -> ET.Element:
    """Build <C:calendar-data>...ics content...</C:calendar-data>."""
    el = ET.Element(_CALENDAR_DATA)
    el.text = ics_bytes.decode("utf-8")
    return el
