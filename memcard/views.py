"""Build the guided screens; filesystem work remains in the controller/engine."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QStackedWidget, QTableWidget,
    QToolButton, QVBoxLayout, QWidget, QLayout, QSizePolicy,
)

from .themes import AeroCheckBox, emulator_icon


def text(value, style=None):
    label = QLabel(value)
    label.setWordWrap(True)
    if style:
        label.setObjectName(style)
    return label


class AeroComboBox(QComboBox):
    """Use a framed Qt list rather than the native menu's dark popup margins."""
    def __init__(self):
        super().__init__()
        from PySide6.QtWidgets import QListView
        view = QListView()
        view.setFrameShape(QFrame.Shape.NoFrame)
        self.setView(view)

    def showPopup(self):
        super().showPopup()
        container = self.view().window()
        if isinstance(container, QFrame):
            container.setFrameShape(QFrame.Shape.NoFrame)
            container.setContentsMargins(0, 0, 0, 0)
            if container.layout():
                layout = container.layout()
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)
                # Qt adds menu-style spacer items independently of margins.
                # Their unpainted background produced the top/bottom bands.
                removed_height = 0
                for index in range(layout.count()):
                    spacer = layout.itemAt(index).spacerItem()
                    if spacer:
                        removed_height += spacer.sizeHint().height()
                        spacer.changeSize(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                layout.invalidate()
                if removed_height:
                    container.resize(container.width(), max(1, container.height() - removed_height))
                layout.activate()


def panel():
    frame = QFrame()
    frame.setObjectName("panel")
    return frame


def page(title, description):
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)
    layout.addWidget(text(title, "pageTitle"))
    layout.addWidget(text(description, "muted"))
    return widget, layout


class FlowPages(QStackedWidget):
    """Size the visible step, rather than the largest hidden setup screen."""
    def __init__(self):
        super().__init__()
        self.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.setMinimumSize(0, 0)
    def sizeHint(self):
        return self.currentWidget().sizeHint() if self.currentWidget() else super().sizeHint()

    def minimumSizeHint(self):
        return self.currentWidget().minimumSizeHint() if self.currentWidget() else super().minimumSizeHint()


