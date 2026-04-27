"""Tests for pytodo_qt.core.meeting_link.

Pure regex matching — no Qt or network dependency.
"""

from __future__ import annotations

import pytest

from pytodo_qt.core.meeting_link import MeetingLink, detect_meeting_link


class TestProviderDetection:
    """Each provider has at least one positive case covering the typical URL
    shape that provider produces, plus a negative-content case."""

    @pytest.mark.parametrize(
        ("text", "provider", "url"),
        [
            (
                "Standup at 9 https://us02web.zoom.us/j/12345678901?pwd=abcDEF",
                "Zoom",
                "https://us02web.zoom.us/j/12345678901?pwd=abcDEF",
            ),
            (
                "PMI https://acme.zoom.us/my/userroom",
                "Zoom",
                "https://acme.zoom.us/my/userroom",
            ),
            (
                "Daily https://teams.microsoft.com/l/meetup-join/19%3aabc%40thread.v2/0",
                "Microsoft Teams",
                "https://teams.microsoft.com/l/meetup-join/19%3aabc%40thread.v2/0",
            ),
            (
                "Sync https://teams.live.com/meet/9876?p=xyz",
                "Microsoft Teams",
                "https://teams.live.com/meet/9876?p=xyz",
            ),
            (
                "Review https://meet.google.com/abc-defg-hij",
                "Google Meet",
                "https://meet.google.com/abc-defg-hij",
            ),
            (
                "Demo https://example.webex.com/meet/userroom",
                "Webex",
                "https://example.webex.com/meet/userroom",
            ),
            (
                "Webex meeting https://acme.webex.com/webappng/sites/acme/meeting/info/12345",
                "Webex",
                "https://acme.webex.com/webappng/sites/acme/meeting/info/12345",
            ),
            (
                "Catchup https://meet.jit.si/MyTeamRoom",
                "Jitsi",
                "https://meet.jit.si/MyTeamRoom",
            ),
            (
                "case-insensitive HTTP HTTPS://US02WEB.ZOOM.US/J/12345",
                "Zoom",
                "HTTPS://US02WEB.ZOOM.US/J/12345",
            ),
        ],
    )
    def test_positive(self, text: str, provider: str, url: str) -> None:
        result = detect_meeting_link(text)
        assert result is not None
        assert result.provider == provider
        assert result.url == url


class TestNegativeContent:
    """Inputs that must NOT match any provider regex."""

    @pytest.mark.parametrize(
        "text",
        [
            "no link here",
            "",
            "Read https://example.com/article",
            "Watch https://youtube.com/watch?v=abc",
            "Bug https://github.com/owner/repo/issues/1",
            # Plausibly URL-shaped but not a recognized provider host:
            "ad https://zoom.example.com/j/abc",  # zoom in a different domain
            "ad https://teams.example.com/meet/abc",  # teams in a different domain
        ],
    )
    def test_no_match(self, text: str) -> None:
        assert detect_meeting_link(text) is None

    def test_none_input(self) -> None:
        assert detect_meeting_link(None) is None


class TestMultipleLinks:
    """The first recognized link wins, in declaration order across the
    provider table and leftmost-within-provider."""

    def test_two_zoom_links_takes_first(self) -> None:
        text = "Switch from https://us02web.zoom.us/j/111 to https://us02web.zoom.us/j/222"
        result = detect_meeting_link(text)
        assert result is not None
        assert result.url == "https://us02web.zoom.us/j/111"


class TestNamedTupleApi:
    """detect_meeting_link returns a MeetingLink NamedTuple."""

    def test_return_type(self) -> None:
        result = detect_meeting_link("https://meet.jit.si/AB")
        assert isinstance(result, MeetingLink)
        assert result[0] == result.provider
        assert result[1] == result.url
