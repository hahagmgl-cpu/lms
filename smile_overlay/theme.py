"""컨트롤 패널 다크 테마 (QSS)"""

DARK_QSS = """
QWidget {
    background-color: #1b2026;
    color: #e8eaed;
    font-family: '맑은 고딕', 'Malgun Gothic', 'Segoe UI', sans-serif;
    font-size: 12px;
}
QLabel { background: transparent; }
QLabel#appTitle {
    font-size: 17px; font-weight: bold; color: #6ea8ff;
    background: transparent;
}
QLabel#appSubtitle { color: #8a94a3; font-size: 10px; background: transparent; }
QLabel#statusBar {
    color: #9aa4b2; font-size: 11px;
    background-color: #14181d; border-radius: 5px; padding: 5px 8px;
}
QGroupBox {
    border: 1px solid #333c47; border-radius: 8px;
    margin-top: 12px; padding: 10px 6px 6px 6px; font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px; padding: 0 5px;
    color: #6ea8ff; background-color: #1b2026;
}
QPushButton {
    background-color: #2a323c; border: 1px solid #3d4854;
    border-radius: 6px; padding: 6px 10px; color: #e8eaed;
}
QPushButton:hover { background-color: #33405c; border-color: #5b8def; }
QPushButton:pressed { background-color: #2f5db3; }
QPushButton:checked { background-color: #2f5db3; border-color: #6ea8ff; font-weight: bold; }
QPushButton:disabled { color: #5c6470; background-color: #22272e; }
QPushButton#primaryBtn {
    background-color: #2f5db3; border-color: #4a7ad1; font-weight: bold;
}
QPushButton#primaryBtn:hover { background-color: #3a6cc9; }
QPushButton#dangerBtn:hover { background-color: #8c3038; border-color: #c25058; }
QCheckBox { spacing: 7px; background: transparent; }
QCheckBox::indicator {
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid #4a5561; background: #232a32;
}
QCheckBox::indicator:checked { background-color: #4a7ad1; border-color: #6ea8ff; }
QTabWidget::pane { border: 1px solid #333c47; border-radius: 6px; top: -1px; }
QTabBar::tab {
    background: #232a32; padding: 7px 14px; margin-right: 2px;
    border-top-left-radius: 6px; border-top-right-radius: 6px; color: #aab4c0;
}
QTabBar::tab:selected { background: #2f5db3; color: #ffffff; font-weight: bold; }
QTabBar::tab:hover:!selected { background: #2c3540; }
QSlider::groove:horizontal { height: 5px; background: #333c47; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #4a7ad1; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 14px; margin: -5px 0; background: #6ea8ff;
    border-radius: 7px; border: 1px solid #1b2026;
}
QDoubleSpinBox, QSpinBox, QComboBox, QKeySequenceEdit, QLineEdit {
    background: #232a32; border: 1px solid #3d4854;
    border-radius: 5px; padding: 3px 5px; color: #e8eaed;
    selection-background-color: #2f5db3;
}
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #232a32; border: 1px solid #3d4854;
    selection-background-color: #2f5db3;
}
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #1b2026; width: 9px; border-radius: 4px; }
QScrollBar::handle:vertical { background: #3d4854; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #4a5865; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip {
    background-color: #14181d; color: #d6dbe1;
    border: 1px solid #3d4854; padding: 4px 6px; border-radius: 4px;
}
"""
