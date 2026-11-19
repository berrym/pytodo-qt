"""The size of the whole interface: a setting, read when the application starts.

Qt draws the application larger than its own measures say when the
environment variable ``QT_SCALE_FACTOR`` is set before the application
object is made: text, spacing, icons and fixed sizes alike, with the
layout of 100%. Larger fonts alone left controls lower than their text:
9 at 150% and 61 at 200% in the main views, where the factor leaves none.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QMainWindow

from pytodo_qt.core import interface_scale
from pytodo_qt.core.config import AppConfig, AppearanceConfig, ConfigManager
from pytodo_qt.gui.dialogs.settings import SettingsDialog

SOURCE_DIR = Path(__file__).resolve().parent.parent / "src" / "pytodo_qt"


@pytest.fixture(autouse=True)
def _module_state_is_put_back():
    """`apply` notes what decided the size of the run, and a restart
    that was asked for stays asked for."""
    before = (
        interface_scale._source,
        interface_scale._rounding_is_ours,
        interface_scale._overridden,
        interface_scale._restart_requested,
        interface_scale._restart_window,
    )
    yield
    (
        interface_scale._source,
        interface_scale._rounding_is_ours,
        interface_scale._overridden,
        interface_scale._restart_requested,
        interface_scale._restart_window,
    ) = before


class TestTheSizesOffered:
    def test_they_run_from_the_full_size_to_twice_it(self):
        assert interface_scale.SCALES == (100, 110, 125, 150, 175, 200)
        assert interface_scale.DEFAULT_SCALE == 100

    @pytest.mark.parametrize(
        ("stored", "taken"),
        [(100, 100), (125, 125), (200, 200), (120, 125), (112, 110), (90, 100), (400, 200)],
    )
    def test_a_stored_number_becomes_the_nearest_of_them(self, stored, taken):
        assert interface_scale.normalized(stored) == taken

    def test_a_number_between_two_becomes_the_smaller(self):
        assert interface_scale.normalized(105) == 100

    @pytest.mark.parametrize("stored", ["large", None, True, [125]])
    def test_what_is_no_number_becomes_the_full_size(self, stored):
        assert interface_scale.normalized(stored) == 100


class TestApply:
    def test_the_full_size_sets_nothing(self):
        environ: dict[str, str] = {}
        assert interface_scale.apply(100, environ) == interface_scale.FROM_NOTHING
        assert environ == {}

    @pytest.mark.parametrize(
        ("scale", "factor"), [(110, "1.1"), (125, "1.25"), (150, "1.5"), (175, "1.75"), (200, "2")]
    )
    def test_a_larger_size_sets_qts_factor(self, scale, factor):
        environ: dict[str, str] = {}
        assert interface_scale.apply(scale, environ) == interface_scale.FROM_SETTING
        assert environ["QT_SCALE_FACTOR"] == factor

    def test_the_factor_is_used_as_it_is(self):
        """Qt can round a factor such as 1.25 to a whole one."""
        environ: dict[str, str] = {}
        interface_scale.apply(125, environ)
        assert environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] == "PassThrough"

    def test_a_rounding_the_environment_asks_for_is_kept(self):
        environ = {"QT_SCALE_FACTOR_ROUNDING_POLICY": "Round"}
        interface_scale.apply(125, environ)
        assert environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] == "Round"

    def test_a_factor_in_the_environment_decides(self):
        """Who starts the application with the variable set has asked
        for that size."""
        environ = {"QT_SCALE_FACTOR": "1.3"}
        assert interface_scale.apply(200, environ) == interface_scale.FROM_ENVIRONMENT
        assert environ == {"QT_SCALE_FACTOR": "1.3"}

    def test_what_decided_is_remembered(self):
        interface_scale.apply(150, {})
        assert interface_scale.source() == interface_scale.FROM_SETTING
        interface_scale.apply(150, {"QT_SCALE_FACTOR": "2"})
        assert interface_scale.source() == interface_scale.FROM_ENVIRONMENT

    def test_a_number_that_is_not_offered_is_made_one(self):
        environ: dict[str, str] = {}
        interface_scale.apply(120, environ)
        assert environ["QT_SCALE_FACTOR"] == "1.25"

    def test_a_size_given_with_the_scale_option_is_noted(self):
        """Also at 100%, where nothing is set."""
        interface_scale.apply(100, {}, overridden=True)
        assert interface_scale.overridden()
        interface_scale.apply(150, {})
        assert not interface_scale.overridden()

    def test_startup_says_whether_the_scale_option_was_given(self):
        text = (SOURCE_DIR / "__main__.py").read_text(encoding="utf-8")
        assert "overridden=args.scale is not None" in text


class TestActiveFactor:
    @pytest.mark.parametrize(
        ("environ", "factor"),
        [({}, 1.0), ({"QT_SCALE_FACTOR": "1.5"}, 1.5), ({"QT_SCALE_FACTOR": ""}, 1.0)],
    )
    def test_it_is_read_from_the_environment(self, environ, factor):
        assert interface_scale.active_factor(environ) == factor

    @pytest.mark.parametrize("value", ["large", "0", "-1"])
    def test_a_value_qt_would_not_take_counts_as_the_full_size(self, value):
        assert interface_scale.active_factor({"QT_SCALE_FACTOR": value}) == 1.0


class TestFits:
    """The main window is 910 x 431 at least."""

    LEAST = (910, 431)

    @pytest.mark.parametrize(
        ("scale", "room"),
        [(100, True), (125, True), (150, True), (175, True), (200, False)],
    )
    def test_a_screen_of_1600_by_1000(self, scale, room):
        """At 175% it holds a window of 914 pixels; at 200% one of 800."""
        assert interface_scale.fits(scale, (1600, 1000), self.LEAST) is room

    def test_a_screen_of_1920_by_1080_has_room_for_twice_the_size(self):
        assert interface_scale.fits(200, (1920, 1080), self.LEAST)

    def test_the_height_counts_as_the_width_does(self):
        assert not interface_scale.fits(200, (4000, 800), self.LEAST)


class TestConfiguration:
    def test_the_full_size_is_the_default(self):
        assert AppearanceConfig().interface_scale == 100

    def test_the_size_is_saved_and_loaded(self, tmp_path):
        manager = ConfigManager(config_dir=tmp_path)
        manager.config.appearance.interface_scale = 150
        manager.save()
        assert "interface_scale = 150" in (tmp_path / "config.toml").read_text()

        again = ConfigManager(config_dir=tmp_path)
        again.load()
        assert again.config.appearance.interface_scale == 150

    def test_a_configuration_from_before_the_setting_has_the_full_size(self, tmp_path):
        (tmp_path / "config.toml").write_text('[appearance]\ntheme = "dark"\n')
        manager = ConfigManager(config_dir=tmp_path)
        manager.load()
        assert manager.config.appearance.interface_scale == 100
        assert manager.config.appearance.theme == "dark"

    def test_a_size_edited_by_hand_becomes_one_of_those_offered(self, tmp_path):
        (tmp_path / "config.toml").write_text("[appearance]\ninterface_scale = 133\n")
        manager = ConfigManager(config_dir=tmp_path)
        manager.load()
        assert manager.config.appearance.interface_scale == 125

    def test_the_default_configuration_has_it(self):
        assert AppConfig().appearance.interface_scale == 100


class TestStartup:
    """`__main__.main` is read, not run: it starts the application."""

    @staticmethod
    def _main() -> tuple[str, ast.FunctionDef]:
        text = (SOURCE_DIR / "__main__.py").read_text(encoding="utf-8")
        tree = ast.parse(text)
        main = next(
            node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        return text, main

    @staticmethod
    def _line_of_call(main: ast.FunctionDef, dotted: str) -> int:
        for node in ast.walk(main):
            if isinstance(node, ast.Call) and ast.unparse(node.func) == dotted:
                return node.lineno
        raise AssertionError(f"{dotted} is not called in main()")

    def test_the_size_is_applied_before_the_application_object_is_made(self):
        """Qt reads the factor when the object is made, and not again."""
        _text, main = self._main()
        applied = self._line_of_call(main, "interface_scale.apply")
        made = self._line_of_call(main, "QApplication")
        assert applied < made

    def test_the_command_line_has_a_scale_option(self):
        text, _main = self._main()
        assert '"--scale"' in text
        assert "choices=list(interface_scale.SCALES)" in text

    def test_the_option_stands_in_for_the_stored_size(self):
        """As the other options do: `--scale 100` is the way back from
        a size the screen has no room for."""
        text, _main = self._main()
        assert "config.appearance.interface_scale = args.scale" in text


class TestSettings:
    @pytest.fixture
    def window(self, qtbot):
        """A stand-in for the main window, with its least size."""
        main_window = QMainWindow()
        qtbot.addWidget(main_window)
        main_window.setMinimumSize(910, 431)
        return main_window

    @pytest.fixture
    def dialog(self, qtbot, window, monkeypatch):
        monkeypatch.setattr(
            SettingsDialog, "_screen_room_at_full_size", lambda self: (1600.0, 1000.0)
        )
        monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
        interface_scale._source = interface_scale.FROM_NOTHING
        settings_dialog = SettingsDialog(window)
        yield settings_dialog
        settings_dialog.deleteLater()

    def test_the_six_sizes_are_offered(self, dialog):
        combo = dialog.interface_scale_combo
        assert [combo.itemData(i) for i in range(combo.count())] == [100, 110, 125, 150, 175, 200]

    def test_the_stored_size_is_shown(self, dialog):
        dialog._show_interface_scale(150)
        assert dialog.interface_scale_combo.currentData() == 150

    def test_a_size_the_screen_has_no_room_for_is_marked(self, dialog):
        """On a screen of 1600 x 1000, twice the size leaves the window
        800 pixels of the 910 it needs."""
        dialog._show_interface_scale(100)
        combo = dialog.interface_scale_combo
        texts = {combo.itemData(i): combo.itemText(i) for i in range(combo.count())}
        assert texts[175] == "175%"
        assert texts[200] == "200% (needs a larger screen)"

    def test_a_marked_size_can_still_be_chosen(self, dialog):
        dialog._show_interface_scale(200)
        assert dialog.interface_scale_combo.currentData() == 200

    def test_nothing_is_marked_without_a_main_window(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            SettingsDialog, "_screen_room_at_full_size", lambda self: (800.0, 500.0)
        )
        settings_dialog = SettingsDialog()
        qtbot.addWidget(settings_dialog)
        combo = settings_dialog.interface_scale_combo
        assert [combo.itemText(i) for i in range(combo.count())] == [
            "100%",
            "110%",
            "125%",
            "150%",
            "175%",
            "200%",
        ]

    def test_the_note_says_that_another_size_restarts_the_application(self, dialog):
        dialog._show_interface_scale(100)
        assert "starts again" not in dialog.interface_scale_note.text()

        dialog.interface_scale_combo.setCurrentIndex(dialog.interface_scale_combo.findData(150))

        assert "PyTodo-Qt starts again to apply this size" in dialog.interface_scale_note.text()
        assert "Now at 100%" in dialog.interface_scale_note.text()

    def test_the_note_of_a_size_left_for_later_says_the_same(self, dialog, monkeypatch):
        """The stored size is 125 and the run is drawn at 100, as after
        "Later": accepting the dialog offers the restart again."""
        monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
        interface_scale._source = interface_scale.FROM_NOTHING
        interface_scale._overridden = False
        monkeypatch.setattr(dialog._config.appearance, "interface_scale", 125)

        dialog._show_interface_scale(125)

        assert dialog.interface_scale_note.text() == (
            "PyTodo-Qt starts again to apply this size. Now at 100%."
        )

    def test_the_note_of_a_size_the_scale_option_stood_in_for_promises_no_restart(
        self, dialog, monkeypatch
    ):
        """Started with `--scale 100` while 200 is stored: accepting the
        dialog as it is does not start the application again."""
        monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
        interface_scale._source = interface_scale.FROM_NOTHING
        interface_scale._overridden = True
        monkeypatch.setattr(dialog._config.appearance, "interface_scale", 200)

        dialog._show_interface_scale(200)

        assert dialog.interface_scale_note.text() == (
            "Applies the next time PyTodo-Qt starts. Now at 100%."
        )

        dialog.interface_scale_combo.setCurrentIndex(dialog.interface_scale_combo.findData(150))
        assert "PyTodo-Qt starts again to apply this size" in dialog.interface_scale_note.text()

    def test_the_note_names_the_size_the_run_is_drawn_at(self, dialog, monkeypatch):
        monkeypatch.setenv("QT_SCALE_FACTOR", "1.5")
        interface_scale._source = interface_scale.FROM_SETTING
        monkeypatch.setattr(dialog._config.appearance, "interface_scale", 100)
        dialog._show_interface_scale(125)
        assert "Now at 150%" in dialog.interface_scale_note.text()

    def test_the_note_says_when_the_environment_decides(self, dialog, monkeypatch):
        monkeypatch.setenv("QT_SCALE_FACTOR", "1.3")
        interface_scale._source = interface_scale.FROM_ENVIRONMENT
        dialog._show_interface_scale(150)
        assert "QT_SCALE_FACTOR" in dialog.interface_scale_note.text()
        assert "no effect" in dialog.interface_scale_note.text()

    def test_the_note_has_the_style_of_the_other_notes(self, dialog):
        assert dialog.interface_scale_note.styleSheet() == "color: palette(placeholder-text);"

    def test_the_room_of_the_screen_is_counted_at_the_full_size(self, qtbot, monkeypatch):
        """At 150% a screen reports two thirds of its pixels."""
        settings_dialog = SettingsDialog()
        qtbot.addWidget(settings_dialog)
        monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
        plain = settings_dialog._screen_room_at_full_size()
        monkeypatch.setenv("QT_SCALE_FACTOR", "1.5")
        scaled = settings_dialog._screen_room_at_full_size()
        assert plain is not None and scaled is not None
        assert scaled[0] == pytest.approx(plain[0] * 1.5)
        assert scaled[1] == pytest.approx(plain[1] * 1.5)

    def test_saving_stores_the_chosen_size(self, dialog, monkeypatch):
        from pytodo_qt.core.config import get_config

        # Nothing is written; the dialog takes a true value for "saved".
        monkeypatch.setattr(ConfigManager, "save", lambda self: True)
        before = get_config().appearance.interface_scale
        try:
            dialog.interface_scale_combo.setCurrentIndex(dialog.interface_scale_combo.findData(175))
            assert dialog._save_settings()
            assert dialog._config_manager.config.appearance.interface_scale == 175
        finally:
            dialog._config_manager.config.appearance.interface_scale = before


class TestSettingsAsksForARestart:
    """Qt takes a size only when the application starts. A saved size
    that is not the one the run is drawn at is announced, and the main
    window starts the application again."""

    @pytest.fixture
    def dialog(self, qtbot, monkeypatch):
        monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
        monkeypatch.setattr(ConfigManager, "save", lambda self: True)
        interface_scale._source = interface_scale.FROM_NOTHING
        interface_scale._overridden = False
        settings_dialog = SettingsDialog()
        qtbot.addWidget(settings_dialog)
        settings_dialog._config_manager.config.appearance.interface_scale = 100
        settings_dialog._show_interface_scale(100)
        announced: list[int] = []
        settings_dialog.interface_scale_changed.connect(announced.append)
        settings_dialog.announced = announced
        yield settings_dialog
        settings_dialog._config_manager.config.appearance.interface_scale = 100

    @staticmethod
    def _choose(dialog, scale: int) -> None:
        dialog.interface_scale_combo.setCurrentIndex(dialog.interface_scale_combo.findData(scale))

    def test_a_new_size_is_announced_when_it_is_saved(self, dialog):
        self._choose(dialog, 150)
        assert dialog._save_settings()
        assert dialog.announced == [150]

    def test_nothing_is_announced_before_the_save(self, dialog):
        self._choose(dialog, 150)
        assert dialog.announced == []

    def test_a_save_that_leaves_the_size_alone_announces_nothing(self, dialog):
        assert dialog._save_settings()
        assert dialog.announced == []

    def test_a_size_left_for_later_is_announced_again_at_the_next_save(self, dialog):
        """The stored size is 150 and the run is drawn at 100, as after
        "Later": the next save offers the restart again."""
        dialog._config_manager.config.appearance.interface_scale = 150
        dialog._show_interface_scale(150)
        assert dialog._save_settings()
        assert dialog.announced == [150]

    def test_it_is_announced_at_every_save_until_the_run_is_drawn_at_it(self, dialog):
        """As with Apply answered "Later" twice: the dialog stays open."""
        self._choose(dialog, 150)
        assert dialog._save_settings()
        assert dialog._save_settings()
        assert dialog.announced == [150, 150]
        assert "starts again" in dialog.interface_scale_note.text()

    def test_a_size_the_scale_option_stood_in_for_is_not_announced(self, dialog):
        """Started with `--scale 100` because 200 is stored and does not
        fit: a save that leaves the size alone does not go back to 200."""
        interface_scale._overridden = True
        dialog._config_manager.config.appearance.interface_scale = 200
        dialog._show_interface_scale(200)
        assert dialog._save_settings()
        assert dialog.announced == []

    def test_a_size_chosen_in_a_run_with_the_scale_option_is_announced(self, dialog):
        interface_scale._overridden = True
        dialog._config_manager.config.appearance.interface_scale = 200
        dialog._show_interface_scale(200)
        self._choose(dialog, 125)
        assert dialog._save_settings()
        assert dialog.announced == [125]

    def test_going_back_to_the_size_the_run_is_drawn_at_needs_no_restart(self, dialog):
        """As after a start with `--scale 100`: the stored size is 150,
        the run is at 100, and 100 is chosen."""
        dialog._config_manager.config.appearance.interface_scale = 150
        dialog._show_interface_scale(150)
        self._choose(dialog, 100)
        assert dialog._save_settings()
        assert dialog.announced == []
        assert dialog._config_manager.config.appearance.interface_scale == 100

    def test_nothing_is_announced_while_the_environment_decides(self, dialog, monkeypatch):
        monkeypatch.setenv("QT_SCALE_FACTOR", "1.3")
        interface_scale._source = interface_scale.FROM_ENVIRONMENT
        self._choose(dialog, 150)
        assert dialog._save_settings()
        assert dialog.announced == []


class TestTheWindowOverARestart:
    def test_it_is_handed_on_in_the_screens_own_pixels(self):
        """At 150% a window of 1000 covers 1500 of the screen's pixels."""
        assert interface_scale.encode_window(100, 50, 1000, 600, False, 1.5) == "150,75,1500,900,0"

    def test_the_new_run_counts_in_its_own(self):
        """The same 1500 pixels are 750 of a run at 200%."""
        assert interface_scale.decode_window("150,75,1500,900,0", 2.0) == (75, 38, 750, 450, False)

    def test_at_the_same_size_it_comes_back_as_it_was(self):
        text = interface_scale.encode_window(40, 60, 1100, 700, True, 1.25)
        assert interface_scale.decode_window(text, 1.25) == (40, 60, 1100, 700, True)

    @pytest.mark.parametrize("text", ["", "1,2,3", "a,b,c,d,e", "0,0,0,600,0", "0,0,800,-1,0"])
    def test_what_cannot_be_read_is_no_window(self, text):
        assert interface_scale.decode_window(text, 1.0) is None

    def test_it_is_taken_from_the_environment_once(self):
        environ = {"PYTODO_QT_RESTORE_WINDOW": "10,20,1000,700,0", "QT_SCALE_FACTOR": "2"}
        assert interface_scale.window_to_restore(environ) == (5, 10, 500, 350, False)
        assert "PYTODO_QT_RESTORE_WINDOW" not in environ
        assert interface_scale.window_to_restore(environ) is None


