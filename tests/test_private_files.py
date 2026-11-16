"""Private keys, device tokens and the application's directories are
readable by the account that runs the application and by no other.

The permission checks are for POSIX systems. On Windows the files are
inside the user profile, whose access list limits them to the account,
and the functions that change permissions do nothing.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from pytodo_qt.core import paths
from pytodo_qt.core.config import ConfigManager, WebConfig
from pytodo_qt.core.models import Database
from pytodo_qt.core.private_files import (
    create_private_file,
    ensure_private_dir,
    make_private,
    write_private_file,
)
from pytodo_qt.web.device_store import WebDeviceStore
from pytodo_qt.web.server import WebServer

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def open_umask():
    """A process that gives new files to everyone, the worst case."""
    if os.name == "nt":
        yield
        return
    previous = os.umask(0)
    try:
        yield
    finally:
        os.umask(previous)


class TestWritePrivateFile:
    def test_writes_the_data(self, tmp_path: Path):
        target = tmp_path / "key.pem"
        write_private_file(target, b"secret")
        assert target.read_bytes() == b"secret"

    @posix_only
    def test_new_file_is_for_the_owner_only(self, tmp_path: Path, open_umask):
        target = tmp_path / "key.pem"
        write_private_file(target, b"secret")
        assert mode_of(target) == 0o600

    @posix_only
    def test_replaces_a_file_that_others_could_read(self, tmp_path: Path):
        """The file an earlier version wrote: its permissions do not
        carry over to the new contents."""
        target = tmp_path / "key.pem"
        target.write_bytes(b"old")
        target.chmod(0o644)
        write_private_file(target, b"new")
        assert target.read_bytes() == b"new"
        assert mode_of(target) == 0o600

    def test_leaves_no_other_file_behind(self, tmp_path: Path):
        write_private_file(tmp_path / "key.pem", b"secret")
        assert [p.name for p in tmp_path.iterdir()] == ["key.pem"]

    def test_failure_keeps_the_old_file_and_removes_the_new(self, tmp_path: Path):
        target = tmp_path / "key.pem"
        target.write_bytes(b"old")
        with (
            patch("pytodo_qt.core.private_files.os.replace", side_effect=OSError("no")),
            pytest.raises(OSError),
        ):
            write_private_file(target, b"new")
        assert target.read_bytes() == b"old"
        assert [p.name for p in tmp_path.iterdir()] == ["key.pem"]


class TestCreatePrivateFile:
    @posix_only
    def test_creates_an_empty_file_for_the_owner_only(self, tmp_path: Path, open_umask):
        target = tmp_path / "devices.db"
        create_private_file(target)
        assert target.read_bytes() == b""
        assert mode_of(target) == 0o600

    def test_leaves_an_existing_file_as_it_is(self, tmp_path: Path):
        target = tmp_path / "devices.db"
        target.write_bytes(b"contents")
        create_private_file(target)
        assert target.read_bytes() == b"contents"


@posix_only
class TestMakePrivate:
    @pytest.mark.parametrize(
        ("before", "after"),
        [(0o644, 0o600), (0o664, 0o600), (0o640, 0o600), (0o444, 0o400), (0o600, 0o600)],
    )
    def test_file(self, tmp_path: Path, before: int, after: int):
        target = tmp_path / "file"
        target.write_bytes(b"")
        target.chmod(before)
        make_private(target)
        assert mode_of(target) == after

    def test_directory(self, tmp_path: Path):
        target = tmp_path / "dir"
        target.mkdir()
        target.chmod(0o755)
        make_private(target)
        assert mode_of(target) == 0o700

    def test_missing_path_is_passed_over(self, tmp_path: Path):
        make_private(tmp_path / "absent")

    def test_failure_is_not_raised(self, tmp_path: Path):
        target = tmp_path / "file"
        target.write_bytes(b"")
        target.chmod(0o644)
        with patch.object(Path, "chmod", side_effect=PermissionError("no")):
            make_private(target)
        assert mode_of(target) == 0o644


@posix_only
class TestEnsurePrivateDir:
    def test_creates_for_the_owner_only(self, tmp_path: Path, open_umask):
        target = tmp_path / "parent" / "pytodo-qt"
        ensure_private_dir(target)
        assert mode_of(target) == 0o700

    def test_restricts_an_existing_directory(self, tmp_path: Path):
        target = tmp_path / "pytodo-qt"
        target.mkdir()
        target.chmod(0o755)
        ensure_private_dir(target)
        assert mode_of(target) == 0o700

    def test_parent_is_left_alone(self, tmp_path: Path):
        """The parent is the account's own ~/.config and the like, which
        other applications share."""
        parent = tmp_path / "parent"
        parent.mkdir()
        parent.chmod(0o755)
        (parent / "pytodo-qt").mkdir()
        ensure_private_dir(parent / "pytodo-qt")
        assert mode_of(parent) == 0o755


@posix_only
class TestApplicationDirectories:
    def test_config_manager_creates_them_private(self, tmp_path: Path, open_umask):
        manager = ConfigManager(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
        manager.state_dir = tmp_path / "state"
        manager.ensure_directories()
        for name in ("config", "data", "state"):
            assert mode_of(tmp_path / name) == 0o700, name

    def test_config_manager_restricts_existing_ones(self, tmp_path: Path):
        for name in ("config", "data", "state"):
            (tmp_path / name).mkdir()
            (tmp_path / name).chmod(0o755)
        manager = ConfigManager(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
        manager.state_dir = tmp_path / "state"
        manager.ensure_directories()
        for name in ("config", "data", "state"):
            assert mode_of(tmp_path / name) == 0o700, name

    def test_paths_ensure_directories(self, tmp_path: Path, monkeypatch, open_umask):
        for variable, name in (
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_STATE_HOME", "state"),
        ):
            monkeypatch.setenv(variable, str(tmp_path / name))
        paths.ensure_directories()
        for name in ("config", "data", "state"):
            assert mode_of(tmp_path / name / "pytodo-qt") == 0o700, name


@posix_only
class TestWebKeys:
    def _generate(self, directory: Path) -> None:
        WebServer._generate_ca(directory / "ca_cert.pem", directory / "ca_key.pem")
        WebServer._generate_server_cert(
            directory / "ca_cert.pem",
            directory / "ca_key.pem",
            directory / "web_cert.pem",
            directory / "web_key.pem",
            ["127.0.0.1"],
        )

    def test_generated_keys_are_for_the_owner_only(self, tmp_path: Path, open_umask):
        self._generate(tmp_path)
        assert mode_of(tmp_path / "ca_key.pem") == 0o600
        assert mode_of(tmp_path / "web_key.pem") == 0o600

    def test_regenerated_keys_replace_readable_ones(self, tmp_path: Path):
        self._generate(tmp_path)
        (tmp_path / "ca_key.pem").chmod(0o644)
        (tmp_path / "web_key.pem").chmod(0o644)
        self._generate(tmp_path)
        assert mode_of(tmp_path / "ca_key.pem") == 0o600
        assert mode_of(tmp_path / "web_key.pem") == 0o600

    def test_server_start_restricts_keys_from_an_earlier_version(self, tmp_path: Path):
        """The keys are kept, so that devices that trust the certificate
        go on trusting it; only their permissions change."""
        manager = ConfigManager(config_dir=tmp_path, data_dir=tmp_path)
        server = WebServer(database=Database(), config=WebConfig(), config_manager=manager)
        assert server._create_ssl_context() is not None
        ca_key = (tmp_path / "ca_key.pem").read_bytes()
        (tmp_path / "ca_key.pem").chmod(0o644)
        (tmp_path / "web_key.pem").chmod(0o644)

        assert server._create_ssl_context() is not None

        assert mode_of(tmp_path / "ca_key.pem") == 0o600
        assert mode_of(tmp_path / "web_key.pem") == 0o600
        assert (tmp_path / "ca_key.pem").read_bytes() == ca_key


@posix_only
class TestDeviceDatabase:
    def _files(self, directory: Path) -> list[Path]:
        return sorted(directory.glob("web_devices.db*"))

    def test_database_and_its_side_files_are_for_the_owner_only(self, tmp_path: Path, open_umask):
        store = WebDeviceStore(tmp_path / "web_devices.db")
        store.open()
        try:
            store.add_device("Phone", "agent", "pin", 0)
            files = self._files(tmp_path)
            # The write-ahead log and its index exist while the store is open.
            assert {p.name for p in files} >= {"web_devices.db", "web_devices.db-wal"}
            for path in files:
                assert mode_of(path) == 0o600, path.name
        finally:
            store.close()

    def test_open_restricts_a_database_from_an_earlier_version(self, tmp_path: Path):
        store = WebDeviceStore(tmp_path / "web_devices.db")
        store.open()
        device = store.add_device("Phone", "agent", "pin", 0)
        store.close()
        (tmp_path / "web_devices.db").chmod(0o644)

        again = WebDeviceStore(tmp_path / "web_devices.db")
        again.open()
        try:
            assert mode_of(tmp_path / "web_devices.db") == 0o600
            # The paired devices are kept.
            assert again.get_device_by_token(device.token) is not None
        finally:
            again.close()

    def test_database_set_aside_as_corrupt_is_restricted(self, tmp_path: Path):
        (tmp_path / "web_devices.db").write_bytes(b"not a database" * 100)
        (tmp_path / "web_devices.db").chmod(0o644)
        store = WebDeviceStore(tmp_path / "web_devices.db")
        store.open()
        try:
            assert mode_of(tmp_path / "web_devices.db.corrupt") == 0o600
            assert mode_of(tmp_path / "web_devices.db") == 0o600
        finally:
            store.close()
