from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QPushButton, QWidget


# Mirrors docs/ui-desgin/_ds/.../tokens.  Keep this QSS deliberately flat: the
# Steady Health system relies on whitespace and borders rather than decoration.
_ASSETS_DIRECTORY = Path(__file__).with_name("assets")
_BUNDLED_UI_FONT = _ASSETS_DIRECTORY / "fonts" / "NotoSansSC-VF.ttf"
_BUNDLED_NUMERIC_FONT = _BUNDLED_UI_FONT
_REGISTERED_FONT_FAMILIES: tuple[str, str] | None = None
_WEIGHT_AXIS = QFont.Tag.fromString("wght")


def bundled_font_paths() -> tuple[Path, Path]:
    """Return the font resources that must travel with every desktop build."""

    return _BUNDLED_UI_FONT, _BUNDLED_NUMERIC_FONT


def _register_bundled_fonts() -> tuple[str, str]:
    """Register shipped fonts instead of relying on a Windows font fallback."""

    global _REGISTERED_FONT_FAMILIES
    if _REGISTERED_FONT_FAMILIES is not None:
        return _REGISTERED_FONT_FAMILIES

    registered: list[str] = []
    for font_path in dict.fromkeys(bundled_font_paths()):
        if not font_path.is_file():
            raise RuntimeError(f"Required application font is missing: {font_path.name}")
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if font_id < 0 or not families:
            raise RuntimeError(f"Could not register application font: {font_path.name}")
        registered.append(families[0])

    _REGISTERED_FONT_FAMILIES = (registered[0], registered[-1])
    return _REGISTERED_FONT_FAMILIES


def _font(family: str) -> QFont:
    font = QFont(family)
    return _configure_variable_font(font)


def _configure_variable_font(font: QFont) -> QFont:
    """Apply Qt's resolved CSS weight to the variable font's ``wght`` axis."""

    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    font.setVariableAxis(_WEIGHT_AXIS, float(font.weight()))
    return font


