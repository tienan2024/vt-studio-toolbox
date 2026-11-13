"""Shared native-widget visual language for the VT Studio toolbox."""
from pathlib import Path
THEME = """
QMainWindow, QWidget { background: #f5f6f8; color: #263548; font-size: 13px; }
QLabel { background: transparent; }
QLabel#Title { font-size: 21px; font-weight: 600; color: #1d2e43; }
QLabel#PageTitle { font-size: 23px; font-weight: 650; color: #1b2e45; }
QLabel#Subtle { color: #58687b; font-size: 12px; }
QLabel#Message { padding: 10px 12px; background: #e8eef4; color: #30465e; border-radius: 6px; }
QLabel#Message[error="true"] { background: #fff0e7; color: #8e3e19; }
QPushButton { background: #ffffff; border: 1px solid #c8d1dd; padding: 7px 12px; border-radius: 6px; min-height: 20px; }
QPushButton:hover { background: #edf1f6; border-color: #8da0b8; }
QPushButton:pressed { background: #e1e7ef; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 2px solid #b5531c; }
QPushButton:disabled { color: #8b96a4; background: #edf0f4; border-color: #d6dce5; }
QPushButton#Primary { background: #b5531c; color: #ffffff; border-color: #b5531c; font-weight: 600; }
QPushButton#Primary:hover { background: #984215; border-color: #984215; }
QPushButton#Primary:disabled { background: #c5a58f; border-color: #c5a58f; color: #ffffff; }
QPushButton#CanvasTool { padding: 7px 9px; background: #ffffff; border: 1px solid #d1dae5; }
QPushButton#CanvasTool:checked { background: #fff0e4; color: #8d3d16; border-color: #b5531c; font-weight: 600; }
QGroupBox { font-weight: 600; border: 0; border-top: 1px solid #d8dfe8; margin-top: 16px; padding-top: 16px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding-right: 9px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #ffffff; border: 1px solid #c8d1dd; padding: 5px; border-radius: 5px; min-height: 22px; selection-background-color: #f1d8c8; selection-color: #41250f; }
QSpinBox:disabled, QDoubleSpinBox:disabled { background: #e8ecf1; color: #8a96a3; border-color: #d5dde6; }
QListWidget { background: #ffffff; border: 1px solid #d1dae5; border-radius: 7px; padding: 5px; outline: none; }
QListWidget::item { padding: 9px 7px; border-radius: 4px; }
QListWidget::item:hover { background: #f1f4f8; }
QListWidget::item:selected { background: #fff0e4; color: #78360e; }
QTabWidget::pane { border: 1px solid #d1dae5; border-radius: 5px; }
QTabBar::tab { padding: 10px 14px; background: #e9edf3; border: 0; margin-right: 3px; }
QTabBar::tab:selected { background: #ffffff; color: #a44714; font-weight: 600; }
QCheckBox { spacing: 8px; background: transparent; padding: 0; margin: 0; }
QCheckBox::indicator { width: 16px; height: 16px; background: #ffffff; border: 1px solid #98a9bd; border-radius: 1px; }
QCheckBox::indicator:checked { background: #b5531c; border-color: #b5531c; image: url('__CHECK_ICON__'); }
QCheckBox::indicator:disabled { background: #e7ebf0; border-color: #b9c3d0; }
QProgressBar { background: #e1e7ef; border: 0; border-radius: 3px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #b5531c; border-radius: 3px; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #edf0f5; width: 10px; margin: 1px; }
QScrollBar::handle:vertical { background: #b9c3d0; min-height: 26px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: #ffffff; color: #263548; border: 1px solid #b7c5d4; padding: 7px; }
QPlainTextEdit { background: #1c2735; color: #d3dce8; border: none; border-radius: 5px; padding: 8px; }
QWidget#Sidebar { background: #172332; }
QWidget#Sidebar QLabel { color: #c1cfde; }
QWidget#Sidebar QLabel#Brand { color: #ffffff; font-size: 20px; font-weight: 650; }
QWidget#Sidebar QLabel#BrandMark { background: #b5531c; color: #ffffff; font-size: 16px; font-weight: 650; border-radius: 8px; }
QWidget#Sidebar QPushButton { background: transparent; color: #d1dbe8; border: none; border-radius: 6px; text-align: left; padding: 12px; }
QWidget#Sidebar QPushButton:hover { background: #25374c; color: #ffffff; }
QWidget#Sidebar QPushButton:checked { background: #354257; color: #ffffff; font-weight: 600; }
QWidget#Sidebar QPushButton:focus { border: 1px solid #e5aa7d; }
QWidget#Header { border-bottom: 1px solid #dae1e9; }
QLabel#Offline { color: #416852; background: #e8efe9; border-radius: 5px; padding: 6px 10px; font-size: 12px; }
QLabel#Rule { background: #fff2e7; color: #88400f; border-radius: 5px; padding: 9px; }
QTableWidget#ScriptTable { background: #ffffff; alternate-background-color: #f0f3f7; color: #263548; gridline-color: #d8dfe8; border: 1px solid #c8d1dd; selection-background-color: #fff0e4; selection-color: #78360e; }
QTableWidget#ScriptTable::item { background: transparent; padding: 3px; }
QTableWidget#ScriptTable::item:selected { background: #fff0e4; color: #78360e; }
QTableWidget#ScriptTable QHeaderView::section { background: #e9edf3; color: #30465e; border: 0; border-bottom: 1px solid #c8d1dd; padding: 5px; }
QPlainTextEdit#ScriptLabels { background: #ffffff; color: #263548; border: 1px solid #c8d1dd; padding: 6px; }
QPlainTextEdit#ScriptLabels:disabled { background: #e8ecf1; color: #8a96a3; }
QFrame#Panel { background: #ffffff; border: 1px solid #d6dfe9; border-radius: 8px; }
"""
THEME = THEME.replace('__CHECK_ICON__', (Path(__file__).parent/'assets/check.svg').as_posix().replace("'", "\\'"))

