"""Meeting-link detection for major video-conference providers.

Pure-Python regex matching with no Qt or network dependency. Used by
the detail panel, kanban card, and calendar surfaces to surface a
"Join" affordance when a recognized meeting URL appears in a task's
text.

This module covers the five most-common providers — Zoom, Microsoft
Teams, Google Meet, Cisco Webex, Jitsi (meet.jit.si). The long-tail
of additional providers is tracked separately and will extend the
PROVIDERS table without changing the public API.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class MeetingLink(NamedTuple):
    """A detected meeting link — provider name and the matched URL."""

    provider: str
    url: str


# Each entry: (provider display name, compiled pattern). Patterns are
# anchored on the recognizable host and path-segment shapes each
# provider uses. Trailing path / query characters are captured up to
# the next whitespace boundary so query strings (?pwd=..., ?authuser=)
# round-trip into the launched URL. Patterns are case-insensitive
# because URL hosts are; URL paths often are not, but providers reject
# malformed paths at the destination, so casing inside the path is
# left to the user's text.
_PROVIDERS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Zoom",
        re.compile(r"https?://[a-z0-9.-]+\.zoom\.us/(?:j|my|s|w)/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "Microsoft Teams",
        re.compile(r"https?://teams\.microsoft\.com/l/meetup-join/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "Microsoft Teams",
        re.compile(r"https?://teams\.live\.com/meet/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "Google Meet",
        re.compile(r"https?://meet\.google\.com/[a-z0-9\-]+(?:\?[^\s<>\"']*)?", re.IGNORECASE),
    ),
    (
        "Webex",
        re.compile(
            r"https?://[a-z0-9.-]+\.webex\.com/(?:meet|wbxmjs|j\.php|w\.php|webappng)/[^\s<>\"']+",
            re.IGNORECASE,
        ),
    ),
    (
        "Jitsi",
        re.compile(r"https?://meet\.jit\.si/[^\s<>\"']+", re.IGNORECASE),
    ),
    # Zoom for Government (separate domain from commercial Zoom)
    (
        "Zoom",
        re.compile(r"https?://[a-z0-9.-]*zoomgov\.com/(?:j|my|s|w)/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "BlueJeans",
        re.compile(
            r"https?://(?:[a-z0-9.-]+\.)?bluejeans\.com/\d+(?:[/?][^\s<>\"']*)?", re.IGNORECASE
        ),
    ),
    (
        "GoToMeeting",
        re.compile(
            r"https?://(?:[a-z0-9.-]+\.)?gotomeeting\.com/join/[^\s<>\"']+",
            re.IGNORECASE,
        ),
    ),
    (
        "GoToMeeting",
        re.compile(r"https?://meet\.goto\.com/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "GoTo Webinar",
        re.compile(
            r"https?://(?:attendee|register)\.gotowebinar\.com/[^\s<>\"']+",
            re.IGNORECASE,
        ),
    ),
    (
        "Whereby",
        re.compile(r"https?://(?:[a-z0-9.-]+\.)?whereby\.com/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "8x8",
        re.compile(r"https?://8x8\.vc/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "8x8",
        re.compile(r"https?://meetings\.8x8\.com/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "RingCentral",
        re.compile(
            r"https?://(?:meetings|app|video)\.ringcentral\.com/(?:j|meetings|join)/[^\s<>\"']+",
            re.IGNORECASE,
        ),
    ),
    # Daily.co — subdomain-per-account convention with a room path.
    # The host shape "<account>.daily.co/<room>" is recognizable
    # without false-matching the company's own marketing URLs.
    (
        "Daily.co",
        re.compile(r"https?://[a-z0-9-]+\.daily\.co/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "Skype",
        re.compile(r"https?://join\.skype\.com/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "FaceTime",
        re.compile(r"https?://facetime\.apple\.com/join[^\s<>\"']*", re.IGNORECASE),
    ),
    (
        "Riverside",
        re.compile(r"https?://(?:www\.)?riverside\.fm/(?:studio|s)/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "Around",
        re.compile(r"https?://(?:www\.)?around\.co/(?:r|join)/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "Vowel",
        re.compile(
            r"https?://(?:www\.)?vowel\.com/(?:best-meetings|meet)/[^\s<>\"']+",
            re.IGNORECASE,
        ),
    ),
    (
        "Lifesize",
        re.compile(r"https?://call\.lifesize\.com/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "Demio",
        re.compile(r"https?://event\.demio\.com/[^\s<>\"']+", re.IGNORECASE),
    ),
    (
        "Dialpad",
        re.compile(
            r"https?://(?:meet|dialpad)\.dialpad\.com/[^\s<>\"']+",
            re.IGNORECASE,
        ),
    ),
    (
        "Dialpad",
        re.compile(r"https?://dialpad\.com/conference/[^\s<>\"']+", re.IGNORECASE),
    ),
    # Discord invites — Discord is commonly used for voice/video calls
    # by smaller teams; a Discord invite is the most direct "join us
    # here" link the platform exposes.
    (
        "Discord",
        re.compile(r"https?://discord\.gg/[a-z0-9-]+", re.IGNORECASE),
    ),
    (
        "Discord",
        re.compile(r"https?://(?:www\.)?discord\.com/invite/[a-z0-9-]+", re.IGNORECASE),
    ),
]


def detect_meeting_link(text: str | None) -> MeetingLink | None:
    """Return the first recognized meeting link in *text*, or None.

    Detection is deterministic: providers are checked in declaration
    order, and within a provider the leftmost match wins. A `None` or
    empty input returns `None` immediately.
    """
    if not text:
        return None
    for provider, pattern in _PROVIDERS:
        match = pattern.search(text)
        if match:
            return MeetingLink(provider=provider, url=match.group(0))
    return None