STEADY_HEALTH_STYLESHEET = """
QWidget {
    color: #0F172A;
    font-family: "Noto Sans SC";
    font-size: 16px;
}
QMainWindow, QWidget#appSurface, QWidget#pageCanvas {
    background: #F8FAFC;
}
QFrame#appHeader, QFrame#wizardHeader, QFrame#screeningHeader,
QFrame#reportHeader, QFrame#reportMetaBar {
    background: #FFFFFF;
    border: 0;
}
QFrame#appHeader, QFrame#wizardHeader, QFrame#screeningHeader, QFrame#reportHeader {
    border-bottom: 1px solid #E2E8F0;
}
QFrame#appHeader { min-height: 64px; max-height: 64px; }
QFrame#wizardHeader { min-height: 56px; max-height: 56px; }
QFrame#screeningHeader, QFrame#reportHeader { min-height: 56px; max-height: 56px; }
QLabel#organizationName { color: #475569; font-size: 16px; }
QLabel#brandDivider { background: #E2E8F0; min-width: 1px; max-width: 1px; min-height: 20px; }
QWidget#appNavigation QPushButton {
    background: transparent;
    border: 0;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    color: #475569;
    font-size: 16px;
    min-height: 62px;
    padding: 0 0;
}
QWidget#appNavigation QPushButton:hover { color: #2569BC; }
QWidget#appNavigation QPushButton[activeNavigation="true"] {
    color: #2569BC;
    border-bottom-color: #2569BC;
    font-weight: 600;
}
QFrame#deviceStatusBadge, QFrame#syncStatusBadge, QFrame[statusPill="true"] {
    background: #EBF7F0;
    border: 1px solid #BFE5D0;
    border-radius: 16px;
    color: #187A4D;
    min-height: 28px;
    max-height: 28px;
    border-radius: 14px;
}
QFrame[statusPillTone="info"] { background: #EFF5FC; border-color: #B7D3F2; color: #2569BC; }
QFrame[statusPillTone="warning"] { background: #FDF6E6; border-color: #F2DFAE; color: #96600D; }
QFrame[statusPillTone="danger"] { background: #FCEFEF; border-color: #F0C6C6; color: #C23B3B; }
QFrame[statusPillTone="neutral"] { background: #F1F5F9; border-color: #E2E8F0; color: #475569; }
QFrame#deviceStatusBadge QLabel, QFrame#syncStatusBadge QLabel, QFrame[statusPill="true"] QLabel { font-size: 14px; color: inherit; }
QFrame[statusDot="true"] { background: #187A4D; border: 0; border-radius: 4px; min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px; }
QFrame[statusDotTone="info"] { background: #2569BC; }
QFrame[statusDotTone="warning"] { background: #96600D; }
QFrame[statusDotTone="danger"] { background: #C23B3B; }
QLabel#pageTitle { color: #0F172A; font-size: 28px; font-weight: 600; }
QLabel#sectionTitle, QLabel#screeningTitle, QLabel#reportPreviewTitle {
    color: #0F172A;
    font-size: 20px;
    font-weight: 600;
}
QLabel#pageSubtitle, QLabel[secondaryText="true"] { color: #475569; font-size: 16px; }
QLabel[fieldLabel="true"], QLabel#fieldLabel {
    color: #0F172A;
    font-size: 14px;
    font-weight: 600;
}
QLabel[mutedText="true"] { color: #94A3B8; font-size: 14px; }
QLabel[eyebrow="true"] { color: #2569BC; font-size: 14px; font-weight: 600; }
QFrame#contentCard, QFrame#recentScreeningsCard, QFrame#reportPreview,
QFrame#checklistCard, QFrame#matchCard, QFrame#resultCard, QFrame#supportCard,
QFrame#reportPaper, QFrame#footPlacementGuide {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
}
QFrame#matchCard { background: #EFF5FC; border-color: #B7D3F2; }
QFrame#footPlacementGuide { background: #F6FAFD; border-color: #DCE7F2; }
QLineEdit, QComboBox {
    background: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    color: #0F172A;
    min-height: 46px;
    padding: 0 12px;
}
QLineEdit:focus, QComboBox:focus, QCheckBox:focus {
    border: 2px solid #2569BC;
}
QLineEdit::placeholder { color: #94A3B8; }
QComboBox::drop-down { border: 0; width: 28px; }
QLineEdit#recordSearchInput, QComboBox#recordStatusFilter,
QComboBox#recordDateFilter, QPushButton#recordSearchButton {
    min-height: 44px;
    max-height: 44px;
}
QTableWidget {
    background: #FFFFFF;
    alternate-background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    color: #0F172A;
    selection-background-color: #EFF5FC;
    selection-color: #0F172A;
}
QTableWidget::item { padding: 0 16px; border: 0; border-bottom: 1px solid #E2E8F0; }
QHeaderView::section {
    background: #FFFFFF;
    border: 0;
    border-bottom: 1px solid #E2E8F0;
    color: #475569;
    font-size: 14px;
    font-weight: 600;
    min-height: 44px;
    padding: 0 16px;
}
QPushButton {
    background: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    color: #0F172A;
    font-size: 16px;
    min-height: 46px;
    padding: 0 20px;
}
QPushButton:hover { background: #F8FAFC; }
QPushButton:focus { border: 2px solid #2569BC; }
QPushButton[importance="primary"] {
    background: #2569BC;
    border-color: #2569BC;
    color: #FFFFFF;
    font-weight: 600;
    min-height: 54px;
}
QPushButton[importance="primary"]:hover { background: #1D549A; border-color: #1D549A; }
QPushButton[importance="ghost"] { background: transparent; border-color: transparent; color: #2569BC; padding-left: 8px; padding-right: 8px; }
QPushButton[importance="ghost"]:hover { background: #EFF5FC; }
QPushButton[importance="danger"] { background: #C23B3B; border-color: #C23B3B; color: #FFFFFF; font-weight: 600; }
QPushButton[profileChip="true"] {
    background: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 20px;
    color: #334155;
    font-size: 14px;
    font-weight: 500;
    min-height: 40px;
    max-height: 40px;
    padding: 0 16px;
}
QPushButton[profileChip="true"]:hover {
    background: #F8FAFC;
    border-color: #94A3B8;
}
QPushButton[profileChip="true"]:checked {
    background: #EFF5FC;
    border: 1px solid #2569BC;
    color: #1D549A;
    font-weight: 600;
}
QPushButton[profileChip="true"]:focus {
    border: 2px solid #2569BC;
}
QPushButton#STOP_SCREENING { background: #FFFFFF; border-color: #F0C6C6; color: #C23B3B; }
QPushButton#STOP_SCREENING:hover { background: #FCEFEF; }
QPushButton#START_NEW_SCREENING {
    min-width: 220px; max-width: 220px;
    min-height: 64px; max-height: 64px;
    border-radius: 8px;
    font-size: 18px;
    font-weight: 600;
}
QLabel#noticeBanner { background: #EFF5FC; border: 1px solid #B7D3F2; border-radius: 8px; color: #2569BC; padding: 12px 16px; }
QLabel#errorBanner { background: #FCEFEF; border: 1px solid #F0C6C6; border-radius: 8px; color: #C23B3B; padding: 12px 16px; }
QFrame#wizardStepBar {
    background: #FFFFFF;
    border: 0;
    border-bottom: 1px solid #E2E8F0;
}
QFrame[stepCircle="true"] { background: #F1F5F9; border: 0; border-radius: 12px; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; }
QFrame[stepCircle="true"][stepActive="true"] { background: #2569BC; }
QFrame[stepCircle="true"][stepDone="true"] { background: #EBF7F0; border: 1px solid #BFE5D0; }
QFrame[stepCircle="true"] QLabel { color: #94A3B8; font-size: 14px; font-weight: 600; }
QFrame[stepCircle="true"][stepActive="true"] QLabel { color: #FFFFFF; }
QLabel[stepLabel="true"] { color: #94A3B8; font-size: 14px; }
QLabel[stepLabel="true"][stepActive="true"] { color: #0F172A; font-weight: 600; }
QLabel[stepLabel="true"][stepDone="true"] { color: #475569; }
QFrame[stepLine="true"] { background: #E2E8F0; min-height: 1px; max-height: 1px; }
QFrame[stepLine="true"][stepDone="true"] { background: #BFE5D0; }
QFrame[checklistIcon="true"] {
    background: #EBF7F0;
    border: 0;
    border-radius: 12px;
}
QFrame[checklistIcon="true"][checklistTone="danger"] {
    background: #FCEFEF;
}
QFrame#subjectConflictBanner {
    background: #FDF6E6;
    border: 1px solid #F2DFAE;
    border-radius: 8px;
}
QFrame#stopConfirmationOverlay {
    background: rgba(15, 23, 42, 102);
    border: 0;
}
QFrame#stopConfirmationDialog {
    background: #FFFFFF;
    border: 0;
    border-radius: 12px;
}
QCheckBox { color: #0F172A; font-size: 16px; spacing: 12px; }
QCheckBox::indicator { width: 20px; height: 20px; border: 1px solid #CBD5E1; border-radius: 4px; background: #FFFFFF; }
QCheckBox::indicator:checked { background: #2569BC; border-color: #2569BC; }
QProgressBar { background: #F1F5F9; border: 0; border-radius: 4px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #3B8BEF; border-radius: 4px; }
QFrame#reportWorkspace { background: #DBE1E9; border: 0; }
QFrame[wizardFooter="true"] { background: #FFFFFF; border-top: 1px solid #E2E8F0; }
QFrame#reportPaper { background: #FFFFFF; border: 0; border-radius: 0; }
QLabel#reportDocumentTitle { color: #0F172A; font-size: 18px; font-weight: 600; }
QLabel[reportSection="true"] { color: #2569BC; font-size: 14px; font-weight: 600; }
QLabel[numericText="true"] { font-family: "Noto Sans SC"; }
QFrame[reportPlaceholder="true"] { background: #F1F5F9; border: 0; border-radius: 4px; }
"""


def apply_design_system(root: QWidget) -> None:
    """Apply the source Steady Health desktop token system to a Qt widget tree."""
    ui_family, numeric_family = _register_bundled_fonts()
    root.setProperty("uiTheme", "steady-health")
    root.setFont(_font(ui_family))
    root.setStyleSheet(STEADY_HEALTH_STYLESHEET)
    for widget in (root, *root.findChildren(QWidget)):
        font = widget.font()
        if widget.property("numericText"):
            font.setFamily(numeric_family)
        widget.setFont(_configure_variable_font(font))
    for button in root.findChildren(QPushButton):
        if not button.accessibleName():
            button.setAccessibleName(button.text())
        minimum = 48
        if button.property("profileChip"):
            minimum = 40
        elif button.objectName() == "START_NEW_SCREENING":
            minimum = 64
        elif button.property("importance") == "primary":
            minimum = 56
        button.setMinimumHeight(max(button.minimumHeight(), minimum))