# Scoped controls: retain the toolbox palette without inheriting Windows' arrows.
CAMERA_CONTROLS = """
QWidget#CameraPage QComboBox, QWidget#CameraPage QSpinBox, QWidget#CameraPage QDoubleSpinBox, QWidget#CameraPage QLineEdit {
    background: #ffffff; border: 1px solid #c8d1dd; border-radius: 7px;
    padding: 6px 11px; min-height: 0; selection-background-color: #f1d8c8; selection-color: #41250f;
}
QWidget#CameraPage QComboBox { padding-right: 35px; }
QWidget#CameraPage QSpinBox, QWidget#CameraPage QDoubleSpinBox { padding-right: 66px; }
QWidget#CameraPage QComboBox:hover, QWidget#CameraPage QSpinBox:hover, QWidget#CameraPage QDoubleSpinBox:hover, QWidget#CameraPage QLineEdit:hover { border-color: #8da0b8; }
QWidget#CameraPage QComboBox:focus, QWidget#CameraPage QSpinBox:focus, QWidget#CameraPage QDoubleSpinBox:focus, QWidget#CameraPage QLineEdit:focus { border: 1px solid #b5531c; }
QWidget#CameraPage QComboBox:disabled, QWidget#CameraPage QSpinBox:disabled, QWidget#CameraPage QDoubleSpinBox:disabled, QWidget#CameraPage QLineEdit:disabled { background: #edf0f4; color: #7a8797; border-color: #d6dce5; }
QWidget#CameraPage QAbstractSpinBox QLineEdit, QWidget#CameraPage QComboBox QLineEdit { background: transparent; border: 0; padding: 0; min-height: 0; }
QWidget#CameraPage QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: top right; width: 34px; border: 0; background: transparent; }
QWidget#CameraPage QComboBox::down-arrow { image: url('__CHEVRON__'); width: 16px; height: 16px; }
QWidget#CameraPage QSpinBox::up-button, QWidget#CameraPage QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right; width: 29px; height: 34px;
    border: 0; border-left: 1px solid #e0e5ec; border-top-right-radius: 7px; border-bottom-right-radius: 7px; background: #f8f9fb;
}
QWidget#CameraPage QSpinBox::down-button, QWidget#CameraPage QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: top right; right: 30px; width: 29px; height: 34px;
    border: 0; border-left: 1px solid #e0e5ec; background: #f8f9fb;
}
QWidget#CameraPage QSpinBox::up-arrow, QWidget#CameraPage QDoubleSpinBox::up-arrow { image: url('__PLUS__'); width: 14px; height: 14px; }
QWidget#CameraPage QSpinBox::down-arrow, QWidget#CameraPage QDoubleSpinBox::down-arrow { image: url('__MINUS__'); width: 14px; height: 14px; }
QWidget#CameraPage QSpinBox::up-button:hover, QWidget#CameraPage QDoubleSpinBox::up-button:hover,
QWidget#CameraPage QSpinBox::down-button:hover, QWidget#CameraPage QDoubleSpinBox::down-button:hover { background: #e8eef4; }
QWidget#CameraPage QSpinBox::up-button:pressed, QWidget#CameraPage QDoubleSpinBox::up-button:pressed,
QWidget#CameraPage QSpinBox::down-button:pressed, QWidget#CameraPage QDoubleSpinBox::down-button:pressed { background: #f1d8c8; }
QWidget#CameraPage QPushButton:checked { background: #fff0e4; color: #78360e; border-color: #b5531c; }
QWidget#CameraPage QPushButton::menu-indicator { image: url('__CHEVRON__'); subcontrol-position: right center; subcontrol-origin: padding; width: 14px; height: 14px; right: 5px; }
QWidget#CameraPage QMenu { background: #ffffff; color: #263548; border: 1px solid #c8d1dd; border-radius: 7px; padding: 5px; }
QWidget#CameraPage QMenu::item { padding: 8px 18px; border-radius: 4px; }
QWidget#CameraPage QMenu::item:selected { background: #fff0e4; color: #78360e; }
"""
for _token,_asset in [('__CHEVRON__','chevron-down.svg'),('__PLUS__','plus.svg'),('__MINUS__','minus.svg')]:
    CAMERA_CONTROLS=CAMERA_CONTROLS.replace(_token,(Path(__file__).parent/'assets'/_asset).as_posix().replace("'","\\'"))