def build_pages(self, layout, settings):
    navigation = QHBoxLayout()
    self.back_button = QPushButton("‹ Back")
    self.back_button.clicked.connect(self.go_back)
    self.breadcrumb = QLabel()
    self.breadcrumb.setObjectName("muted")
    self.home_button = QPushButton("Change emulator")
    self.home_button.clicked.connect(lambda: self.show_page("home"))
    navigation.addWidget(self.back_button)
    navigation.addWidget(self.breadcrumb, 1)
    navigation.addWidget(self.home_button)
    self.navigation = QWidget()
    self.navigation.setLayout(navigation)
    layout.addWidget(self.navigation)
    self.pages = FlowPages()
    layout.addWidget(self.pages, 1)
    self.page_widgets = {}

    home, home_layout = page("Which emulator are you using?", "")
    home_layout.itemAt(1).widget().hide()
    cards = QHBoxLayout()
    self.mode_group = QButtonGroup(self)
    self.ps2_button, self.ps3_button = QToolButton(), QToolButton()
    self.emulator_status = {}
    for mode, button, title in (("pcsx2", self.ps2_button, "PCSX2\n(PlayStation 2)"),
                                 ("rpcs3", self.ps3_button, "RPCS3\n(PlayStation 3)")):
        card = QVBoxLayout()
        button.setText(title)
        button.setObjectName("emulatorCard")
        button.setIcon(emulator_icon(mode))
        button.setIconSize(QSize(100, 100))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setMinimumHeight(210)
        button.setMinimumWidth(260)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        button.setCheckable(True)
        self.mode_group.addButton(button)
        button.clicked.connect(lambda checked=False, key=mode: self.choose_emulator(key))
        card.addWidget(button)
        self.emulator_status[mode] = text("", "muted")
        self.emulator_status[mode].setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.addWidget(self.emulator_status[mode])
        cards.addLayout(card, 1)
    home_layout.addLayout(cards)
    home_layout.addStretch()
    self.page_widgets["home"] = home

    overview, overview_layout = page("What would you like to do?", "")
    self.overview_title = overview_layout.itemAt(0).widget()
    self.overview_summary = overview_layout.itemAt(1).widget()
    actions = QHBoxLayout()
    self.start_backup_button = QPushButton("Back up saves\nCreate a new, verified backup")
    self.start_restore_button = QPushButton("Restore saves\nRecover from an existing backup")
    for button, slot in ((self.start_backup_button, self.start_backup), (self.start_restore_button, self.start_restore)):
        button.setObjectName("actionCard")
        button.setMinimumHeight(135)
        button.clicked.connect(slot)
        actions.addWidget(button)
    overview_layout.addLayout(actions)
    self.last_backup = text("", "muted")
    overview_layout.addWidget(self.last_backup)
    overview_layout.addStretch()
    self.page_widgets["overview"] = overview

    backup, backup_layout = page("Back up your saves", "Check your save folder and backup destination, then create a backup.")
    summary = panel()
    summary_layout = QVBoxLayout(summary)
    summary_layout.setContentsMargins(18, 14, 18, 14)
    self.backup_summary = text("", "section")
    self.backup_destination = text("", "muted")
    summary_layout.addWidget(self.backup_summary)
    summary_layout.addWidget(self.backup_destination)
    self.folder_toggle = QToolButton()
    self.folder_toggle.setObjectName("logToggle")
    self.folder_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    self.folder_toggle.setCheckable(True)
    self.folder_toggle.toggled.connect(self.set_folder_details)
    summary_layout.addWidget(self.folder_toggle)
    backup_layout.addWidget(summary)

    self.setup_panel = panel()
    grid = QGridLayout(self.setup_panel)
    grid.setContentsMargins(16, 12, 16, 12)
    grid.setHorizontalSpacing(10)
    grid.setVerticalSpacing(8)
    self.source_hint = text("", "muted")
    grid.addWidget(self.source_hint, 0, 0, 1, 4)
    self.rpcs3_exe_label = QLabel("RPCS3 application")
    self.rpcs3_exe = QLineEdit(settings.get("rpcs3_executable", ""))
    self.rpcs3_exe.setReadOnly(True)
    self.rpcs3_exe.setPlaceholderText("Choose rpcs3.exe to find your save folders")
    self.locate_rpcs3_button = QPushButton("Locate RPCS3…")
    self.locate_rpcs3_button.clicked.connect(self.locate_rpcs3)
    grid.addWidget(self.rpcs3_exe_label, 1, 0)
    grid.addWidget(self.rpcs3_exe, 1, 1, 1, 2)
    grid.addWidget(self.locate_rpcs3_button, 1, 3)
    self.rpcs3_user_label = QLabel("RPCS3 user")
    self.rpcs3_users = AeroComboBox()
    self.rpcs3_users.addItem("Locate RPCS3 to discover users", None)
    self.rpcs3_users.currentIndexChanged.connect(self.select_rpcs3_user)
    grid.addWidget(self.rpcs3_user_label, 2, 0)
    grid.addWidget(self.rpcs3_users, 2, 1, 1, 3)
    self.rpcs3_widgets = [self.rpcs3_exe_label, self.rpcs3_exe, self.locate_rpcs3_button,
                          self.rpcs3_user_label, self.rpcs3_users]
    self.source = QLineEdit(self.sources[self.mode])
    self.source_button = QPushButton("Browse…")
    self.source_button.clicked.connect(self.choose_source)
    self.detect_button = QPushButton("Find saves")
    self.detect_button.clicked.connect(self.detect_source)
    self.source_label = QLabel()
    grid.addWidget(self.source_label, 3, 0)
    grid.addWidget(self.source, 3, 1)
    grid.addWidget(self.source_button, 3, 2)
    grid.addWidget(self.detect_button, 3, 3)
    self.library = QLineEdit(settings.get("library", ""))
    self.library.setPlaceholderText("Choose where to store your backups")
    self.library_button = QPushButton("Choose folder…")
    self.library_button.clicked.connect(self.choose_library)
    grid.addWidget(QLabel("Backup destination"), 4, 0)
    grid.addWidget(self.library, 4, 1)
    grid.addWidget(self.library_button, 4, 2, 1, 2)
    self.library_status = text("", "muted")
    grid.addWidget(self.library_status, 5, 1, 1, 3)
    grid.setColumnStretch(1, 1)
    backup_layout.addWidget(self.setup_panel)
    confirmation = panel()
    confirmation_layout = QVBoxLayout(confirmation)
    confirmation_layout.setContentsMargins(16, 12, 16, 12)
    self.closed = AeroCheckBox()
    self.closed.setMinimumHeight(28)
    self.closed.toggled.connect(self.confirmation_changed)
    confirmation_layout.addWidget(self.closed)
    self.confirmation_hint = text("", "requiredHint")
    self.confirmation_hint.hide()
    confirmation_layout.addWidget(self.confirmation_hint)
    backup_layout.addWidget(confirmation)
    self.backup_button = QPushButton("Back up now")
    self.backup_button.setObjectName("primary")
    self.backup_button.setMinimumHeight(36)
    self.backup_button.clicked.connect(self.prepare_backup)
    self.backup_result = text("", "section")
    backup_layout.addWidget(self.backup_result)
    backup_complete = QHBoxLayout()
    self.open_backup_button = QPushButton("Open Backup Directory")
    self.open_backup_button.clicked.connect(lambda: self.open_result_directory("backup"))
    self.backup_menu_button = QPushButton("Main Menu")
    self.backup_menu_button.clicked.connect(lambda: self.show_page("home"))
    for button in (self.open_backup_button, self.backup_menu_button):
        button.hide()
        backup_complete.addWidget(button)
    backup_complete.addStretch()
    backup_layout.addLayout(backup_complete)
    backup_layout.addStretch()
    self.page_widgets["backup"] = backup

    history, history_layout = page("Choose a backup to restore", "Step 1 of 2 · Select a backup for this emulator.")
    library_row = QHBoxLayout()
    self.restore_library_summary = text("Choose the folder containing your backups.", "muted")
    self.restore_library_button = QPushButton("Choose backup folder…")
    self.restore_library_button.clicked.connect(self.choose_library)
    library_row.addWidget(self.restore_library_summary, 1)
    library_row.addWidget(self.restore_library_button)
    history_layout.addLayout(library_row)
    self.table = QTableWidget(0, 4)
    self.table.setHorizontalHeaderLabels(["Created · local time", "Save collection", "Size", "Status"])
    self.table.setAlternatingRowColors(True)
    self.table.setShowGrid(False)
    self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    self.table.verticalHeader().hide()
    self.table.verticalHeader().setDefaultSectionSize(36)
    self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    self.table.itemSelectionChanged.connect(self.update_actions)
    self.table.setMinimumHeight(170)
    history_layout.addWidget(self.table, 1)
    self.empty = text("Choose a backup folder to load its backups.", "muted")
    history_layout.addWidget(self.empty)
    history_actions = QHBoxLayout()
    self.refresh_button = QPushButton("Refresh")
    self.refresh_button.clicked.connect(self.refresh)
    self.restore_next_button = QPushButton("Continue to destination →")
    self.restore_next_button.setObjectName("primary")
    self.restore_next_button.clicked.connect(self.show_restore_target)
    history_actions.addWidget(self.refresh_button)
    history_actions.addStretch()
    history_layout.addLayout(history_actions)
    self.page_widgets["restore_list"] = history

    destination, destination_layout = page("Where should we recover your saves?", "Step 2 of 2 · Recover to a new folder, or choose this computer's current emulator save folder.")
    self.restore_step_title = destination_layout.itemAt(0).widget()
    self.restore_step_description = destination_layout.itemAt(1).widget()
    self.restore_review = text("", "section")
    destination_layout.addWidget(self.restore_review)
    self.restore_destination_mode = AeroComboBox()
    self.restore_destination_mode.addItem("Recover to a new folder", "new")
    self.restore_destination_mode.addItem("Restore to the emulator's current save folder", "current")
    self.restore_destination_mode.currentIndexChanged.connect(self.restore_destination_changed)
    destination_layout.addWidget(self.restore_destination_mode)
    destination_panel = panel()
    self.new_restore_panel = destination_panel
    destination_grid = QGridLayout(destination_panel)
    destination_grid.setContentsMargins(18, 16, 18, 16)
    self.restore_parent = QLineEdit()
    self.restore_parent.setPlaceholderText("Choose a parent folder for the recovered saves")
    self.restore_parent_button = QPushButton("Choose folder…")
    self.restore_parent_button.clicked.connect(self.choose_restore_parent)
    self.restore_name = QLineEdit("PCSX2-Restored")
    destination_grid.addWidget(QLabel("Parent folder"), 0, 0)
    destination_grid.addWidget(self.restore_parent, 0, 1)
    destination_grid.addWidget(self.restore_parent_button, 0, 2)
    destination_grid.addWidget(QLabel("New folder name"), 1, 0)
    destination_grid.addWidget(self.restore_name, 1, 1, 1, 2)
    self.restore_target_preview = text("", "muted")
    destination_grid.addWidget(self.restore_target_preview, 2, 1, 1, 2)
    destination_grid.setColumnStretch(1, 1)
    destination_layout.addWidget(destination_panel)
    self.current_restore_panel = panel()
    current = QGridLayout(self.current_restore_panel)
    current.setContentsMargins(18, 16, 18, 16)
    self.current_restore_path = QLineEdit()
    self.current_restore_path.setReadOnly(True)
    self.current_restore_path.setPlaceholderText("Find or select the actual save folder used on this computer")
    self.current_restore_path.textChanged.connect(self.current_restore_path_changed)
    self.current_restore_browse = QPushButton("Choose save folder…")
    self.current_restore_browse.clicked.connect(self.choose_current_restore_folder)
    self.current_restore_detect = QPushButton("Find current folder")
    self.current_restore_detect.clicked.connect(self.find_current_restore_folder)
    current.addWidget(text("Current save folder"), 0, 0)
    current.addWidget(self.current_restore_path, 1, 0, 1, 2)
    current.addWidget(self.current_restore_browse, 2, 0)
    current.addWidget(self.current_restore_detect, 2, 1)
    self.current_restore_users = AeroComboBox()
    self.current_restore_users.addItem("Choose an RPCS3 user", None)
    self.current_restore_users.currentIndexChanged.connect(self.select_current_restore_user)
    current.addWidget(self.current_restore_users, 3, 0, 1, 2)
    self.current_restore_warning = text("Existing saves in this folder will be replaced. MemCard keeps the previous folder beside it so you can recover it if needed. Confirm this is the current installation's save folder.", "requiredHint")
    current.addWidget(self.current_restore_warning, 4, 0, 1, 2)
    self.current_restore_closed = AeroCheckBox("The emulator is closed and I confirmed this save folder.")
    self.current_restore_closed.setMinimumHeight(28)
    self.current_restore_closed.toggled.connect(self.current_restore_confirmation_changed)
    current.addWidget(self.current_restore_closed, 5, 0, 1, 2)
    destination_layout.addWidget(self.current_restore_panel)
    self.current_restore_panel.hide()
    self.restore_info = text("MemCard will check the backup, copy it, and verify the recovered files before making the new folder available.", "muted")
    destination_layout.addWidget(self.restore_info)
    self.restore_button = QPushButton("Review and restore")
    self.restore_button.setObjectName("primary")
    self.restore_button.setMinimumHeight(36)
    self.restore_button.clicked.connect(self.restore_selected)
    self.restore_result = text("", "section")
    destination_layout.addWidget(self.restore_result)
    restore_complete = QHBoxLayout()
    self.open_restore_button = QPushButton("Open Restored Directory")
    self.open_restore_button.clicked.connect(lambda: self.open_result_directory("restore"))
    self.restore_menu_button = QPushButton("Main Menu")
    self.restore_menu_button.clicked.connect(lambda: self.show_page("home"))
    for button in (self.open_restore_button, self.restore_menu_button):
        button.hide()
        restore_complete.addWidget(button)
    restore_complete.addStretch()
    destination_layout.addLayout(restore_complete)
    destination_layout.addStretch()
    self.page_widgets["restore_target"] = destination
    for widget in self.page_widgets.values():
        self.pages.addWidget(widget)
