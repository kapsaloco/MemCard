"""Exercise actual Qt workers and UI actions with disposable card folders."""

import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from memcard import ui
from memcard.manifest import verify_snapshot
from memcard.settings import load_settings, save_settings
from memcard.snapshots import Cancelled, backup_pcsx2, backup_rpcs3


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    return instance


def wait_idle(window, timeout=30):
    deadline = time.monotonic() + timeout
    while window.job is not None and time.monotonic() < deadline:
        QTest.qWait(10)
    assert window.job is None, "UI worker did not finish"


def set_theme(window, theme):
    if window.theme != theme:
        window.theme_button.click()


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "find_pcsx2_memcards", lambda: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *_: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
    win = ui.MainWindow(tmp_path / "preferences" / "settings.json")
    win.show()
    win.choose_emulator("pcsx2")
    wait_idle(win)
    win.start_backup()
    wait_idle(win)
    yield win
    wait_idle(win)
    win.close()
    app.processEvents()


def prepare_folders(window, tmp_path):
    source, library = tmp_path / "cards", tmp_path / "library"
    source.mkdir()
    library.mkdir()
    (source / "card.ps2").write_bytes(b"test card bytes")
    (source / "folder" / "empty").mkdir(parents=True)
    window.source.setText(str(source))
    window.library.setText(str(library))
    return source, library


def select_restore_destination(window, parent, name):
    window.start_restore()
    wait_idle(window)
    window.restore_next_button.click()
    assert window.flow == "restore_target"
    window.restore_parent.setText(str(parent))
    window.restore_name.setText(name)