class TestTheCommandThatStartsAgain:
    def test_a_packaged_application_is_its_own_executable(self):
        command = interface_scale.relaunch_command(
            ["--theme", "dark"], executable="/Applications/PyTodo-Qt", frozen=True
        )
        assert command == ["/Applications/PyTodo-Qt", "--theme", "dark"]

    def test_from_source_it_is_the_interpreter_running_the_package(self):
        command = interface_scale.relaunch_command(
            ["--theme", "dark"], executable="/usr/bin/python3", frozen=False
        )
        assert command == ["/usr/bin/python3", "-m", "pytodo_qt", "--theme", "dark"]

    @pytest.mark.parametrize(
        "arguments",
        [["--scale", "150", "--web", "yes"], ["--scale=150", "--web", "yes"]],
    )
    def test_the_scale_option_is_left_out(self, arguments):
        """It stood in for the stored size; the new size is the stored one."""
        command = interface_scale.relaunch_command(arguments, executable="py", frozen=True)
        assert command == ["py", "--web", "yes"]


class TestTheEnvironmentOfTheNewProcess:
    def test_a_factor_this_run_set_is_taken_out(self):
        """Left in, it would count as the environment's and decide."""
        environ: dict[str, str] = {"PATH": "/bin"}
        interface_scale.apply(150, environ)
        assert environ["QT_SCALE_FACTOR"] == "1.5"

        new = interface_scale.relaunch_environment(environ)

        assert new == {"PATH": "/bin"}

    def test_a_factor_the_environment_had_is_kept(self):
        environ = {"QT_SCALE_FACTOR": "1.3", "QT_SCALE_FACTOR_ROUNDING_POLICY": "Round"}
        interface_scale.apply(150, environ)
        assert interface_scale.relaunch_environment(environ) == environ

    def test_a_rounding_the_environment_asked_for_is_kept(self):
        environ = {"QT_SCALE_FACTOR_ROUNDING_POLICY": "Round"}
        interface_scale.apply(150, environ)
        new = interface_scale.relaunch_environment(environ)
        assert new == {"QT_SCALE_FACTOR_ROUNDING_POLICY": "Round"}

    def test_the_window_is_handed_on(self):
        new = interface_scale.relaunch_environment({}, window="1,2,3,4,0")
        assert new == {"PYTODO_QT_RESTORE_WINDOW": "1,2,3,4,0"}

    def test_a_window_handed_to_this_run_is_not_handed_on_again(self):
        new = interface_scale.relaunch_environment({"PYTODO_QT_RESTORE_WINDOW": "9,9,9,9,0"})
        assert new == {}

    def test_the_environment_it_was_made_from_is_left_as_it_is(self):
        environ: dict[str, str] = {}
        interface_scale.apply(150, environ)
        before = dict(environ)
        interface_scale.relaunch_environment(environ)
        assert environ == before


