"""The web server's certificates: when one is replaced, and which one a
browser is shown.

A browser that was let through by hand accepted one certificate for one
address. The server made a new certificate whenever the set of the
machine's addresses changed, a temporary IPv6 address among them, and
every such browser was turned away until it accepted the new one
(#111).
"""

from __future__ import annotations

import asyncio
import datetime
import os
import ssl
import stat
from pathlib import Path

import pytest
from cryptography import x509

from pytodo_qt.core import network
from pytodo_qt.core.config import ConfigManager, WebConfig
from pytodo_qt.core.models import Database
from pytodo_qt.web import server as web_server
from pytodo_qt.web.server import WebServer

HOST = "Planner.local"


class Machine:
    """The host name and the addresses the machine has, as the server
    is told them."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.host_name: str | None = HOST
        self.ipv4 = ["192.168.1.20"]
        self.ipv6 = ["2001:db8::1111"]
        monkeypatch.setattr(network, "get_local_hostname", lambda: self.host_name)
        monkeypatch.setattr(
            network, "get_all_local_addresses", lambda: (list(self.ipv4), list(self.ipv6))
        )


@pytest.fixture(scope="module")
def certificate_authority(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One CA for the module: making its key takes a second each time."""
    directory = tmp_path_factory.mktemp("ca")
    WebServer._generate_ca(directory / "ca_cert.pem", directory / "ca_key.pem")
    return directory


@pytest.fixture
def machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, certificate_authority: Path
) -> Machine:
    """The machine, with the CA already in the test's directory."""
    for name in ("ca_cert.pem", "ca_key.pem"):
        (tmp_path / name).write_bytes((certificate_authority / name).read_bytes())
    return Machine(monkeypatch)


def make_server(directory: Path) -> WebServer:
    manager = ConfigManager(config_dir=directory, data_dir=directory)
    return WebServer(database=Database(), config=WebConfig(), config_manager=manager)


def start(directory: Path) -> ssl.SSLContext:
    """What a start of the application does with the certificates."""
    context = make_server(directory)._create_ssl_context()
    assert context is not None
    return context


