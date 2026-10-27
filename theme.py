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
QCheckBox { spacing: 7px; background: transparent; }
QCheckBox::indicator { width: 15px; height: 15px; background: #ffffff; border: 1px solid #98a9bd; border-radius: 3px; }
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
QFrame#Panel { background: #ffffff; border: 1px solid #d6dfe9; border-radius: 8px; }
"""
THEME = THEME.replace('__CHECK_ICON__', (Path(__file__).parent/'assets/check.svg').as_posix().replace("'", "\\'"))