CAMERA_POPUP = """
QListView { background: #ffffff; color: #263548; border: 1px solid #c8d1dd; border-radius: 7px; padding: 5px; outline: 0; }
QListView::item { min-height: 32px; padding: 6px 10px; border-radius: 0; border-bottom: 1px solid #e2e7ed; }
QListView::item:hover { background: #edf1f6; }
QListView::item:selected { background: #fff0e4; color: #78360e; }
"""

# One visual language for all four tools, including controls created in tables.
SHARED_CONTROLS=CAMERA_CONTROLS.replace('QWidget#CameraPage ','')
SHARED_CONTROLS+='''
QSpinBox[vtCompact="true"], QDoubleSpinBox[vtCompact="true"] { padding: 3px 42px 3px 7px; }
QSpinBox[vtCompact="true"]::up-button, QDoubleSpinBox[vtCompact="true"]::up-button { width: 19px; height: 26px; }
QSpinBox[vtCompact="true"]::down-button, QDoubleSpinBox[vtCompact="true"]::down-button { right: 20px; width: 19px; height: 26px; }
QLineEdit[vtCompact="true"], QComboBox[vtCompact="true"] { padding-top: 3px; padding-bottom: 3px; }
QSpinBox[vtNoButtons="true"], QDoubleSpinBox[vtNoButtons="true"] { padding-left: 11px; padding-right: 11px; }
QScrollBar:horizontal { background: #edf0f5; height: 9px; margin: 1px; }
QScrollBar::handle:horizontal { background: #b9c3d0; min-width: 26px; border-radius: 4px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
'''
SHARED_POPUP=CAMERA_POPUP
THEME+='\n'+SHARED_CONTROLS