def certificate(path: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(path.read_bytes())


def begins(cert: x509.Certificate) -> datetime.datetime:
    """When a certificate begins to serve, with any version of the
    library that reads it."""
    return getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before.replace(
        tzinfo=datetime.UTC
    )


def ends(cert: x509.Certificate) -> datetime.datetime:
    return getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(
        tzinfo=datetime.UTC
    )


def names(path: Path) -> tuple[list[str], list[str]]:
    listed = WebServer._certificate_names(path)
    assert listed is not None
    return listed


def files(directory: Path) -> dict[str, bytes]:
    return {
        name: (directory / name).read_bytes()
        for name in ("web_cert.pem", "web_key.pem", "web_host_cert.pem", "web_host_key.pem")
    }


def earlier_version(
    directory: Path,
    addresses: list[str],
    days: int = 365,
    dns_names: tuple[str, ...] = ("localhost", HOST),
    ca: Path | None = None,
) -> None:
    """The one certificate a version before this one kept, issued by
    the CA in the directory unless another is given."""
    issuer = ca or directory
    WebServer._generate_server_cert(
        issuer / "ca_cert.pem",
        issuer / "ca_key.pem",
        directory / "web_cert.pem",
        directory / "web_key.pem",
        addresses,
        list(dns_names),
        days,
    )


class TestWhatIsGenerated:
    def test_a_first_start_makes_a_certificate_for_each(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        assert names(tmp_path / "web_host_cert.pem") == (["localhost", HOST], [])
        assert names(tmp_path / "web_cert.pem") == (
            ["localhost", HOST],
            ["127.0.0.1", "192.168.1.20"],
        )

    def test_no_ipv6_address_is_listed(self, tmp_path: Path, machine: Machine):
        """The server does not listen on one, and the one the system
        prefers is temporary."""
        start(tmp_path)
        for name in ("web_cert.pem", "web_host_cert.pem"):
            assert not [address for address in names(tmp_path / name)[1] if ":" in address]

    def test_a_certificate_serves_for_about_two_years(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        for name in ("web_cert.pem", "web_host_cert.pem"):
            cert = certificate(tmp_path / name)
            # No longer than Apple's systems accept.
            assert ends(cert) - begins(cert) == datetime.timedelta(days=825)

    def test_a_certificate_begins_a_day_before_it_is_made(self, tmp_path: Path, machine: Machine):
        """A device whose clock is behind, or this machine after its
        clock was set back by some hours, meets one that serves."""
        start(tmp_path)
        now = datetime.datetime.now(datetime.UTC)
        for name in ("web_cert.pem", "web_host_cert.pem"):
            ahead = now - begins(certificate(tmp_path / name))
            assert datetime.timedelta(hours=23) < ahead < datetime.timedelta(hours=25)

    def test_both_are_issued_by_the_local_ca(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        ca = certificate(tmp_path / "ca_cert.pem")
        for name in ("web_cert.pem", "web_host_cert.pem"):
            certificate(tmp_path / name).verify_directly_issued_by(ca)

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
    def test_both_keys_are_for_the_owner_only(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        for name in ("web_key.pem", "web_host_key.pem"):
            assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600

    def test_without_a_host_name_there_is_the_one_for_addresses(
        self, tmp_path: Path, machine: Machine
    ):
        machine.host_name = None
        start(tmp_path)
        assert not (tmp_path / "web_host_cert.pem").exists()
        assert names(tmp_path / "web_cert.pem") == (["localhost"], ["127.0.0.1", "192.168.1.20"])


class TestWhatLeavesThemAlone:
    def test_a_second_start_changes_nothing(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        before = files(tmp_path)
        start(tmp_path)
        assert files(tmp_path) == before

    def test_a_new_ipv6_address_changes_nothing(self, tmp_path: Path, machine: Machine):
        """A temporary address is replaced about daily."""
        start(tmp_path)
        before = files(tmp_path)
        machine.ipv6 = ["2001:db8::2222"]
        start(tmp_path)
        machine.ipv6 = []
        start(tmp_path)
        assert files(tmp_path) == before

    def test_losing_an_address_changes_nothing(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        before = files(tmp_path)
        machine.ipv4 = []
        start(tmp_path)
        assert files(tmp_path) == before

    def test_the_host_name_in_other_letters_changes_nothing(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        before = files(tmp_path)
        machine.host_name = HOST.lower()
        start(tmp_path)
        assert files(tmp_path) == before


class TestANewAddress:
    def test_only_the_certificate_for_addresses_is_replaced(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        before = files(tmp_path)
        machine.ipv4 = ["10.0.0.7"]
        start(tmp_path)
        after = files(tmp_path)
        assert after["web_cert.pem"] != before["web_cert.pem"]
        # A browser at the host name meets the certificate it accepted.
        assert after["web_host_cert.pem"] == before["web_host_cert.pem"]
        assert after["web_host_key.pem"] == before["web_host_key.pem"]

    def test_the_addresses_listed_before_are_kept(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        machine.ipv4 = ["10.0.0.7"]
        start(tmp_path)
        assert names(tmp_path / "web_cert.pem")[1] == ["192.168.1.20", "127.0.0.1", "10.0.0.7"]

    def test_going_back_to_an_earlier_address_changes_nothing(
        self, tmp_path: Path, machine: Machine
    ):
        """Home, elsewhere and home again; a VPN turned on and off."""
        start(tmp_path)
        machine.ipv4 = ["10.0.0.7"]
        start(tmp_path)
        before = files(tmp_path)
        machine.ipv4 = ["192.168.1.20"]
        start(tmp_path)
        machine.ipv4 = ["10.0.0.7", "192.168.1.20"]
        start(tmp_path)
        assert files(tmp_path) == before

    def test_the_oldest_addresses_go_when_there_are_too_many(self):
        earlier = [f"10.0.0.{number}" for number in range(1, 31)]
        kept = WebServer._names_to_keep(earlier, ["127.0.0.1", "192.168.1.20"])
        assert len(kept) == web_server._NAMES_KEPT
        assert kept[-2:] == ["127.0.0.1", "192.168.1.20"]
        assert kept[0] == "10.0.0.17"
        assert kept[-3] == "10.0.0.30"

    def test_a_name_in_use_is_listed_once(self):
        assert WebServer._names_to_keep(["localhost", "planner.local"], ["localhost", HOST]) == [
            "localhost",
            HOST,
        ]


class TestWhatReplacesTheOneForTheHostName:
    def test_a_new_host_name(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        before = files(tmp_path)
        machine.host_name = "Study.local"
        start(tmp_path)
        after = files(tmp_path)
        assert after["web_host_cert.pem"] != before["web_host_cert.pem"]
        # The name it had is kept: the machine may be given it back.
        assert names(tmp_path / "web_host_cert.pem")[0] == [HOST, "localhost", "Study.local"]
        # The one for addresses lists all it has to.
        assert after["web_cert.pem"] == before["web_cert.pem"]

    def test_few_days_left(self, tmp_path: Path, machine: Machine):
        earlier_version(tmp_path, [], days=web_server._RENEW_DAYS_BEFORE_END - 1)
        (tmp_path / "web_host_cert.pem").write_bytes((tmp_path / "web_cert.pem").read_bytes())
        (tmp_path / "web_host_key.pem").write_bytes((tmp_path / "web_key.pem").read_bytes())
        before = files(tmp_path)
        start(tmp_path)
        after = files(tmp_path)
        assert after["web_host_cert.pem"] != before["web_host_cert.pem"]
        assert after["web_cert.pem"] != before["web_cert.pem"]
        left = ends(certificate(tmp_path / "web_host_cert.pem")) - datetime.datetime.now(
            datetime.UTC
        )
        assert left > datetime.timedelta(days=800)

    def test_enough_days_left(self, tmp_path: Path, machine: Machine):
        earlier_version(
            tmp_path, ["127.0.0.1", "192.168.1.20"], days=web_server._RENEW_DAYS_BEFORE_END + 2
        )
        before = (tmp_path / "web_cert.pem").read_bytes()
        start(tmp_path)
        assert (tmp_path / "web_cert.pem").read_bytes() == before

    def test_a_file_that_is_no_certificate(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        (tmp_path / "web_host_cert.pem").write_text("not a certificate")
        start(tmp_path)
        assert names(tmp_path / "web_host_cert.pem")[0] == ["localhost", HOST]

    def test_a_missing_key(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        before = files(tmp_path)
        (tmp_path / "web_host_key.pem").unlink()
        start(tmp_path)
        assert files(tmp_path)["web_host_cert.pem"] != before["web_host_cert.pem"]

    def test_another_certificates_key(self, tmp_path: Path, machine: Machine):
        """The server could not start with it, at this start or any
        after: nothing else would ever replace the pair."""
        start(tmp_path)
        machine.ipv4 = ["10.0.0.7"]
        start(tmp_path)  # the two keys now differ
        before = files(tmp_path)
        (tmp_path / "web_host_key.pem").write_bytes(before["web_key.pem"])
        start(tmp_path)
        after = files(tmp_path)
        assert after["web_host_cert.pem"] != before["web_host_cert.pem"]
        assert after["web_cert.pem"] == before["web_cert.pem"]
        start(tmp_path)
        assert files(tmp_path) == after

    @pytest.mark.parametrize("pair", ["web_host", "web"])
    @pytest.mark.parametrize("damage", [b"", b"not a key"])
    def test_a_key_that_cannot_be_read(
        self, tmp_path: Path, machine: Machine, pair: str, damage: bytes
    ):
        start(tmp_path)
        machine.ipv4 = ["10.0.0.7"]
        start(tmp_path)  # the two certificates now differ
        before = files(tmp_path)
        (tmp_path / f"{pair}_key.pem").write_bytes(damage)
        start(tmp_path)
        after = files(tmp_path)
        assert after[f"{pair}_cert.pem"] != before[f"{pair}_cert.pem"]
        other = "web" if pair == "web_host" else "web_host"
        assert after[f"{other}_cert.pem"] == before[f"{other}_cert.pem"]

    def test_one_that_does_not_serve_yet(self, tmp_path: Path, machine: Machine):
        """Made while the machine's clock was a month ahead."""
        from cryptography.hazmat.primitives import hashes, serialization

        start(tmp_path)
        ca_key = serialization.load_pem_private_key(
            (tmp_path / "ca_key.pem").read_bytes(), password=None
        )
        now = datetime.datetime.now(datetime.UTC)
        for name in ("web", "web_host"):
            made = certificate(tmp_path / f"{name}_cert.pem")
            ahead = (
                x509.CertificateBuilder()
                .subject_name(made.subject)
                .issuer_name(made.issuer)
                .public_key(made.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now + datetime.timedelta(days=30))
                .not_valid_after(now + datetime.timedelta(days=855))
                .add_extension(
                    made.extensions.get_extension_for_class(x509.SubjectAlternativeName).value,
                    critical=False,
                )
                .sign(ca_key, hashes.SHA256())  # type: ignore[arg-type]
            )
            (tmp_path / f"{name}_cert.pem").write_bytes(
                ahead.public_bytes(serialization.Encoding.PEM)
            )
        before = files(tmp_path)

        start(tmp_path)

        after = files(tmp_path)
        for name in ("web_cert.pem", "web_host_cert.pem"):
            assert after[name] != before[name]
            assert begins(certificate(tmp_path / name)) < now

    def test_a_new_certificate_authority(self, tmp_path: Path, machine: Machine):
        server = make_server(tmp_path)
        assert server._create_ssl_context() is not None
        before = files(tmp_path)
        old_ca = (tmp_path / "ca_cert.pem").read_bytes()

        assert server.regenerate_certs() is True

        after = files(tmp_path)
        assert (tmp_path / "ca_cert.pem").read_bytes() != old_ca
        ca = certificate(tmp_path / "ca_cert.pem")
        for name in ("web_cert.pem", "web_host_cert.pem"):
            assert after[name] != before[name]
            certificate(tmp_path / name).verify_directly_issued_by(ca)
        assert server._config is not None
        assert server._config.ca_generation == 1


class TestAfterAnEarlierVersion:
    """A version before this one kept one certificate, for the host name
    and for every address, an IPv6 address among them."""

    def test_the_certificate_browsers_accepted_is_kept_for_both(
        self, tmp_path: Path, machine: Machine
    ):
        earlier_version(tmp_path, ["127.0.0.1", "192.168.1.20", "2001:db8::9999"])
        accepted = (tmp_path / "web_cert.pem").read_bytes()
        start(tmp_path)
        assert (tmp_path / "web_cert.pem").read_bytes() == accepted
        assert (tmp_path / "web_host_cert.pem").read_bytes() == accepted
        assert (tmp_path / "web_host_key.pem").read_bytes() == (
            tmp_path / "web_key.pem"
        ).read_bytes()

    def test_it_is_kept_for_the_host_name_when_an_address_is_new(
        self, tmp_path: Path, machine: Machine
    ):
        earlier_version(tmp_path, ["127.0.0.1", "172.16.0.5", "2001:db8::9999"])
        accepted = (tmp_path / "web_cert.pem").read_bytes()
        start(tmp_path)
        assert (tmp_path / "web_host_cert.pem").read_bytes() == accepted
        assert (tmp_path / "web_cert.pem").read_bytes() != accepted
        # The IPv6 address is not carried over.
        assert names(tmp_path / "web_cert.pem")[1] == ["172.16.0.5", "127.0.0.1", "192.168.1.20"]

    @pytest.mark.parametrize("why", ["few days left", "another host name", "another CA"])
    def test_one_that_does_not_serve_for_the_host_name_is_not_kept_for_it(
        self, tmp_path: Path, machine: Machine, tmp_path_factory: pytest.TempPathFactory, why: str
    ):
        """It would be presented for the host name and then replaced:
        two certificates for a browser to accept, not one."""
        addresses = ["127.0.0.1", "192.168.1.20"]
        if why == "few days left":
            earlier_version(tmp_path, addresses, days=web_server._RENEW_DAYS_BEFORE_END - 1)
        elif why == "another host name":
            earlier_version(tmp_path, addresses, dns_names=("localhost", "Study.local"))
        else:
            other = tmp_path_factory.mktemp("other-ca")
            WebServer._generate_ca(other / "ca_cert.pem", other / "ca_key.pem")
            earlier_version(tmp_path, addresses, ca=other)
        old = (tmp_path / "web_cert.pem").read_bytes()

        start(tmp_path)

        assert (tmp_path / "web_host_cert.pem").read_bytes() != old
        host = certificate(tmp_path / "web_host_cert.pem")
        host.verify_directly_issued_by(certificate(tmp_path / "ca_cert.pem"))
        assert HOST in names(tmp_path / "web_host_cert.pem")[0]
        assert ends(host) - datetime.datetime.now(datetime.UTC) > datetime.timedelta(days=800)

    def test_a_copy_cut_short_is_made_again(self, tmp_path: Path, machine: Machine):
        """The key is written first; without its certificate the copy
        counts as not made."""
        earlier_version(tmp_path, ["127.0.0.1", "192.168.1.20"])
        accepted = (tmp_path / "web_cert.pem").read_bytes()
        (tmp_path / "web_host_key.pem").write_bytes((tmp_path / "web_key.pem").read_bytes())
        start(tmp_path)
        assert (tmp_path / "web_host_cert.pem").read_bytes() == accepted

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
    def test_the_copied_key_is_for_the_owner_only(self, tmp_path: Path, machine: Machine):
        earlier_version(tmp_path, ["127.0.0.1", "192.168.1.20"])
        before = os.umask(0)
        try:
            start(tmp_path)
        finally:
            os.umask(before)
        assert stat.S_IMODE((tmp_path / "web_host_key.pem").stat().st_mode) == 0o600

    def test_then_it_stays(self, tmp_path: Path, machine: Machine):
        earlier_version(tmp_path, ["127.0.0.1", "192.168.1.20", "2001:db8::9999"])
        start(tmp_path)
        before = files(tmp_path)
        machine.ipv6 = ["2001:db8::3333"]
        start(tmp_path)
        assert files(tmp_path) == before


class TestWhichOneABrowserIsShown:
    async def _shown(self, context: ssl.SSLContext, asked_for: str) -> bytes:
        """The certificate a browser is shown that asks for the server
        by this name ("" for an address, which names nothing)."""
        seen: list[bytes] = []

        async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writer.close()

        listening = await asyncio.start_server(serve, "127.0.0.1", 0, ssl=context)
        port = listening.sockets[0].getsockname()[1]
        browser = ssl.create_default_context()
        browser.check_hostname = False
        browser.verify_mode = ssl.CERT_NONE
        try:
            _, writer = await asyncio.open_connection(
                "127.0.0.1", port, ssl=browser, server_hostname=asked_for
            )
            seen.append(writer.get_extra_info("ssl_object").getpeercert(binary_form=True))
            writer.close()
        finally:
            listening.close()
            await listening.wait_closed()
        return ssl.DER_cert_to_PEM_cert(seen[0]).encode()

    def _same(self, shown: bytes, path: Path) -> bool:
        return certificate(path) == x509.load_pem_x509_certificate(shown)

    @pytest.mark.asyncio
    async def test_by_host_name_the_one_for_the_host_name(self, tmp_path: Path, machine: Machine):
        context = start(tmp_path)
        machine.ipv4 = ["10.0.0.7"]
        context = start(tmp_path)  # the two certificates now differ
        assert self._same(await self._shown(context, HOST), tmp_path / "web_host_cert.pem")
        # A browser sends the name in small letters.
        assert self._same(await self._shown(context, HOST.lower()), tmp_path / "web_host_cert.pem")
        assert self._same(await self._shown(context, "localhost"), tmp_path / "web_host_cert.pem")

    @pytest.mark.asyncio
    async def test_by_address_the_one_for_addresses(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        machine.ipv4 = ["10.0.0.7"]
        context = start(tmp_path)
        assert self._same(await self._shown(context, ""), tmp_path / "web_cert.pem")

    @pytest.mark.asyncio
    async def test_by_another_name_the_one_for_addresses(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        machine.ipv4 = ["10.0.0.7"]
        context = start(tmp_path)
        assert self._same(await self._shown(context, "other.example"), tmp_path / "web_cert.pem")

    @pytest.mark.asyncio
    async def test_a_new_address_does_not_change_what_the_host_name_shows(
        self, tmp_path: Path, machine: Machine
    ):
        first = await self._shown(start(tmp_path), HOST)
        machine.ipv4 = ["10.0.0.7"]
        machine.ipv6 = ["2001:db8::4444"]
        assert await self._shown(start(tmp_path), HOST) == first


class TestWithoutAHostName:
    """The machine had a host name and has none at this start. The
    certificate for the host name is still presented for the names it
    lists, so it is still looked after."""

    def test_a_start_leaves_it_as_it_is(self, tmp_path: Path, machine: Machine):
        start(tmp_path)
        before = files(tmp_path)
        machine.host_name = None
        start(tmp_path)
        assert files(tmp_path) == before

    def test_a_damaged_one_is_replaced_and_the_server_starts(
        self, tmp_path: Path, machine: Machine
    ):
        start(tmp_path)
        machine.host_name = None
        (tmp_path / "web_host_cert.pem").write_text("not a certificate")
        start(tmp_path)
        assert names(tmp_path / "web_host_cert.pem")[0] == ["localhost"]

    def test_a_new_certificate_authority_replaces_it_too(self, tmp_path: Path, machine: Machine):
        server = make_server(tmp_path)
        assert server._create_ssl_context() is not None
        machine.host_name = None
        assert server.regenerate_certs() is True
        ca = certificate(tmp_path / "ca_cert.pem")
        certificate(tmp_path / "web_host_cert.pem").verify_directly_issued_by(ca)
        # The name it had is kept for the machine's getting it back.
        assert names(tmp_path / "web_host_cert.pem")[0] == [HOST, "localhost"]


class TestACertificateAuthorityOutOfStep:
    """The CA's key is not the one its certificate was made for: a new
    CA was cut short between the two files, or one of them was put back
    from a copy."""

    def _out_of_step(self, directory: Path, other: Path) -> None:
        (directory / "ca_key.pem").write_bytes((other / "ca_key.pem").read_bytes())

    @pytest.fixture
    def other_ca(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        directory = tmp_path_factory.mktemp("other-ca")
        WebServer._generate_ca(directory / "ca_cert.pem", directory / "ca_key.pem")
        return directory

    def test_what_it_issued_before_serves_until_something_is_due(
        self, tmp_path: Path, machine: Machine, other_ca: Path
    ):
        start(tmp_path)
        before = files(tmp_path)
        ca = (tmp_path / "ca_cert.pem").read_bytes()
        self._out_of_step(tmp_path, other_ca)
        start(tmp_path)
        assert files(tmp_path) == before
        assert (tmp_path / "ca_cert.pem").read_bytes() == ca

    def test_when_a_certificate_is_due_a_new_one_is_made_once(
        self, tmp_path: Path, machine: Machine, other_ca: Path
    ):
        server = make_server(tmp_path)
        assert server._create_ssl_context() is not None
        old_ca = (tmp_path / "ca_cert.pem").read_bytes()
        self._out_of_step(tmp_path, other_ca)
        machine.ipv4 = ["10.0.0.7"]

        assert server._create_ssl_context() is not None

        assert (tmp_path / "ca_cert.pem").read_bytes() != old_ca
        assert WebServer._ca_fits(tmp_path / "ca_cert.pem", tmp_path / "ca_key.pem")
        ca = certificate(tmp_path / "ca_cert.pem")
        for name in ("web_cert.pem", "web_host_cert.pem"):
            certificate(tmp_path / name).verify_directly_issued_by(ca)
        # Devices that installed the CA before are shown as needing this one.
        assert server._config is not None
        assert server._config.ca_generation == 1
        # And that is the end of it: the next start replaces nothing.
        after = files(tmp_path)
        assert server._create_ssl_context() is not None
        assert files(tmp_path) == after
        assert server._config.ca_generation == 1


class TestTheHostName:
    """The name the certificate for the host name is made for must not
    follow the network the machine is on."""

    def test_on_macos_it_is_the_systems_own_mdns_name(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(network.sys, "platform", "darwin")
        monkeypatch.setattr(network, "_macos_local_hostname", lambda: "Planner")
        # What the network the machine is on calls it.
        monkeypatch.setattr(network.socket, "gethostname", lambda: "dhcp-10-1-2-3.example.com")
        assert network.get_local_hostname() == "Planner.local"

    def test_on_macos_without_that_name_it_is_the_first_label(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(network.sys, "platform", "darwin")
        monkeypatch.setattr(network, "_macos_local_hostname", lambda: None)
        monkeypatch.setattr(network.socket, "gethostname", lambda: "Planner.lan")
        assert network.get_local_hostname() == "Planner.local"

    @pytest.mark.parametrize(
        ("system_name", "expected"),
        [
            ("planner", "planner.local"),
            ("Planner.local", "Planner.local"),
            ("planner.example.com", "planner.local"),
            ("localhost", None),
            ("localhost.localdomain", None),
            ("", None),
        ],
    )
    def test_elsewhere_it_is_the_first_label(
        self, monkeypatch: pytest.MonkeyPatch, system_name: str, expected: str | None
    ):
        monkeypatch.setattr(network.sys, "platform", "linux")
        monkeypatch.setattr(network.socket, "gethostname", lambda: system_name)
        assert network.get_local_hostname() == expected

    def test_a_system_that_gives_no_name(self, monkeypatch: pytest.MonkeyPatch):
        def fails() -> str:
            raise OSError("no name")

        monkeypatch.setattr(network.sys, "platform", "linux")
        monkeypatch.setattr(network.socket, "gethostname", fails)
        assert network.get_local_hostname() is None

    def test_the_macos_setting_is_read_without_failing(self, monkeypatch: pytest.MonkeyPatch):
        """Whatever the command does: missing, or an error."""

        def missing(*args: object, **kwargs: object) -> object:
            raise FileNotFoundError("scutil")

        monkeypatch.setattr(network.subprocess, "run", missing)
        assert network._macos_local_hostname() is None

        class Result:
            returncode = 1
            stdout = ""

        monkeypatch.setattr(network.subprocess, "run", lambda *a, **k: Result())
        assert network._macos_local_hostname() is None

        Result.returncode = 0
        Result.stdout = "Planner\n"
        assert network._macos_local_hostname() == "Planner"
