"""MemCard alpha: Qt widgets around the independently tested filesystem engine."""

from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
import traceback

from PySide6.QtCore import QThread, Signal, Qt, QUrl, QSignalBlocker, QSize
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton,
    QTableWidgetItem, QVBoxLayout, QWidget, QScrollArea, QLayout, QToolButton,
)

from .discovery import discover_rpcs3, find_pcsx2_memcards
from .assets import APP_LOGO
from .about import about_html
from .instance import single_instance
from .manifest import load_manifest
from .paths import BackupError, checked_path, inventory, reject_overlap, relative_name
from .settings import load_settings, save_settings, settings_path
from .snapshots import (Cancelled, backup_pcsx2, backup_rpcs3, restore_pcsx2, restore_rpcs3,
                        restore_pcsx2_current, restore_rpcs3_current, EmulatorRestoreResult)
from .themes import AeroBanner, appearance_icon, palette, stylesheet
from .views import build_pages


MODES = {
    "pcsx2": {"emulator": "PCSX2", "kind": "pcsx2_memory_cards",
              "backup": backup_pcsx2, "restore": restore_pcsx2,
              "restore_current": restore_pcsx2_current, "folder": "memory-card", "hint": ""},
    "rpcs3": {"emulator": "RPCS3", "kind": "rpcs3_savedata",
              "backup": backup_rpcs3, "restore": restore_rpcs3,
              "restore_current": restore_rpcs3_current,
              "folder": "savedata", "hint": "Locate rpcs3.exe to find your save folders, then choose a user. You can also browse manually."},
}