class TestRelaunch:
    @pytest.fixture
    def started(self, monkeypatch) -> list[tuple[list[str], dict]]:
        calls: list[tuple[list[str], dict]] = []
        monkeypatch.setattr(
            interface_scale.subprocess,
            "Popen",
            lambda command, **options: calls.append((command, options)),
        )
        return calls

    def test_nothing_is_started_unless_it_was_asked_for(self, started):
        interface_scale._restart_requested = False
        assert interface_scale.relaunch(["--web", "yes"]) is False
        assert started == []

    def test_the_application_is_started_again(self, started, monkeypatch):
        monkeypatch.setattr(interface_scale.sys, "executable", "/usr/bin/python3")
        monkeypatch.delattr(interface_scale.sys, "frozen", raising=False)
        interface_scale.request_restart("1,2,1000,700,0")

        assert interface_scale.relaunch(["--scale", "150", "--web", "yes"]) is True

        ((command, options),) = started
        assert command == ["/usr/bin/python3", "-m", "pytodo_qt", "--web", "yes"]
        assert options["env"]["PYTODO_QT_RESTORE_WINDOW"] == "1,2,1000,700,0"
        assert options["start_new_session"] is True

    def test_a_start_that_fails_is_reported_and_not_raised(self, monkeypatch):
        def fail(*_args, **_options):
            raise OSError("no such file")

        monkeypatch.setattr(interface_scale.subprocess, "Popen", fail)
        interface_scale.request_restart()
        assert interface_scale.relaunch([]) is False


