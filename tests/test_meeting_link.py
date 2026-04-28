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


class TestExtendedProviders:
    """Coverage for the long-tail providers added by extending the
    PROVIDERS table beyond the original five (Zoom / Teams / Meet /
    Webex / Jitsi)."""

    @pytest.mark.parametrize(
        ("text", "provider", "url"),
        [
            (
                "Government https://example.zoomgov.com/j/12345",
                "Zoom",
                "https://example.zoomgov.com/j/12345",
            ),
            (
                "BJ https://bluejeans.com/123456789",
                "BlueJeans",
                "https://bluejeans.com/123456789",
            ),
            (
                "GTM https://www.gotomeeting.com/join/123456789",
                "GoToMeeting",
                "https://www.gotomeeting.com/join/123456789",
            ),
            (
                "GTM new https://meet.goto.com/JohnDoe",
                "GoToMeeting",
                "https://meet.goto.com/JohnDoe",
            ),
            (
                "Webinar https://attendee.gotowebinar.com/register/123",
                "GoTo Webinar",
                "https://attendee.gotowebinar.com/register/123",
            ),
            (
                "Whereby https://whereby.com/myroom",
                "Whereby",
                "https://whereby.com/myroom",
            ),
            (
                "Whereby sub https://acme.whereby.com/myroom",
                "Whereby",
                "https://acme.whereby.com/myroom",
            ),
            (
                "8x8 https://8x8.vc/myroom",
                "8x8",
                "https://8x8.vc/myroom",
            ),
            (
                "8x8 alt https://meetings.8x8.com/12345",
                "8x8",
                "https://meetings.8x8.com/12345",
            ),
            (
                "RC https://meetings.ringcentral.com/j/123456",
                "RingCentral",
                "https://meetings.ringcentral.com/j/123456",
            ),
            (
                "RC app https://app.ringcentral.com/meetings/join/123",
                "RingCentral",
                "https://app.ringcentral.com/meetings/join/123",
            ),
            (
                "Daily https://acme.daily.co/standup",
                "Daily.co",
                "https://acme.daily.co/standup",
            ),
            (
                "Skype https://join.skype.com/AbCdEf",
                "Skype",
                "https://join.skype.com/AbCdEf",
            ),
            (
                "FaceTime https://facetime.apple.com/join#abcdef",
                "FaceTime",
                "https://facetime.apple.com/join#abcdef",
            ),
            (
                "Riverside https://riverside.fm/studio/abc-123",
                "Riverside",
                "https://riverside.fm/studio/abc-123",
            ),
            (
                "Around https://around.co/r/team-call",
                "Around",
                "https://around.co/r/team-call",
            ),
            (
                "Vowel https://vowel.com/best-meetings/abc",
                "Vowel",
                "https://vowel.com/best-meetings/abc",
            ),
            (
                "Lifesize https://call.lifesize.com/12345",
                "Lifesize",
                "https://call.lifesize.com/12345",
            ),
            (
                "Demio https://event.demio.com/anywhere/123",
                "Demio",
                "https://event.demio.com/anywhere/123",
            ),
            (
                "Dialpad https://meet.dialpad.com/standup",
                "Dialpad",
                "https://meet.dialpad.com/standup",
            ),
            (
                "Dialpad alt https://dialpad.com/conference/12345",
                "Dialpad",
                "https://dialpad.com/conference/12345",
            ),
            (
                "Discord https://discord.gg/abcDEF",
                "Discord",
                "https://discord.gg/abcDEF",
            ),
            (
                "Discord new https://discord.com/invite/xyz789",
                "Discord",
                "https://discord.com/invite/xyz789",
            ),
        ],
    )
    def test_extended_provider_positive(self, text: str, provider: str, url: str) -> None:
        result = detect_meeting_link(text)
        assert result is not None, f"no match for {text!r}"
        assert result.provider == provider
        assert result.url == url


class TestExtendedProviderNegatives:
    """Negative cases — plausibly-similar URLs that must NOT match the
    extended providers, to confirm the regexes haven't been too
    permissive."""

    @pytest.mark.parametrize(
        "text",
        [
            # Bare top-level marketing pages should not match.
            "Read https://daily.co/about",
            "Discord landing https://discord.com/",
            "GoTo top-level https://goto.com/",
            # Wrong path on a recognized host.
            "Zoom blog https://blog.zoom.us/posts/123",
            "Webex blog https://www.webex.com/blog/articles",
            # Hosts that contain a provider name as substring but are not the provider.
            "Off-host https://zoomy-app.example.com/j/123",
            "Off-host https://my-bluejeans-clone.example.com/12345",
            # Discord top-level paths that are not invites.
            "Discord settings https://discord.com/login",
        ],
    )
    def test_no_false_positive_extended(self, text: str) -> None:
        assert detect_meeting_link(text) is None