def test_ui_backup_verify_restore(window, tmp_path, monkeypatch):
    source, library = prepare_folders(window, tmp_path)
    window.closed.setChecked(True)
    window.backup_button.click()
    wait_idle(window)
    assert window.table.rowCount() == 1
    snapshot = window.rows[0]["path"]
    verify_snapshot(snapshot)
    assert window.open_backup_button.isVisible()
    assert window.backup_menu_button.isVisible()
    assert not window.action_strip.isVisible()
    opened = []
    monkeypatch.setattr(ui.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    window.open_backup_button.click()
    assert Path(opened[-1]) == snapshot
    assert window.restore_button.isEnabled()
    assert window.table.item(0, 3).text().startswith("VERIFIED")
    select_restore_destination(window, tmp_path, "Restored")
    window.restore_button.click()
    wait_idle(window)
    target = tmp_path / "Restored"
    assert (target / "card.ps2").read_bytes() == (source / "card.ps2").read_bytes()
    assert (target / "folder" / "empty").is_dir()
    assert window.open_restore_button.isVisible()
    assert window.restore_menu_button.isVisible()
    assert not window.action_strip.isVisible()
    window.open_restore_button.click()
    assert Path(opened[-1]) == target
    log = window.console.toPlainText()
    assert "CLI >" in log and "restore-pcsx2" in log and "SUCCESS / Restored" in log
    assert load_settings(window.preferences)["library"] == str(library)


def test_ui_restore_automatically_rejects_corruption(window, tmp_path, monkeypatch):
    source, library = prepare_folders(window, tmp_path)
    snapshot = backup_pcsx2(source, library, emulator_closed=True)
    (snapshot / "payload" / "card.ps2").write_bytes(b"bad")
    window.refresh()
    wait_idle(window)
    select_restore_destination(window, tmp_path, "Must not be restored")
    window.restore_button.click()
    wait_idle(window)
    assert not (tmp_path / "Must not be restored").exists()
    assert window.status.text().startswith("FAILED")
    assert "Traceback" in window.console.toPlainText()


def test_ui_invalid_and_staging_history(window, tmp_path):
    _, library = prepare_folders(window, tmp_path)
    snapshots = library / "snapshots"
    snapshots.mkdir()
    (snapshots / "broken").mkdir()
    (snapshots / ".staging-interrupted").mkdir()
    window.refresh()
    wait_idle(window)
    assert window.table.rowCount() == 1
    assert window.table.item(0, 3).text() == "INVALID"
    assert not window.restore_button.isEnabled()


def test_unavailable_library(window, tmp_path):
    window.library.setText(str(tmp_path / "unplugged"))
    window.refresh()
    wait_idle(window)
    assert window.library_status.text().startswith("UNAVAILABLE")
    assert window.table.rowCount() == 0


def test_busy_cancellation_and_responsiveness(window):
    from PySide6.QtCore import QTimer
    ticks = []
    def operation(job):
        job.cancelled.wait(3)
        if job.cancelled.is_set():
            raise Cancelled("Test cancellation")
    window.start_job("Test running job", operation, lambda _: None, True)
    assert not window.backup_button.isEnabled()
    assert not window.ps2_button.isEnabled()
    assert not window.ps3_button.isEnabled()
    assert not window.back_button.isEnabled()
    assert not window.home_button.isEnabled()
    assert window.cancel_button.isEnabled()
    QTimer.singleShot(0, lambda: ticks.append(True))
    QTest.qWait(25)
    assert ticks
    window.cancel_button.click()
    wait_idle(window)
    assert "CANCELLED" in window.status.text()
    assert window.backup_button.isEnabled()


def test_changing_source_requires_confirmation_again(window):
    window.closed.setChecked(True)
    window.source.setText("different folder")
    assert not window.closed.isChecked()


def test_preferences_round_trip_and_failed_write_preserves_old(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    save_settings(path, {"source": "first", "library": "library"})
    def fail(*_):
        raise OSError("Simulated replace failure")
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        save_settings(path, {"source": "second"})
    assert load_settings(path)["source"] == "first"
    assert not list(tmp_path.glob("*.tmp"))


def test_close_waits_for_worker(window):
    def operation(job):
        job.cancelled.wait(3)
        if job.cancelled.is_set():
            raise Cancelled("Closing")
    window.start_job("Job running", operation, lambda _: None, True)
    window.close()
    assert window.close_when_done
    wait_idle(window)
    assert not window.isVisible()


def test_ps3_ui_backup_restore_and_mode_filter(window, tmp_path, monkeypatch):
    ps2_source, library = prepare_folders(window, tmp_path)
    backup_pcsx2(ps2_source, library, emulator_closed=True)
    ps3_source = tmp_path / "RPCS3" / "dev_hdd0" / "home" / "00000002" / "savedata"
    game = ps3_source / "TEST-SAVE"
    game.mkdir(parents=True)
    (game / "PARAM.SFO").write_bytes(b"metadata")
    (game / "SAVE.DAT").write_bytes(b"ps3 save")
    window.ps3_button.click()
    wait_idle(window)
    assert window.mode == "rpcs3"
    assert window.source.text() == ""
    assert window.table.rowCount() == 0
    window.source.setText(str(ps3_source))
    window.closed.setChecked(True)
    window.backup_button.click()
    wait_idle(window)
    assert window.table.rowCount() == 1
    assert window.rows[0]["data"]["preset"]["kind"] == "rpcs3_savedata"
    assert window.rows[0]["data"]["preset"]["label"] == "RPCS3 user 00000002"
    assert window.table.item(0, 3).text().startswith("VERIFIED")
    select_restore_destination(window, tmp_path, "PS3 restored")
    window.restore_button.click()
    wait_idle(window)
    assert (tmp_path / "PS3 restored" / "TEST-SAVE" / "SAVE.DAT").read_bytes() == b"ps3 save"
    assert "restore-rpcs3" in window.console.toPlainText()
    window.ps2_button.click()
    wait_idle(window)
    assert window.source.text() == str(ps2_source)
    assert window.table.rowCount() == 1
    assert window.rows[0]["data"]["preset"]["kind"] == "pcsx2_memory_cards"
    window.ps3_button.click()
    wait_idle(window)
    assert window.source.text() == str(ps3_source)
    assert not window.closed.isChecked()
    preferences = load_settings(window.preferences)
    assert preferences["pcsx2_source"] == str(ps2_source)
    assert preferences["rpcs3_source"] == str(ps3_source)
    assert preferences["mode"] == "rpcs3"


def test_ps3_restore_automatically_rejects_corruption(window, tmp_path, monkeypatch):
    source, library = prepare_folders(window, tmp_path)
    snapshot = backup_rpcs3(source, library, emulator_closed=True)
    (snapshot / "payload" / "card.ps2").write_bytes(b"corruption")
    window.ps3_button.click()
    wait_idle(window)
    select_restore_destination(window, tmp_path, "Must not be restored")
    window.restore_button.click()
    wait_idle(window)
    assert not (tmp_path / "Must not be restored").exists()
    assert window.status.text().startswith("FAILED")


def test_legacy_preferences_migrate_and_reopen_ps3(app, tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "find_pcsx2_memcards", lambda: None)
    path = tmp_path / "settings.json"
    save_settings(path, {"source": "legacy ps2 folder"})
    win = ui.MainWindow(path)
    assert win.mode == "pcsx2"
    assert win.source.text() == "legacy ps2 folder"
    win.ps3_button.click()
    win.source.setText("ps3 folder")
    win.close()
    reopened = ui.MainWindow(path)
    assert reopened.mode == "rpcs3"
    assert reopened.source.text() == "ps3 folder"
    assert reopened.sources["pcsx2"] == "legacy ps2 folder"
    reopened.close()


def test_locate_rpc3_and_choose_between_users(window, tmp_path, monkeypatch):
    monkeypatch.delenv("RPCS3_CONFIG_DIR", raising=False)
    root = tmp_path / "emulator"
    root.mkdir()
    executable = root / "rpcs3.exe"
    executable.write_bytes(b"never executed")
    paths = []
    for name in ("00000001", "00000002"):
        path = root / "dev_hdd0" / "home" / name / "savedata"
        path.mkdir(parents=True)
        paths.append(path)
    window.ps3_button.click()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_: (str(executable), ""))
    window.locate_rpcs3_button.click()
    wait_idle(window)
    assert window.rpcs3_candidates == paths
    assert window.source.text() == ""
    assert window.rpcs3_users.currentIndex() == 0
    window.rpcs3_users.setCurrentIndex(2)
    assert window.source.text() == str(paths[1])
    assert not window.closed.isChecked()
    preferences = load_settings(window.preferences)
    assert preferences["rpcs3_executable"] == str(executable)
    assert preferences["rpcs3_source"] == str(paths[1])
    window.find_rpcs3_users()
    wait_idle(window)
    assert window.source.text() == str(paths[1])


def test_single_user_proposed_and_manual_source_still_possible(window, tmp_path, monkeypatch):
    monkeypatch.delenv("RPCS3_CONFIG_DIR", raising=False)
    root = tmp_path / "emulator"
    savedata = root / "dev_hdd0" / "home" / "00000007" / "savedata"
    savedata.mkdir(parents=True)
    executable = root / "rpcs3.exe"
    executable.write_bytes(b"test")
    window.ps3_button.click()
    window.rpcs3_exe.setText(str(executable))
    window.find_rpcs3_users()
    wait_idle(window)
    assert window.source.text() == str(savedata)
    assert window.rpcs3_users.currentIndex() == 1
    window.source.setText(str(tmp_path / "custom savedata"))
    assert window.rpcs3_users.currentIndex() == 0
    assert window.source.text() == str(tmp_path / "custom savedata")


def test_failed_discovery_does_not_leave_old_save_source(window, tmp_path):
    window.ps3_button.click()
    window.source.setText("old savedata")
    window.rpcs3_exe.setText(str(tmp_path / "missing.exe"))
    window.find_rpcs3_users()
    wait_idle(window)
    assert window.source.text() == ""
    assert not window.closed.isChecked()
    assert "browse" in window.source_hint.text().lower()
    assert window.source_button.isEnabled()


def test_light_dark_selection_persists_and_keeps_current_mode(window, app):
    assert window.theme == "light"
    window.ps3_button.click()
    set_theme(window, "dark")
    assert window.theme == "dark"
    assert window.mode == "rpcs3"
    assert window.banner.theme == "dark"
    assert load_settings(window.preferences)["theme"] == "dark"
    reopened = ui.MainWindow(window.preferences)
    assert reopened.theme == "dark"
    assert "light" in reopened.theme_button.toolTip()
    reopened.close()
    set_theme(window, "light")
    assert window.theme == "light"


def test_rpc3_controls_locked_during_job(window):
    window.ps3_button.click()
    def operation(job):
        job.cancelled.wait(3)
        raise Cancelled("Test")
    window.start_job("Running", operation, lambda _: None, True)
    assert not window.locate_rpcs3_button.isEnabled()
    assert not window.rpcs3_users.isEnabled()
    # Appearance can change without touching an active filesystem job.
    set_theme(window, "dark")
    assert window.theme == "dark"
    window.cancel_button.click()
    wait_idle(window)


def test_aero_confirmation_checkbox_mouse_and_keyboard(window):
    from PySide6.QtCore import QPoint, Qt
    assert not window.closed.isChecked()
    QTest.mouseClick(window.closed, Qt.MouseButton.LeftButton, pos=QPoint(9, window.closed.height() // 2))
    assert window.closed.isChecked()
    window.closed.setFocus()
    QTest.keyClick(window.closed, Qt.Key.Key_Space)
    assert not window.closed.isChecked()


def test_reopen_rediscovery_preserves_user_selection(app, tmp_path, monkeypatch):
    monkeypatch.delenv("RPCS3_CONFIG_DIR", raising=False)
    root = tmp_path / "emulator"
    savedata = root / "dev_hdd0" / "home" / "00000002" / "savedata"
    savedata.mkdir(parents=True)
    (root / "dev_hdd0" / "home" / "00000001" / "savedata").mkdir(parents=True)
    executable = root / "rpcs3.exe"
    executable.write_bytes(b"never executed")
    path = tmp_path / "settings.json"
    save_settings(path, {"mode": "rpcs3", "rpcs3_source": str(savedata), "rpcs3_executable": str(executable), "theme": "dark"})
    win = ui.MainWindow(path)
    win.show()
    win.choose_emulator("rpcs3")
    wait_idle(win)
    win.start_backup()
    QTest.qWait(25)
    wait_idle(win)
    assert win.source.text() == str(savedata)
    assert win.rpcs3_users.currentData() == str(savedata)
    assert win.theme == "dark"
    win.close()


def test_debug_and_progress_stay_visible_in_small_window(window, app):
    from PySide6.QtCore import QPoint
    window.log_toggle.click()
    window.resize(860, 680)
    app.processEvents()
    for control in (window.console, window.status):
        position = control.mapTo(window, QPoint(0, 0))
        assert position.y() >= 0
        assert position.y() + control.height() <= window.height()


@pytest.mark.parametrize("mode", ["pcsx2", "rpcs3"])
def test_missing_closed_confirmation_is_highlighted(window, tmp_path, mode):
    source, library = prepare_folders(window, tmp_path)
    if mode == "rpcs3":
        window.ps3_button.click()
        wait_idle(window)
        window.start_backup()
        wait_idle(window)
        window.source.setText(str(source))
    window.backup_button.click()
    assert window.closed.property("needsConfirmation") is True
    assert not window.confirmation_hint.isHidden()
    assert ui.MODES[mode]["emulator"] in window.confirmation_hint.text()
    assert window.job is None
    assert not list(library.iterdir())
    window.closed.setChecked(True)
    assert window.closed.property("needsConfirmation") is False
    assert window.confirmation_hint.isHidden()


def test_debug_collapse_remembers_state_and_retains_log(window, app):
    assert window.console.isHidden()
    assert not window.log_toggle.isChecked()
    window.log("A hidden log entry")
    window.log_toggle.click()
    assert not window.console.isHidden()
    assert "A hidden log entry" in window.console.toPlainText()
    assert load_settings(window.preferences)["debug_expanded"] is True
    reopened = ui.MainWindow(window.preferences)
    assert reopened.log_toggle.isChecked()
    assert not reopened.console.isHidden()
    reopened.close()
    window.log_toggle.click()
    assert window.console.isHidden()
    assert load_settings(window.preferences)["debug_expanded"] is False


def test_manual_verify_not_exposed_in_interface(window):
    from PySide6.QtWidgets import QPushButton
    assert all(button.text() != "Verify" for button in window.findChildren(QPushButton))


def test_guided_home_and_returning_backup(window, tmp_path):
    source, library = prepare_folders(window, tmp_path)
    window.show_page("home")
    assert window.ps2_button.isVisible()
    assert window.ps3_button.isVisible()
    assert not window.source.isVisible()
    assert not window.table.isVisible()
    window.ps2_button.click()
    wait_idle(window)
    assert window.flow == "overview"
    assert window.start_backup_button.isVisible()
    assert window.start_restore_button.isVisible()
    window.start_backup_button.click()
    wait_idle(window)
    assert window.flow == "backup"
    assert not window.setup_panel.isVisible()
    assert window.closed.isVisible()
    assert window.backup_button.isVisible()
    assert not window.table.isVisible()
    window.folder_toggle.click()
    assert window.source.isVisible()
    assert window.library.text() == str(library)
    window.folder_toggle.click()
    window.closed.setChecked(True)
    window.backup_button.click()
    wait_idle(window)
    assert "Backup complete" in window.backup_result.text()
    assert window.flow == "backup"
    window.back_button.click()
    assert window.flow == "overview"
    assert "Last backup" in window.last_backup.text()


def test_guided_restore_without_emulator_installation(window, tmp_path, app):
    source, library = prepare_folders(window, tmp_path)
    snapshot = backup_rpcs3(source, library, emulator_closed=True)
    preferences = tmp_path / "fresh" / "settings.json"
    save_settings(preferences, {"library": str(library)})
    fresh = ui.MainWindow(preferences)
    fresh.show()
    assert fresh.flow == "home"
    assert fresh.job is None
    fresh.ps3_button.click()
    wait_idle(fresh)
    assert fresh.flow == "overview"
    fresh.start_restore_button.click()
    wait_idle(fresh)
    assert fresh.flow == "restore_list"
    assert fresh.table.isVisible()
    assert not fresh.source.isVisible()
    assert fresh.rpcs3_exe.text() == ""
    fresh.restore_next_button.click()
    assert fresh.flow == "restore_target"
    assert fresh.restore_name.text() == "RPCS3-Restored"
    assert not fresh.table.isVisible()
    assert fresh.restore_parent.isVisible()
    fresh.restore_parent.setText(str(tmp_path))
    fresh.restore_name.setText("Fresh recovery")
    assert not (tmp_path / "Fresh recovery").exists()
    fresh.restore_button.click()
    wait_idle(fresh)
    assert (tmp_path / "Fresh recovery" / "card.ps2").read_bytes() == (source / "card.ps2").read_bytes()
    assert "Recovery complete" in fresh.restore_result.text()
    verify_snapshot(snapshot)
    fresh.close()


def test_guided_missing_folders_and_back_navigation(window):
    window.show_page("home")
    window.ps2_button.click()
    wait_idle(window)
    window.start_backup_button.click()
    assert window.setup_panel.isVisible()
    window.back_button.click()
    assert window.flow == "overview"
    window.start_restore_button.click()
    wait_idle(window)
    assert window.flow == "restore_list"
    assert not window.restore_next_button.isEnabled()
    window.home_button.click()
    assert window.flow == "home"


def test_restore_existing_target_is_preserved_in_guided_flow(window, tmp_path):
    source, library = prepare_folders(window, tmp_path)
    backup_pcsx2(source, library, emulator_closed=True)
    select_restore_destination(window, tmp_path, "Existing")
    target = tmp_path / "Existing"
    target.mkdir()
    (target / "keep").write_bytes(b"keep")
    window.restore_button.click()
    assert window.job is None
    assert (target / "keep").read_bytes() == b"keep"


def test_guided_primary_actions_stay_visible_on_small_window(window, app):
    from PySide6.QtCore import QPoint
    window.resize(860, 680)
    for step, button in (("backup", window.backup_button), ("restore_list", window.restore_next_button),
                          ("restore_target", window.restore_button)):
        window.show_page(step)
        app.processEvents()
        assert button.isVisible()
        position = button.mapTo(window, QPoint(0, 0))
        assert position.y() >= 0
        assert position.y() + button.height() <= window.height()


def test_current_pcsx2_restore_uses_this_pc_path_and_preserves_old_saves(window, tmp_path, monkeypatch):
    source, library = prepare_folders(window, tmp_path)
    snapshot = backup_pcsx2(source, library, emulator_closed=True)
    current = tmp_path / "New username Documents" / "PCSX2" / "memcards"
    current.mkdir(parents=True)
    (current / "old.ps2").write_bytes(b"old current saves")
    monkeypatch.setattr(ui, "find_pcsx2_memcards", lambda: current)
    select_restore_destination(window, tmp_path, "unused")
    window.restore_destination_mode.setCurrentIndex(1)
    assert window.current_restore_path.text() == str(current)
    assert current != Path(window.rows[0]["data"]["source_path"])
    window.restore_button.click()
    assert window.job is None
    assert window.current_restore_closed.property("needsConfirmation") is True
    window.current_restore_closed.setChecked(True)
    prompts = []
    def decline(*args):
        prompts.append(args)
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "warning", decline)
    window.restore_button.click()
    assert (current / "old.ps2").read_bytes() == b"old current saves"
    assert window.job is None
    assert str(current) in prompts[-1][2]
    assert prompts[-1][-1] == QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.StandardButton.Yes)
    window.restore_button.click()
    wait_idle(window)
    assert (current / "card.ps2").read_bytes() == (source / "card.ps2").read_bytes()
    previous = next(current.parent.glob("memcards.before-MemCard-*"))
    assert (previous / "old.ps2").read_bytes() == b"old current saves"
    assert str(previous) in window.restore_result.text()
    assert window.result_paths["restore"] == current
    assert window.open_restore_button.isVisible()
    assert not window.current_restore_closed.isChecked()
    verify_snapshot(snapshot)
    window.restore_menu_button.click()
    assert window.flow == "home"


def test_current_rpc3_restore_selects_user_from_current_installation(window, tmp_path, monkeypatch):
    monkeypatch.delenv("RPCS3_CONFIG_DIR", raising=False)
    source, library = prepare_folders(window, tmp_path)
    snapshot = backup_rpcs3(source, library, emulator_closed=True)
    root = tmp_path / "New RPCS3 installation"
    root.mkdir()
    executable = root / "rpcs3.exe"
    executable.write_bytes(b"never executed")
    users = []
    for identifier in ("00000001", "00000002"):
        folder = root / "dev_hdd0" / "home" / identifier / "savedata"
        folder.mkdir(parents=True)
        (folder / "previous.dat").write_bytes(identifier.encode())
        users.append(folder)
    window.ps3_button.click()
    wait_idle(window)
    window.rpcs3_exe.setText(str(executable))
    select_restore_destination(window, tmp_path, "unused")
    chosen_snapshot = window.selected()["path"]
    window.restore_destination_mode.setCurrentIndex(1)
    wait_idle(window)
    assert window.selected()["path"] == chosen_snapshot
    assert window.current_restore_path.text() == ""
    window.current_restore_users.setCurrentIndex(2)
    assert window.current_restore_path.text() == str(users[1])
    window.current_restore_closed.setChecked(True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.StandardButton.Yes)
    window.restore_button.click()
    wait_idle(window)
    assert (users[1] / "card.ps2").read_bytes() == (source / "card.ps2").read_bytes()
    assert (users[0] / "previous.dat").read_bytes() == b"00000001"
    previous = next(users[1].parent.glob("savedata.before-MemCard-*"))
    assert (previous / "previous.dat").read_bytes() == b"00000002"
    verify_snapshot(snapshot)


def test_main_menu_copy_and_sun_moon_toggle(window):
    from PySide6.QtWidgets import QLabel
    window.show_page("home")
    visible_text = [label.text() for label in window.findChildren(QLabel) if label.isVisible()]
    assert not any("Choose an emulator to back up" in value or "Your saves stay in place" in value for value in visible_text)
    assert not any(value.lower().startswith("choose an emulator to") for value in visible_text)
    assert "(PlayStation 2)" in window.ps2_button.text()
    assert "(PlayStation 3)" in window.ps3_button.text()
    assert not window.theme_button.icon().isNull()
    original = window.theme
    window.theme_button.click()
    assert window.theme != original
    window.theme_button.click()
    assert window.theme == original


def test_dropdown_popup_has_no_outer_bands(window):
    window.ps3_button.click()
    wait_idle(window)
    window.start_backup()
    window.set_folder_details(True)
    window.rpcs3_users.addItems(["User 00000001", "User 00000002"])
    window.rpcs3_users.showPopup()
    try:
        QTest.qWait(20)
        view = window.rpcs3_users.view()
        popup = view.window()
        assert view.geometry().top() == 0
        assert popup.rect().bottom() - view.geometry().bottom() <= 1
    finally:
        window.rpcs3_users.hidePopup()


def test_about_button_opens_shared_about_content(window, monkeypatch):
    from memcard.about import about_html
    calls = []
    monkeypatch.setattr(QMessageBox, "about", lambda parent, title, content: calls.append((parent, title, content)))
    window.show_page("home")
    assert window.about_button.isVisible()
    window.about_button.click()
    assert calls == [(window, "About MemCard", about_html())]