class TestStartupAndShutdownOrder:
    """`__main__.main` is read, not run."""

    @staticmethod
    def _lines() -> dict[str, int]:
        text = (SOURCE_DIR / "__main__.py").read_text(encoding="utf-8")
        main = next(
            node
            for node in ast.parse(text).body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        lines: dict[str, int] = {}
        for node in ast.walk(main):
            if isinstance(node, ast.Call):
                lines.setdefault(ast.unparse(node.func), node.lineno)
        return lines

    def test_the_application_starts_again_after_it_has_shut_down(self):
        """The new process needs the instance lock, which is free once
        the event loop has ended."""
        lines = self._lines()
        assert lines["loop.run_forever"] < lines["interface_scale.relaunch"]
        assert lines["_dispose_before_exit"] < lines["interface_scale.relaunch"]

    def test_the_window_is_put_back_once_it_exists(self):
        lines = self._lines()
        assert lines["MainWindow"] < lines["interface_scale.window_to_restore"]
        assert lines["interface_scale.window_to_restore"] < lines["loop.run_forever"]


class TestMainWindowStartsAgain:
    """Methods are run unbound against a mock window, as in
    ``test_minute_tick.py``."""

    @staticmethod
    def _window(*, timer="IDLE", stopwatch="IDLE"):
        from unittest.mock import MagicMock

        from pytodo_qt.gui.widgets.pomodoro import TimerState
        from pytodo_qt.gui.widgets.stopwatch import StopwatchState

        window = MagicMock()
        window._pomodoro.state = TimerState[timer]
        window._stopwatch.state = StopwatchState[stopwatch]
        window._restart_pending = False
        return window

    @pytest.mark.parametrize(
        ("timer", "stopwatch", "under_way"),
        [
            ("IDLE", "IDLE", False),
            ("WORKING", "IDLE", True),
            ("BREAK", "IDLE", True),
            ("PAUSED", "IDLE", True),
            ("IDLE", "RUNNING", True),
            ("IDLE", "PAUSED", True),
        ],
    )
    def test_a_session_at_work_on_a_break_or_paused_is_under_way(self, timer, stopwatch, under_way):
        """None of them is kept over a restart."""
        from pytodo_qt.gui.main_window import MainWindow

        window = self._window(timer=timer, stopwatch=stopwatch)
        assert MainWindow._session_under_way(window) is under_way

    def test_with_nothing_under_way_it_starts_again_without_asking(self, monkeypatch):
        from unittest.mock import MagicMock

        from pytodo_qt.gui import main_window as module
        from pytodo_qt.gui.main_window import MainWindow

        asked = MagicMock()
        monkeypatch.setattr(module, "QMessageBox", asked)
        window = self._window()
        window._session_under_way.return_value = False
        dialog = MagicMock()

        MainWindow._on_interface_scale_changed(window, dialog)

        asked.assert_not_called()
        assert window._restart_pending is True
        dialog.accept.assert_called_once_with()

    @pytest.mark.parametrize(("answer", "restarts"), [("restart", True), ("later", False)])
    def test_with_a_session_under_way_it_asks_first(self, monkeypatch, answer, restarts):
        from unittest.mock import MagicMock

        from pytodo_qt.gui import main_window as module
        from pytodo_qt.gui.main_window import MainWindow

        buttons = {"restart": object(), "later": object()}
        box = MagicMock()
        box.addButton.side_effect = [buttons["restart"], buttons["later"]]
        box.clickedButton.return_value = buttons[answer]
        message_box = MagicMock(return_value=box)
        monkeypatch.setattr(module, "QMessageBox", message_box)
        window = self._window(timer="WORKING")
        window._session_under_way.return_value = True
        dialog = MagicMock()

        MainWindow._on_interface_scale_changed(window, dialog)

        box.exec.assert_called_once_with()
        box.setDefaultButton.assert_called_once_with(buttons["later"])
        assert window._restart_pending is restarts
        assert dialog.accept.called is restarts

    def test_starting_again_quits_in_the_ordinary_way(self, monkeypatch):
        from PyQt6.QtCore import QRect

        from pytodo_qt.gui.main_window import MainWindow

        monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
        window = self._window()
        window._restart_pending = True
        window.isMaximized.return_value = False
        window.geometry.return_value = QRect(40, 60, 1100, 700)

        MainWindow._restart_application(window)

        assert interface_scale.restart_requested()
        assert interface_scale._restart_window == "40,60,1100,700,0"
        assert window._restart_pending is False
        window._quit_application.assert_called_once_with()

    def test_a_maximized_window_hands_on_the_size_it_goes_back_to(self, monkeypatch):
        from PyQt6.QtCore import QRect

        from pytodo_qt.gui.main_window import MainWindow

        monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
        window = self._window()
        window.isMaximized.return_value = True
        window.normalGeometry.return_value = QRect(10, 20, 1000, 650)

        MainWindow._restart_application(window)

        assert interface_scale._restart_window == "10,20,1000,650,1"

    def test_the_settings_dialog_closing_is_what_starts_it(self, monkeypatch):
        """The restart follows the dialog's own event loop."""
        from unittest.mock import MagicMock

        from pytodo_qt.gui import main_window as module
        from pytodo_qt.gui.main_window import MainWindow

        later: list[object] = []
        timer = MagicMock()
        timer.singleShot.side_effect = lambda _ms, call: later.append(call)
        monkeypatch.setattr(module, "QTimer", timer)
        dialog = MagicMock()
        monkeypatch.setattr(module, "SettingsDialog", MagicMock(return_value=dialog))
        window = self._window()
        window._restart_pending = True

        MainWindow._on_settings(window)

        assert later == [window._restart_application]
        window._refresh_ui.assert_not_called()

    def test_the_window_comes_back_where_it_was(self, qtbot):
        from pytodo_qt.gui.main_window import MainWindow

        window = QMainWindow()
        qtbot.addWidget(window)
        window.setMinimumSize(300, 200)
        room = window.screen().availableGeometry()
        x, y = room.left() + 20, room.top() + 20

        MainWindow.restore_after_restart(window, (x, y, 400, 300, False))

        assert window.isVisible()
        assert (window.width(), window.height()) == (400, 300)

    def test_it_is_never_smaller_than_the_window_can_be(self, qtbot):
        from pytodo_qt.gui.main_window import MainWindow

        window = QMainWindow()
        qtbot.addWidget(window)
        window.setMinimumSize(300, 200)
        room = window.screen().availableGeometry()

        MainWindow.restore_after_restart(window, (room.left(), room.top(), 100, 80, False))

        assert window.width() >= 300
        assert window.height() >= 200

    def test_it_stays_on_the_screen(self, qtbot):
        from pytodo_qt.gui.main_window import MainWindow

        window = QMainWindow()
        qtbot.addWidget(window)
        window.setMinimumSize(300, 200)
        room = window.screen().availableGeometry()

        MainWindow.restore_after_restart(
            window, (room.right() + 5000, room.bottom() + 5000, 400, 300, False)
        )

        assert room.contains(window.geometry())
