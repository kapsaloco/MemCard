"""Aero-inspired palettes and a painted glass banner; no web or image assets."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QCheckBox, QFrame

from .assets import APP_LOGO


PALETTES = {
    "light": {"background": "#e9f3fa", "text": "#19384e", "muted": "#506c7f",
              "panel": "#fafdff", "panel_end": "#e4f0f8", "border": "#aac8dc",
              "field": "#ffffff", "alternate": "#f0f7fc", "button": "#ffffff",
              "button_end": "#d8e9f5", "hover": "#e2f6ff", "selected": "#ccecff",
              "accent": "#086da1", "disabled": "#7b8e9c", "console": "#f6fbff",
              "hero_top": "#f7fdff", "hero_bottom": "#a5d5ee", "hero_text": "#124e73"},
    "dark": {"background": "#142b3e", "text": "#e0edf8", "muted": "#a7bfd1",
             "panel": "#29475d", "panel_end": "#1d354a", "border": "#50738c",
             "field": "#142c3e", "alternate": "#1b364a", "button": "#42637b",
             "button_end": "#29465d", "hover": "#3e708d", "selected": "#285f81",
             "accent": "#85d7ff", "disabled": "#7f98aa", "console": "#102636",
             "hero_top": "#315e7e", "hero_bottom": "#183b58", "hero_text": "#edfaff"},
}


def palette(theme):
    colors = PALETTES[theme]
    result = QPalette()
    for role, color in ((QPalette.ColorRole.Window, "background"), (QPalette.ColorRole.WindowText, "text"),
                        (QPalette.ColorRole.Base, "field"), (QPalette.ColorRole.AlternateBase, "alternate"),
                        (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "panel"),
                        (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.Highlight, "selected"),
                        (QPalette.ColorRole.HighlightedText, "text"), (QPalette.ColorRole.ToolTipBase, "panel"),
                        (QPalette.ColorRole.ToolTipText, "text"), (QPalette.ColorRole.Link, "accent")):
        result.setColor(role, QColor(colors[color]))
    result.setColor(QPalette.ColorRole.PlaceholderText, QColor(colors["muted"]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        result.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["disabled"]))
    return result


def stylesheet(theme):
    c = PALETTES[theme]
    return f"""
    QWidget {{ color: {c['text']}; font-family: 'Segoe UI'; font-size: 13px; }}
    QMainWindow, QScrollArea, QWidget#shell {{ background: {c['background']}; }}
    QScrollArea > QWidget > QWidget {{ background: {c['background']}; }}
    QDialog, QMessageBox {{ background: {c['background']}; }}
    QLabel {{ background: transparent; }}
    QLabel#brand {{ color: {c['hero_text']}; font-size: 32px; font-weight: 600; }}
    QLabel#heroSubtitle {{ color: {c['hero_text']}; font-size: 13px; }}
    QLabel#badge {{ background: {c['panel']}; color: {c['accent']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 4px 10px; font-size: 11px; }}
    QLabel#muted {{ color: {c['muted']}; }}
    QLabel#section {{ color: {c['accent']}; font-size: 15px; font-weight: 600; }}
    QLabel#pageTitle {{ color: {c['text']}; font-size: 24px; font-weight: 600; }}
    QPushButton#actionCard {{ font-size: 18px; font-weight: 600; padding: 18px; border-radius: 10px; min-height: 80px; }}
    QToolButton#emulatorCard {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {c['panel']},stop:1 {c['panel_end']}); border: 1px solid {c['border']}; border-radius: 12px; color: {c['text']}; font-size: 19px; font-weight: 600; padding: 22px; }}
    QToolButton#emulatorCard:hover, QToolButton#emulatorCard:focus {{ background: {c['hover']}; border: 2px solid {c['accent']}; padding: 21px; }}
    QLabel#requiredHint {{ color: {'#8c4a00' if theme == 'light' else '#ffd58a'}; padding: 3px 0; }}
    QToolButton#logToggle {{ color: {c['accent']}; background: transparent; border: 0; padding: 3px; font-weight: 600; text-align: left; }}
    QToolButton#logToggle:hover {{ background: {c['selected']}; border-radius: 4px; }}
    QFrame#panel {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {c['panel']},stop:1 {c['panel_end']}); border: 1px solid {c['border']}; border-radius: 9px; }}
    QLineEdit, QComboBox, QPlainTextEdit, QTableWidget {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 4px; padding: 6px; selection-background-color: {c['selected']}; selection-color: {c['text']}; }}
    QFrame#panel QLineEdit, QFrame#panel QComboBox {{ background: {c['field']}; }}
    QLineEdit:focus, QComboBox:focus {{ border: 1px solid {c['accent']}; }}
    QLineEdit:read-only {{ color: {c['muted']}; }}
    QComboBox {{ min-height: 20px; padding-right: 23px; }}
    QComboBox QAbstractItemView {{ background: {c['field']}; color: {c['text']}; selection-background-color: {c['selected']}; selection-color: {c['text']}; border: 1px solid {c['border']}; outline: 0; padding: 0; }}
    QComboBox QAbstractItemView::item {{ min-height: 24px; border: 0; padding: 3px 7px; }}
    QPushButton {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {c['button']},stop:0.48 {c['panel']},stop:0.5 {c['panel_end']},stop:1 {c['button_end']}); border: 1px solid {c['border']}; border-radius: 5px; padding: 7px 13px; min-height: 18px; }}
    QPushButton:hover {{ background: {c['hover']}; border-color: {c['accent']}; }}
    QPushButton:pressed {{ background: {c['selected']}; }}
    QPushButton#primary {{ color: white; font-weight: 600; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #63b8e6,stop:0.48 #2793c8,stop:0.5 #087ab3,stop:1 #09689e); border: 1px solid #086797; min-height: 25px; }}
    QPushButton#primary:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #8bd8f7,stop:1 #1387c2); }}
    QPushButton:disabled, QPushButton#primary:disabled {{ color: {c['disabled']}; background: {c['panel_end']}; border-color: {c['border']}; }}
    QHeaderView::section {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {c['panel']},stop:1 {c['panel_end']}); color: {c['muted']}; border: 0; border-bottom: 1px solid {c['border']}; padding: 8px; font-weight: 600; }}
    QTableWidget {{ alternate-background-color: {c['alternate']}; gridline-color: {c['border']}; }}
    QTableWidget::item {{ padding: 5px; }}
    QTableWidget::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
    QPlainTextEdit {{ background: {c['console']}; font-family: 'Consolas'; font-size: 12px; }}
    QProgressBar {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 5px; min-height: 14px; max-height: 16px; }}
    QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #b7ed95,stop:0.48 #7dcb57,stop:0.5 #52ab37,stop:1 #86d65d); border-radius: 3px; }}
    QCheckBox {{ spacing: 8px; background: transparent; }}
    QToolTip {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px; }}
    QScrollBar:vertical {{ background: {c['panel_end']}; width: 12px; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 22px; }}
    """


def emulator_icon(mode):
    """Small original console silhouettes, independent of emulator branding assets."""
    pixmap = QPixmap(120, 120)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(25, 10, 90, 110)
    gradient.setColorAt(0, QColor("#4c7190" if mode == "pcsx2" else "#718394"))
    gradient.setColorAt(1, QColor("#101d30"))
    painter.setBrush(gradient)
    painter.setPen(QPen(QColor("#8dbbd8"), 1.5))
    rect = QRectF(30, 8, 60, 104) if mode == "pcsx2" else QRectF(13, 24, 94, 73)
    painter.drawRoundedRect(rect, 3 if mode == "pcsx2" else 17, 3 if mode == "pcsx2" else 17)
    painter.setPen(QPen(QColor("#52caf0"), 3))
    painter.drawLine(42, 79, 78, 79)
    painter.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
    painter.setPen(QColor("#def6ff"))
    painter.drawText(QRectF(20, 29, 80, 42), Qt.AlignmentFlag.AlignCenter, "PS2" if mode == "pcsx2" else "PS3")
    painter.end()
    return QIcon(pixmap)


def appearance_icon(theme):
    """Show the active appearance: sun for light, moon for dark."""
    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if theme == "dark":
        moon = QPainterPath()
        moon.addEllipse(QRectF(4, 3, 21, 21))
        cutout = QPainterPath()
        cutout.addEllipse(QRectF(11, 0, 19, 19))
        painter.fillPath(moon.subtracted(cutout), QColor("#a7d8f6"))
    else:
        painter.setPen(QPen(QColor("#c68b13"), 2))
        painter.setBrush(QColor("#e8b33d"))
        painter.drawEllipse(QRectF(9, 9, 10, 10))
        for x1, y1, x2, y2 in ((14, 1, 14, 5), (14, 23, 14, 27), (1, 14, 5, 14), (23, 14, 27, 14),
                               (5, 5, 8, 8), (20, 20, 23, 23), (5, 23, 8, 20), (20, 8, 23, 5)):
            painter.drawLine(x1, y1, x2, y2)
    painter.end()
    return QIcon(pixmap)


class AeroBanner(QFrame):
    """Paint soft glass reflections and an orb, entirely using Qt."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = "light"
        self.logo = QPixmap(str(APP_LOGO))
        self.setMinimumHeight(100)

    def paintEvent(self, event):
        c = PALETTES[self.theme]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 11, 11)
        painter.setClipPath(clip)
        glass = QLinearGradient(0, 0, 0, self.height())
        glass.setColorAt(0, QColor(c["hero_top"]))
        glass.setColorAt(1, QColor(c["hero_bottom"]))
        painter.fillRect(rect, glass)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 45 if self.theme == "light" else 12))
        painter.drawEllipse(QRectF(self.width() * 0.36, -self.height() * 1.1, self.width() * 0.8, self.height() * 1.8))
        painter.setBrush(QColor(255, 255, 255, 35))
        painter.drawEllipse(QRectF(-self.width() * 0.2, -self.height() * 2.1, self.width() * 1.1, self.height() * 2.65))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(QRectF(20, (self.height() - 66) / 2, 66, 66), self.logo, QRectF(self.logo.rect()))
        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(c["border"]), 1))
        painter.drawRoundedRect(rect, 11, 11)


class AeroCheckBox(QCheckBox):
    """Keep the confirmation indicator visible in both native and offscreen Qt."""
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.property("needsConfirmation"):
            painter.setBrush(QColor(241, 166, 38, 45))
            painter.setPen(QPen(QColor("#d9911d"), 1.5))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8), 4, 4)
        box = QRectF(1, (self.height() - 16) / 2, 16, 16)
        painter.setPen(QPen(QColor("#739bb5"), 1))
        painter.setBrush(QColor("#147fb5") if self.isChecked() else self.palette().base())
        painter.drawRoundedRect(box, 3, 3)
        if self.isChecked():
            tick = QPainterPath()
            tick.moveTo(box.x() + 3, box.y() + 8)
            tick.lineTo(box.x() + 7, box.y() + 12)
            tick.lineTo(box.x() + 13, box.y() + 4)
            painter.setPen(QPen(QColor("white"), 2))
            painter.drawPath(tick)
        painter.setPen(self.palette().windowText().color())
        painter.drawText(self.rect().adjusted(25, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self.palette().link().color(), 1, Qt.PenStyle.DotLine))
            painter.drawRect(self.rect().adjusted(0, 1, -1, -2))