def readable_size(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024


class Job(QThread):
    progress = Signal(int, int, str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.cancelled = Event()
        self.result = None
        self.error = None
        self.details = ""

    def run(self):
        try:
            self.result = self.operation(self)
        except Exception as error:
            self.error = error
            self.details = traceback.format_exc()


class MainWindow(QMainWindow):
    def __init__(self, preferences: Path | None = None):
        super().__init__()
        self.preferences = preferences or settings_path()
        self.job = None
        self.rows = []
        self.verifications = {}
        self.close_when_done = False
        self.setWindowTitle("MemCard | PS2 + PS3 Alpha")
        self.resize(1040, 820)
        self.setMinimumSize(860, 680)
        self.setWindowIcon(QIcon(str(APP_LOGO)))
        self.logger = logging.getLogger(f"memcard.ui.{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.handler = None
        settings_error = None
        try:
            settings = load_settings(self.preferences)
        except (OSError, ValueError) as error:
            settings, settings_error = {}, str(error)
        self.mode = settings.get("mode", "pcsx2")
        self.sources = {"pcsx2": settings.get("pcsx2_source", settings.get("source", "")),
                        "rpcs3": settings.get("rpcs3_source", "")}
        self.theme = settings.get("theme", "light")
        self.debug_expanded = settings.get("debug_expanded", False)
        self.rpcs3_candidates = []
        self.restore_user_candidates = []
        self.result_paths = {"backup": None, "restore": None}
        self.flow = "home"
        try:
            log_dir = self.preferences.parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            self.handler = RotatingFileHandler(log_dir / "memcard.log", maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
            self.logger.addHandler(self.handler)
        except OSError:
            pass

        root = QWidget()
        root.setObjectName("shell")
        central = QWidget()
        central.setObjectName("shell")
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        self.content_scroll = scroll
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(root)
        outer.addWidget(scroll, 1)
        self.setCentralWidget(central)
        layout = QVBoxLayout(root)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        self.banner = AeroBanner()
        header = QHBoxLayout(self.banner)
        header.setContentsMargins(96, 12, 20, 12)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        title = QLabel("MemCard")
        title.setObjectName("brand")
        brand.addWidget(title)
        tagline = QLabel("Your progress, safely preserved.")
        tagline.setObjectName("heroSubtitle")
        brand.addWidget(tagline)
        header.addLayout(brand)
        header.addStretch()
        badge = QLabel("PS2 + PS3  ·  Alpha")
        badge.setObjectName("badge")
        badge.setMaximumHeight(22)
        header.addWidget(badge)
        self.about_button = QPushButton("About")
        self.about_button.clicked.connect(self.show_about)
        header.addWidget(self.about_button)
        self.theme_button = QPushButton()
        self.theme_button.setIconSize(QSize(24, 24))
        self.theme_button.setFixedSize(44, 38)
        self.theme_button.clicked.connect(self.change_theme)
        header.addWidget(self.theme_button)
        layout.addWidget(self.banner)
        build_pages(self, layout, settings)
        self.action_strip = QWidget()
        action_layout = QHBoxLayout(self.action_strip)
        action_layout.setContentsMargins(18, 8, 18, 4)
        action_layout.addStretch()
        for button in (self.backup_button, self.restore_next_button, self.restore_button):
            action_layout.addWidget(button)
        outer.addWidget(self.action_strip)
        self.debug_panel = QWidget()
        debug_layout = QVBoxLayout(self.debug_panel)
        debug_layout.setContentsMargins(18, 6, 18, 0)
        self.log_toggle = QToolButton()
        self.log_toggle.setText("Activity && debug log")
        self.log_toggle.setObjectName("logToggle")
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.log_toggle.setCheckable(True)
        self.log_toggle.setAccessibleName("Expand or collapse activity and debug log")
        self.log_toggle.toggled.connect(self.set_debug_expanded)
        debug_layout.addWidget(self.log_toggle)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(1500)
        self.console.setMinimumHeight(95)
        debug_layout.addWidget(self.console)
        outer.addWidget(self.debug_panel)
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(18, 6, 18, 12)
        footer_layout.setSpacing(6)
        self.status = QLabel("READY / Select a source and a backup library.")
        self.status.setWordWrap(True)
        footer_layout.addWidget(self.status)
        bottom = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setValue(0)
        bottom.addWidget(self.progress_bar, 1)
        self.cancel_button = QPushButton("Cancel job")
        self.cancel_button.clicked.connect(self.cancel_job)
        bottom.addWidget(self.cancel_button)
        footer_layout.addLayout(bottom)
        outer.addWidget(footer)
        self.controls = [self.source, self.library, self.source_button, self.library_button,
                         self.detect_button, self.closed, self.backup_button, self.refresh_button, self.table,
                         self.ps2_button, self.ps3_button, self.rpcs3_exe, self.rpcs3_users,
                         self.locate_rpcs3_button, self.back_button, self.home_button,
                         self.start_backup_button, self.start_restore_button, self.folder_toggle,
                         self.restore_library_button, self.restore_next_button, self.restore_parent,
                         self.restore_parent_button, self.restore_name, self.restore_destination_mode,
                         self.current_restore_browse, self.current_restore_detect, self.current_restore_users,
                         self.current_restore_closed, self.open_backup_button, self.backup_menu_button,
                         self.open_restore_button, self.restore_menu_button]
        self.source.editingFinished.connect(self.remember)
        self.source.textChanged.connect(self.source_changed)
        self.library.editingFinished.connect(self.library_changed)
        self.library.textChanged.connect(self.update_summaries)
        self.restore_parent.textChanged.connect(self.update_restore_preview)
        self.restore_name.textChanged.connect(self.update_restore_preview)
        self.log("MemCard alpha started. Commands shown below are references; operations call the Python engine directly.")
        if settings_error:
            self.log(f"Settings could not be loaded: {settings_error}")
        if self.handler is None:
            self.log("Disk log unavailable; activity remains visible in this console.")
        self.apply_mode_labels()
        self.apply_theme()
        self.set_debug_expanded(self.debug_expanded, persist=False)
        if not self.source.text() and self.mode == "pcsx2":
            self.detect_source()
        self.update_actions()
        self.update_summaries()
        self.show_page("home")

    def show_page(self, name):
        if self.job:
            return
        self.flow = name
        self.pages.setCurrentWidget(self.page_widgets[name])
        self.pages.updateGeometry()
        self.navigation.setVisible(name != "home")
        self.status.setVisible(name != "home")
        self.action_strip.setVisible(name in {"backup", "restore_list", "restore_target"})
        for button, step in ((self.backup_button, "backup"), (self.restore_next_button, "restore_list"),
                              (self.restore_button, "restore_target")):
            button.setVisible(name == step)
        emulator = MODES[self.mode]["emulator"]
        labels = {"home": "", "overview": "Choose Back up or Restore.",
                  "backup": "Review your folders and confirm the emulator is closed.",
                  "restore_list": "Choose a backup to recover.", "restore_target": "Choose a new recovery folder."}
        self.breadcrumb.setText(f"{emulator}  /  " + {"home": "Emulators", "overview": "Your saves", "backup": "Back up saves", "restore_list": "Restore · choose backup", "restore_target": "Restore · destination"}[name])
        self.status.setText(labels[name])
        self.content_scroll.verticalScrollBar().setValue(0)
        self.update_summaries()
        self.update_actions()

    def go_back(self):
        previous = {"overview": "home", "backup": "overview", "restore_list": "overview", "restore_target": "restore_list"}
        self.show_page(previous.get(self.flow, "home"))

    def choose_emulator(self, mode):
        if self.job:
            return
        self.switch_mode(mode)
        self.show_page("overview")
        self.refresh()

    def start_backup(self):
        if self.job:
            return
        self.closed.setChecked(False)
        self.clear_confirmation_hint()
        self.reset_result("backup")
        self.show_page("backup")
        if self.mode == "pcsx2" and not self.source.text():
            self.detect_source()
        ready = bool(self.source.text() and Path(self.source.text()).is_dir()
                     and self.library.text() and Path(self.library.text()).is_dir())
        self.set_folder_details(not ready)
        if self.mode == "rpcs3" and self.rpcs3_exe.text():
            self.find_rpcs3_users()
        else:
            self.update_summaries()

    def start_restore(self):
        if self.job:
            return
        self.reset_result("restore")
        self.show_page("restore_list")
        self.refresh()

    def set_folder_details(self, expanded):
        with QSignalBlocker(self.folder_toggle):
            self.folder_toggle.setChecked(expanded)
        self.folder_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.folder_toggle.setText("Hide folder details" if expanded else "Change folders / show details")
        self.setup_panel.setVisible(expanded)
        self.pages.updateGeometry()

    def update_summaries(self):
        current = self.source.text().strip()
        for mode in MODES:
            value = current if mode == self.mode else self.sources[mode]
            found = bool(value and Path(value).is_dir())
            self.emulator_status[mode].setText("Save folder available" if found else "Find your save folder")
        emulator = MODES[self.mode]["emulator"]
        found = bool(current and Path(current).is_dir())
        self.overview_title.setText(f"Your {emulator} saves")
        self.overview_summary.setText("Your save folder is ready. Choose what you want to do." if found else "Set up your save folder for a backup, or recover an existing backup.")
        self.backup_summary.setText(f"{emulator} save folder found" if found else f"Choose your {emulator} save folder")
        if found and self.mode == "rpcs3":
            user = Path(current).parent.name
            self.backup_summary.setText(f"RPCS3 · User {user}" if len(user) == 8 and user.isdigit() else "RPCS3 save folder selected")
        self.backup_summary.setToolTip(current)
        destination = self.library.text().strip()
        self.backup_destination.setText(f"Backup destination: {Path(destination).name or destination}" if destination else "Choose where to store your backups.")
        self.backup_destination.setToolTip(destination)
        self.restore_library_summary.setText(f"Backup folder: {destination}" if destination else "Choose the folder containing your backups.")
        valid = [row["data"] for row in self.rows if row.get("data") and row["data"]["preset"]["kind"] == MODES[self.mode]["kind"]]
        if valid:
            latest = max(valid, key=lambda data: data["created_at_utc"])
            when = datetime.fromisoformat(latest["created_at_utc"]).astimezone().strftime("%d %b %Y, %H:%M")
            self.last_backup.setText(f"Last backup in this folder: {when} · {latest['preset']['label']}")
        else:
            self.last_backup.setText("Choose Restore to browse backups, or Back up to create one.")

    def show_restore_target(self):
        row = self.selected()
        if self.job or not row or not row.get("data"):
            return
        data = row["data"]
        when = datetime.fromisoformat(data["created_at_utc"]).astimezone().strftime("%d %b %Y, %H:%M")
        self.restore_review.setText(f"{data['preset']['label']}\n{when} · {len(data['files'])} files · {readable_size(sum(item['size_bytes'] for item in data['files']))}")
        self.reset_result("restore")
        self.restore_step_title.setText("Where should we recover your saves?")
        self.restore_step_description.setText("Step 2 of 2 · Recover to a new folder, or choose this computer's current emulator save folder.")
        self.restore_destination_mode.show()
        self.restore_info.show()
        self.show_page("restore_target")
        self.restore_destination_mode.setCurrentIndex(0)
        self.restore_destination_changed()
        self.current_restore_closed.setChecked(False)
        self.update_restore_preview()

    def choose_restore_parent(self):
        parent = QFileDialog.getExistingDirectory(self, "Choose a parent folder for recovered saves", self.restore_parent.text())
        if parent:
            self.restore_parent.setText(parent)

    def update_restore_preview(self):
        if self.restore_destination_mode.currentData() == "current":
            target = self.current_restore_path.text()
            self.restore_target_preview.setText(f"Current save folder: {target}" if target else "Locate the emulator's current save folder.")
            return
        parent, name = self.restore_parent.text().strip(), self.restore_name.text()
        self.restore_target_preview.setText(f"New recovery folder: {Path(parent) / name}" if parent and name else "Select a parent folder and give the recovered folder a new name.")

    def reset_result(self, kind):
        self.result_paths[kind] = None
        if kind == "backup":
            self.backup_result.clear()
            self.open_backup_button.hide()
            self.backup_menu_button.hide()
        else:
            self.restore_result.clear()
            self.open_restore_button.hide()
            self.restore_menu_button.hide()

    def open_result_directory(self, kind):
        path = self.result_paths[kind]
        if path is None:
            return
        if not path.is_dir():
            QMessageBox.warning(self, "Folder unavailable", f"Reconnect the drive or locate this folder:\n{path}")
            return
        self.log(f"OPEN / {path}")
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "Could not open folder", str(path))

    def restore_destination_changed(self):
        current = self.restore_destination_mode.currentData() == "current"
        self.new_restore_panel.setVisible(not current)
        self.current_restore_panel.setVisible(current)
        self.current_restore_closed.setChecked(False)
        self.current_restore_closed.setProperty("needsConfirmation", False)
        self.current_restore_closed.update()
        self.pages.updateGeometry()
        self.update_restore_preview()
        if current and self.flow == "restore_target" and not self.job:
            self.find_current_restore_folder()

    def current_restore_path_changed(self):
        self.current_restore_closed.setChecked(False)
        self.current_restore_closed.setProperty("needsConfirmation", False)
        self.current_restore_closed.update()
        self.current_restore_path.setToolTip(self.current_restore_path.text())
        self.update_restore_preview()

    def current_restore_confirmation_changed(self, checked):
        if checked:
            self.current_restore_closed.setProperty("needsConfirmation", False)
            self.current_restore_closed.update()

    def choose_current_restore_folder(self):
        emulator = MODES[self.mode]["emulator"]
        path = QFileDialog.getExistingDirectory(self, f"Choose the current {emulator} save folder", self.current_restore_path.text())
        if path:
            with QSignalBlocker(self.current_restore_users):
                self.current_restore_users.setCurrentIndex(0)
            self.current_restore_path.setText(path)

    def select_current_restore_user(self):
        self.current_restore_path.setText(self.current_restore_users.currentData() or "")

    def find_current_restore_folder(self):
        if self.job:
            return
        self.current_restore_path.clear()
        self.current_restore_warning.setText("Existing saves will be replaced. The previous save folder will be retained beside the restored folder. Confirm the full path and intended emulator user before proceeding.")
        if self.mode == "pcsx2":
            candidate = find_pcsx2_memcards()
            if candidate:
                self.current_restore_path.setText(str(candidate))
            else:
                self.current_restore_warning.setText("No default PCSX2 memory-card folder was found on this PC. Use Choose save folder to select the folder used by the current installation. Existing saves there will be replaced and the previous folder retained.")
            return
        executable = self.rpcs3_exe.text().strip()
        if not executable or not Path(executable).is_file() or self.sender() is self.current_restore_detect:
            executable, _ = QFileDialog.getOpenFileName(self, "Locate the current RPCS3 installation", executable, "RPCS3 (rpcs3.exe)")
            if not executable:
                return
            self.rpcs3_exe.setText(executable)
        self.restore_user_candidates = []
        with QSignalBlocker(self.current_restore_users):
            self.current_restore_users.clear()
            self.current_restore_users.addItem("Choose an RPCS3 user", None)

        def discovered(location):
            self.restore_user_candidates = list(location.users)
            self.log(f"RESTORE TARGET / RPCS3 HDD on this PC: {location.hdd0}")
            for warning in location.warnings:
                self.log(warning)
            with QSignalBlocker(self.current_restore_users):
                for path in location.users:
                    self.current_restore_users.addItem(f"User {path.parent.name}", str(path))
                if len(location.users) == 1:
                    self.current_restore_users.setCurrentIndex(1)
            self.select_current_restore_user()
            self.update_actions()
            if not location.users:
                self.current_restore_warning.setText("No user savedata folders were found. Choose the actual save folder manually. Existing saves will be replaced and the previous folder retained.")
            self.status.setText("Confirm the current RPCS3 user and save folder.")
            self.remember()

        self.start_job("Finding the current RPCS3 save folders…", lambda job: discover_rpcs3(executable), discovered)
        self.job.discovering_restore = True

    def log(self, message):
        line = f"[{datetime.now().astimezone():%H:%M:%S}] {message}"
        self.console.appendPlainText(line)
        self.logger.info(line)

    def show_about(self):
        QMessageBox.about(self, "About MemCard", about_html())

    def command(self, *args):
        self.log("CLI > " + subprocess.list2cmdline([sys.executable, "main.py", *map(str, args)]))

    def apply_theme(self):
        self.setPalette(palette(self.theme))
        self.setStyleSheet(stylesheet(self.theme))
        self.banner.theme = self.theme
        self.banner.update()
        self.theme_button.setIcon(appearance_icon(self.theme))
        action = "Switch to dark mode" if self.theme == "light" else "Switch to light mode"
        self.theme_button.setToolTip(action)
        self.theme_button.setAccessibleName(action)

    def change_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.apply_theme()
        self.remember()
        self.log(f"Appearance changed to {self.theme} mode.")

    def set_debug_expanded(self, expanded, persist=True):
        self.debug_expanded = bool(expanded)
        with QSignalBlocker(self.log_toggle):
            self.log_toggle.setChecked(self.debug_expanded)
        self.log_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.console.setVisible(self.debug_expanded)
        self.debug_panel.setMinimumHeight(135 if expanded else 36)
        self.debug_panel.setMaximumHeight(170 if expanded else 40)
        if persist:
            self.remember()

    def clear_confirmation_hint(self):
        self.closed.setProperty("needsConfirmation", False)
        self.closed.setAccessibleDescription("")
        self.closed.update()
        self.confirmation_hint.hide()

    def confirmation_changed(self, checked):
        if checked:
            self.clear_confirmation_hint()
            if self.status.text().startswith("ACTION NEEDED"):
                self.status.setText("READY / Confirmation received. Click Back up now to continue.")

    def source_changed(self):
        self.closed.setChecked(False)
        self.clear_confirmation_hint()
        self.source.setToolTip(self.source.text())
        self.update_summaries()
        if self.mode == "rpcs3":
            with QSignalBlocker(self.rpcs3_users):
                index = self.rpcs3_users.findData(self.source.text())
                self.rpcs3_users.setCurrentIndex(max(index, 0))

    def locate_rpcs3(self):
        executable, _ = QFileDialog.getOpenFileName(
            self, "Locate the RPCS3 application", self.rpcs3_exe.text(), "RPCS3 (rpcs3.exe)"
        )
        if not executable:
            return
        if executable != self.rpcs3_exe.text():
            self.source.clear()
        self.rpcs3_exe.setText(executable)
        self.rpcs3_exe.setToolTip(executable)
        self.find_rpcs3_users()

    def find_rpcs3_users(self):
        if self.job:
            return
        executable = self.rpcs3_exe.text().strip()
        if not executable:
            self.locate_rpcs3()
            return
        preferred = self.source.text().strip()
        self.rpcs3_candidates = []
        self.source.clear()
        with QSignalBlocker(self.rpcs3_users):
            self.rpcs3_users.clear()
            self.rpcs3_users.addItem("Finding save folders…", None)
        self.rows = []
        self.table.setRowCount(0)
        self.remember()
        self.log(f"DISCOVER / Reading RPCS3 paths for {executable}; the executable is not launched.")

        def discovered(location):
            self.rpcs3_candidates = list(location.users)
            self.log(f"RPCS3 data root: {location.config_root}")
            self.log(f"RPCS3 virtual HDD: {location.hdd0}")
            for warning in location.warnings:
                self.log(warning)
            with QSignalBlocker(self.rpcs3_users):
                self.rpcs3_users.clear()
                self.rpcs3_users.addItem("Choose a user, or browse to a custom save folder", None)
                for path in location.users:
                    self.rpcs3_users.addItem(f"User {path.parent.name}", str(path))
                    self.log(f"RPCS3 user {path.parent.name}: {path}")
                index = self.rpcs3_users.findData(preferred)
                if index < 1 and len(location.users) == 1:
                    index = 1
                self.rpcs3_users.setCurrentIndex(max(index, 0))
            self.select_rpcs3_user()
            count = len(location.users)
            self.source_hint.setText(
                f"Found {count} user save folder(s). Confirm the user and resolved path before backing up."
                if count else "No savedata folders were found. Check RPCS3's virtual HDD settings, or browse manually."
            )
            self.update_actions()
            self.update_summaries()
            if not self.source.text():
                self.set_folder_details(True)
            self.status.setText("READY / RPCS3 users discovered." if count else "READY / Select the save folder manually.")
            self.refresh()

        self.start_job("DISCOVER / Finding RPCS3 users and save folders", lambda job: discover_rpcs3(executable), discovered)
        self.job.discovering_rpcs3 = True

    def select_rpcs3_user(self):
        if self.mode != "rpcs3":
            return
        selected = self.rpcs3_users.currentData()
        self.source.setText(selected or "")
        self.closed.setChecked(False)
        self.remember()

    def remember(self):
        self.sources[self.mode] = self.source.text().strip()
        try:
            save_settings(self.preferences, {"source": self.sources["pcsx2"],
                          "pcsx2_source": self.sources["pcsx2"], "rpcs3_source": self.sources["rpcs3"],
                          "mode": self.mode, "library": self.library.text().strip(),
                          "theme": self.theme, "rpcs3_executable": self.rpcs3_exe.text().strip(),
                          "debug_expanded": self.debug_expanded})
        except OSError as error:
            self.log(f"Could not save preferences: {error}")

    def choose_source(self):
        config = MODES[self.mode]
        path = QFileDialog.getExistingDirectory(self, f"Select {config['emulator']} {config['folder']} folder", self.source.text())
        if path:
            self.source.setText(path)
            self.closed.setChecked(False)
            self.remember()

    def detect_source(self):
        if self.mode == "rpcs3":
            if self.rpcs3_exe.text():
                self.find_rpcs3_users()
            else:
                self.locate_rpcs3()
            return
        candidate = find_pcsx2_memcards()
        if candidate:
            self.source.setText(str(candidate))
            self.log(f"Detected candidate: {candidate}. Confirm it matches PCSX2 settings.")
        else:
            self.source.setPlaceholderText("Not found in Documents. Use BROWSE to select your save directory.")
            self.log("No safe Documents/PCSX2/memcards folder found. Use BROWSE; in PCSX2: Settings > Memory Cards > Browse.")
        self.closed.setChecked(False)

    def apply_mode_labels(self):
        self.clear_confirmation_hint()
        config = MODES[self.mode]
        self.setWindowTitle(f"MemCard | {config['emulator']} Alpha")
        self.source_label.setText("Memory cards" if self.mode == "pcsx2" else "Save folder")
        self.restore_name.setText(f"{config['emulator']}-Restored")
        self.source_hint.setText(config["hint"])
        self.source_hint.setVisible(bool(config["hint"]))
        self.current_restore_users.setVisible(self.mode == "rpcs3")
        self.current_restore_detect.setText("Find current PCSX2 folder" if self.mode == "pcsx2" else "Locate RPCS3…")
        self.current_restore_closed.setText(f"{config['emulator']} is closed and I confirmed this save folder.")
        self.source.setPlaceholderText(f"Select your {config['emulator']} {config['folder']} folder")
        self.closed.setText(f"{config['emulator']} is closed. I confirmed the selected save folder.")
        self.detect_button.setText("Find saves" if self.mode == "pcsx2" else "Rescan users")
        for widget in self.rpcs3_widgets:
            widget.setVisible(self.mode == "rpcs3")

    def switch_mode(self, mode):
        if self.job:
            return
        if mode == self.mode:
            self.update_summaries()
            return
        self.sources[self.mode] = self.source.text().strip()
        self.mode = mode
        self.ps2_button.setChecked(mode == "pcsx2")
        self.ps3_button.setChecked(mode == "rpcs3")
        self.source.setText(self.sources[mode])
        self.closed.setChecked(False)
        self.apply_mode_labels()
        self.restore_name.setText(f"{MODES[mode]['emulator']}-Restored")
        self.restore_parent.clear()
        self.current_restore_path.clear()
        self.restore_destination_mode.setCurrentIndex(0)
        self.reset_result("backup")
        self.reset_result("restore")
        self.rows = []
        self.table.setRowCount(0)
        if mode == "pcsx2" and not self.source.text():
            self.detect_source()
        self.log(f"MODE / {MODES[mode]['emulator']}. {MODES[mode]['hint']}")
        self.remember()

    def choose_library(self):
        path = QFileDialog.getExistingDirectory(self, "Choose backup library", self.library.text())
        if path:
            self.library.setText(path)
            self.library_changed()

    def library_changed(self):
        self.remember()
        self.refresh()

    def selected(self):
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def update_actions(self):
        busy = self.job is not None
        for control in self.controls:
            control.setEnabled(not busy)
        self.rpcs3_users.setEnabled(not busy and bool(self.rpcs3_candidates))
        self.current_restore_users.setEnabled(not busy and bool(self.restore_user_candidates))
        selected = self.selected()
        valid = bool(selected and selected.get("data"))
        self.restore_button.setEnabled(not busy and valid)
        self.restore_next_button.setEnabled(not busy and valid)
        if not busy:
            self.cancel_button.setEnabled(False)
        self.progress_bar.setVisible(busy)
        self.cancel_button.setVisible(busy)

    def start_job(self, title, operation, completed, cancellable=False):
        if self.job is not None:
            return
        self.status.setText(title)
        self.log(title)
        self.progress_bar.setRange(0, 0)
        job = Job(operation, self)
        self.job = job
        job.progress.connect(self.on_progress)
        job.finished.connect(lambda: self.finish_job(job, completed))
        self.update_actions()
        self.cancel_button.setEnabled(cancellable)
        job.start()

    def finish_job(self, job, completed):
        self.job = None
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0 if job.error else 100)
        self.update_actions()
        if job.error:
            if hasattr(job, "discovering_restore"):
                self.current_restore_warning.setText("Could not resolve this installation. Choose the actual save folder manually. " + str(job.error))
            if hasattr(job, "discovering_rpcs3"):
                self.set_folder_details(True)
                self.source_hint.setText("RPCS3 could not be resolved. Locate it again, or browse to the actual savedata folder.")
                with QSignalBlocker(self.rpcs3_users):
                    self.rpcs3_users.clear()
                    self.rpcs3_users.addItem("Discovery unavailable — browse to savedata manually", None)
            if hasattr(job, "scan_path"):
                self.library_status.setText(f"UNAVAILABLE / {job.scan_path} — reconnect or choose another library.")
                self.empty.setText("Library could not be read. See the activity console.")
            self.log(job.details)
            self.status.setText(f"{'CANCELLED' if isinstance(job.error, Cancelled) else 'FAILED'} / {job.error}")
            if not isinstance(job.error, Cancelled):
                details = "\n".join([str(job.error), *getattr(job.error, "__notes__", [])])
                QMessageBox.warning(self, "Operation failed", details)
        elif not self.close_when_done:
            completed(job.result)
        job.deleteLater()
        if self.close_when_done:
            self.close()

    def on_progress(self, done, total, name):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self.status.setText(f"COPY / {done}/{total} / {name} — final verification follows")
        self.log(f"COPY [{done}/{total}] {name}")
        if done == total:
            self.progress_bar.setRange(0, 0)
            self.status.setText("VERIFY / Checking copied files before publication.")

    def cancel_job(self):
        if self.job:
            self.job.cancelled.set()
            self.cancel_button.setEnabled(False)
            self.log("Cancellation requested; waiting for the next safe boundary before publication.")
            self.status.setText("CANCELLING / Waiting for the current copy or verification to finish.")

    def refresh(self):
        if self.job:
            return
        self.rows = []
        self.table.setRowCount(0)
        self.update_actions()
        path_text = self.library.text().strip()
        if not path_text:
            self.library_status.setText("Choose a library to load its snapshots.")
            self.empty.setText("No library selected.")
            return
        library = Path(path_text)
        kind = MODES[self.mode]["kind"]

        def scan(job):
            root = checked_path(library)
            if not root.is_dir():
                raise BackupError(f"Library unavailable: {root}")
            snapshots = root / "snapshots"
            if not snapshots.exists():
                return []
            checked_path(snapshots)
            rows = []
            for entry in sorted(snapshots.iterdir(), reverse=True):
                if job.cancelled.is_set():
                    raise Cancelled("Library scan cancelled")
                if entry.name.startswith(".staging-"):
                    continue
                try:
                    data = load_manifest(entry)
                    if data["preset"]["kind"] != kind:
                        continue
                    rows.append({"path": entry, "data": data})
                except (OSError, ValueError) as error:
                    rows.append({"path": entry, "error": str(error)})
            return rows

        self.library_status.setText(f"Loading: {library}")

        def loaded(rows):
            self.rows = rows
            self.table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                data = row.get("data")
                if data:
                    date = datetime.fromisoformat(data["created_at_utc"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
                    status = self.verifications.get(str(row["path"]), "Checks on restore")
                    values = [date, data["preset"]["label"], readable_size(sum(f["size_bytes"] for f in data["files"])), status]
                else:
                    values = [row["path"].name, "Invalid snapshot", "—", "INVALID"]
                    self.log(f"Invalid snapshot {row['path']}: {row['error']}")
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(row.get("error", str(row["path"])))
                    self.table.setItem(index, column, item)
            self.empty.setText(f"{len(rows)} snapshot(s)")
            warning = " / SYSTEM VOLUME" if library.absolute().drive.casefold() == os.environ.get("SystemDrive", "C:").casefold() else ""
            self.library_status.setText(f"AVAILABLE / {library.absolute()}{warning}")
            self.status.setText({"home": "",
                                 "overview": "Choose Back up or Restore.",
                                 "backup": "Backup completed and verified." if self.backup_result.text() else "Ready to back up your saves.",
                                 "restore_list": "Choose a backup to restore.",
                                 "restore_target": "Choose a new recovery folder."}[self.flow])
            self.log(f"Library loaded: {len(rows)} snapshot(s). Metadata listing does not verify file contents.")
            if rows:
                self.table.selectRow(0)
            self.update_summaries()
            self.update_actions()

        self.start_job("SCAN / Loading library metadata", scan, loaded)
        self.job.scan_path = library

    def prepare_backup(self):
        mode = self.mode
        config = MODES[mode]
        emulator = config["emulator"]
        if not self.closed.isChecked():
            message = f"Close {emulator}, then tick the highlighted box to continue."
            self.closed.setProperty("needsConfirmation", True)
            self.closed.setAccessibleDescription(message)
            self.closed.update()
            self.closed.setFocus(Qt.FocusReason.OtherFocusReason)
            self.confirmation_hint.setText(message)
            self.confirmation_hint.show()
            self.content_scroll.ensureWidgetVisible(self.closed, 20, 40)
            self.status.setText(f"ACTION NEEDED / {message}")
            return
        if not self.source.text().strip() or not self.library.text().strip():
            self.set_folder_details(True)
            QMessageBox.information(self, "Choose folders", "Select both the save folder and backup library.")
            return
        source, library = Path(self.source.text().strip()), Path(self.library.text().strip())
        self.remember()

        def prepare(job):
            origin, destination = checked_path(source), checked_path(library)
            reject_overlap(origin, destination)
            _, files = inventory(origin)
            if not files:
                raise BackupError(f"Source has no files: {origin}")
            return origin, destination, len(files), sum(info[0] for info in files.values())

        def confirm(result):
            origin, destination, count, size = result
            message = f"{emulator} source:\n{origin}\n\nLibrary:\n{destination}\n\n{count} files / {readable_size(size)}\n\n{emulator} must remain closed."
            if QMessageBox.question(self, "Create verified backup?", message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                self.status.setText("READY / Backup declined; no files copied.")
                return
            self.command(f"backup-{mode}", "--source", origin, "--library", destination, "--emulator-closed")
            self.start_job(f"BACKUP / {emulator}: copying, then verifying snapshot", lambda job: config["backup"](origin, destination, emulator_closed=True, progress=job.progress.emit, cancelled=job.cancelled.is_set), self.backup_done, True)

        self.start_job("PREPARE / Checking source inventory", prepare, confirm)

    def backup_done(self, path):
        self.verifications[str(path)] = f"VERIFIED {datetime.now():%H:%M:%S}"
        self.log(f"SUCCESS / Verified snapshot published: {path}")
        QMessageBox.information(self, "Backup complete", f"Verified snapshot created:\n{path}")
        self.backup_result.setText(f"Backup complete. Your saves were copied and verified.\n{path}")
        self.result_paths["backup"] = path
        self.open_backup_button.show()
        self.backup_menu_button.show()
        self.action_strip.hide()
        self.refresh()

    def restore_selected(self):
        row = self.selected()
        if not row or not row.get("data"):
            return
        mode = self.mode
        config = MODES[mode]
        emulator = config["emulator"]
        current = self.restore_destination_mode.currentData() == "current"
        parent_text = self.restore_parent.text().strip()
        name = self.restore_name.text()
        try:
            if current:
                value = self.current_restore_path.text().strip()
                if not value:
                    raise BackupError("Find or choose the current emulator save folder first")
                target = checked_path(value)
                if not target.is_dir():
                    raise BackupError(f"Choose an existing save folder: {target}")
                if not self.current_restore_closed.isChecked():
                    self.current_restore_closed.setProperty("needsConfirmation", True)
                    self.current_restore_closed.update()
                    self.current_restore_closed.setFocus()
                    self.status.setText(f"Close {emulator} and confirm the selected restore folder.")
                    return
            else:
                if not parent_text:
                    raise BackupError("Choose a parent folder for the recovered saves")
                parent = checked_path(parent_text)
                if not parent.is_dir():
                    raise BackupError(f"Choose an existing parent folder: {parent}")
                relative_name(name)
                if "/" in name:
                    raise BackupError("Enter a single folder name")
                target = Path(parent) / name
                if os.path.lexists(target):
                    raise BackupError(f"Target already exists: {target}")
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Choose a new folder", str(error))
            return
        data, snapshot = row["data"], row["path"]
        text = f"Snapshot: {data['created_at_utc']}\nPreset: {data['preset']['label']}\nFiles: {len(data['files'])}\n\nNew target:\n{target}\n\nThe snapshot and restored copy will be verified."
        if current:
            text = f"Replace the current {emulator} saves in this exact folder?\n\n{target}\n\nBackup: {data['preset']['label']}\nDate: {data['created_at_utc']}\n\nExisting saves will be replaced, not merged. The previous folder will be kept beside this folder with a .before-MemCard name."
        confirm = QMessageBox.warning if current else QMessageBox.question
        if confirm(self, "Replace current saves?" if current else "Restore to new folder?", text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        library = Path(self.library.text().strip())
        sources = [Path(value) for value in self.sources.values() if value.strip()]
        sources.extend(self.rpcs3_candidates)
        sources.extend(self.restore_user_candidates)
        if self.source.text().strip():
            sources.append(Path(self.source.text().strip()))
        detected = find_pcsx2_memcards()
        if detected:
            sources.append(detected)
        if current:
            self.log(f"ENGINE > restore_{mode}_current / snapshot={snapshot} / target={target} / previous folder retained")
        else:
            self.command(f"restore-{mode}", snapshot, "--library", library, "--target", target, *[part for source in sources for part in ("--source", source)])
        self.reset_result("restore")

        def done(result):
            path = result.target if isinstance(result, EmulatorRestoreResult) else result
            previous = result.previous if isinstance(result, EmulatorRestoreResult) else None
            self.status.setText(f"RESTORED / {path}")
            self.log(f"SUCCESS / Restored and verified: {path}")
            note = f"\n\nPrevious saves retained at:\n{previous}" if previous else ""
            self.restore_result.setText(f"Recovery complete. Your saves were restored and verified.\n{path}{note}")
            self.result_paths["restore"] = path
            self.open_restore_button.show()
            self.restore_menu_button.show()
            self.restore_step_title.setText("Your saves have been restored")
            self.restore_step_description.setText("Recovery completed successfully. Open the recovered folder or return to the main menu.")
            self.restore_destination_mode.hide()
            self.new_restore_panel.hide()
            self.current_restore_panel.hide()
            self.restore_info.hide()
            self.action_strip.hide()
            self.pages.updateGeometry()
            if current:
                self.source.setText(str(path))
                self.current_restore_closed.setChecked(False)
                self.remember()
            QMessageBox.information(self, "Restore complete", f"Verified saves restored to:\n{path}{note}")

        def recover(job):
            options = dict(configured_sources=tuple(sources), progress=job.progress.emit, cancelled=job.cancelled.is_set)
            if current:
                return config["restore_current"](snapshot, library, target, emulator_closed=True, **options)
            return config["restore"](snapshot, library, target, **options)

        self.start_job(f"RESTORE / {emulator}: verifying snapshot, copying, then verifying restored files", recover, done, True)

    def closeEvent(self, event):
        if self.job:
            answer = QMessageBox.question(self, "Job running", "Cancel this job and close after it safely finishes?\nChoose No to keep waiting.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.close_when_done = True
                self.cancel_job()
            event.ignore()
            return
        self.remember()
        if self.handler:
            self.logger.removeHandler(self.handler)
            self.handler.close()
        event.accept()


def launch() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setApplicationName("MemCard")
    app.setWindowIcon(QIcon(str(APP_LOGO)))
    try:
        with single_instance():
            window = MainWindow()
            window.show()
            return app.exec()
    except (OSError, BackupError) as error:
        QMessageBox.critical(None, "MemCard", str(error))
        return 1
