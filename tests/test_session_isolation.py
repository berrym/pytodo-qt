"""A test session reads and writes nothing of the machine's real application.

`tests/conftest.py` points the configuration, data and state directories
at a scratch directory and the keyring at one that stores nothing. Before
it did, a run of the suite on a machine where the application is in use
wrote that application's `config.toml`: choosing a view of the calendar
saves the configuration, and tests choose views.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pytodo_qt.core import logger as logger_module
from pytodo_qt.core import paths

from .conftest import SESSION_ROOT

_ROOT = Path(SESSION_ROOT).resolve()
_VARIABLES = ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME")


def _real(*parts: str) -> Path:
    return Path.home().joinpath(*parts, paths.APP_NAME).resolve()


class TestDirectories:
    @pytest.mark.parametrize("variable", _VARIABLES)
    def test_each_variable_points_into_the_scratch_directory(self, variable):
        assert Path(os.environ[variable]).resolve().is_relative_to(_ROOT)

    @pytest.mark.parametrize(
        ("found", "real"),
        [
            (paths.get_config_dir, (".config",)),
            (paths.get_data_dir, (".local", "share")),
            (paths.get_state_dir, (".local", "state")),
        ],
    )
    def test_the_application_finds_its_directories_there(self, found, real):
        directory = found().resolve()
        assert directory.is_relative_to(_ROOT)
        assert directory != _real(*real)

    def test_the_files_are_there(self):
        for file in (paths.get_config_file(), paths.get_database_file(), paths.get_log_file()):
            assert file.resolve().is_relative_to(_ROOT)

    def test_the_log_file_the_logger_chose_is_there(self):
        """The logger works its file's place out for itself, when the
        package is first imported."""
        assert logger_module._xdg_state_log_file().resolve().is_relative_to(_ROOT)

    def test_the_scratch_directory_is_not_inside_a_real_one(self):
        for real in (_real(".config"), _real(".local", "share"), _real(".local", "state")):
            assert not _ROOT.is_relative_to(real)


class TestConfiguration:
    def test_the_configuration_is_not_saved_to_the_real_file(self):
        from pytodo_qt.core.config import get_config_manager

        file = get_config_manager().config_file.resolve()
        assert file != (_real(".config") / "config.toml")
        assert not file.is_relative_to(_real(".config"))

    def test_choosing_a_view_of_the_calendar_saves_into_the_scratch_directory(self, qtbot):
        """The save that reached the real file."""
        from pytodo_qt.core.config import ConfigManager, get_config
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        saved_to: list[Path] = []
        save = ConfigManager.save

        def noting(manager, *args, **kwargs):
            saved_to.append(manager.config_file.resolve())
            return save(manager, *args, **kwargs)

        widget = CalendarViewWidget()
        qtbot.addWidget(widget)
        before = get_config().database.calendar_sub_view
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(ConfigManager, "save", noting)
            widget._set_sub_view(widget.SUB_MONTH)
        get_config().database.calendar_sub_view = before

        assert saved_to
        for file in saved_to:
            assert not file.is_relative_to(_real(".config"))


class TestKeyring:
    def test_the_keyring_stores_nothing(self):
        import keyring
        from keyring.backends import null

        assert isinstance(keyring.get_keyring(), null.Keyring)

    def test_the_variable_names_that_keyring(self):
        assert os.environ["PYTHON_KEYRING_BACKEND"] == "keyring.backends.null.Keyring"
