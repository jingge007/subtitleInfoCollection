from __future__ import annotations

PAGE_BG = "#F0F2F5"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F8FAFB"
LINE = "#D1D9E0"
LINE_SOFT = "#E4E9EF"
LINE_HOVER = "#B0BCCA"
TEXT = "#1A1D23"
TEXT_MUTED = "#3D4552"
TEXT_SOFT = "#5A6478"
TEXT_PLACEHOLDER = "#8B95A5"
PRIMARY = "#4F6EF7"
PRIMARY_SOFT = "#EEF1FE"
PRIMARY_DARK = "#3B54D4"
PRIMARY_LIGHT = "#7B92FA"
GREEN = "#10A050"
GREEN_SOFT = "#E8F8EF"
ORANGE = "#D97706"
ORANGE_SOFT = "#FFF8ED"
RED = "#E04040"
RED_SOFT = "#FDEEEE"
LOG_BG = "#0D1117"
LOG_TEXT = "#C9D1D9"
DANGER_BG = "#FEF5F5"
DANGER_BORDER = "#F5B8B8"
DANGER_TEXT = "#991B1B"
DANGER_TEXT_MUTED = "#B91C1C"

GLOBAL_QSS = f"""
QWidget {{
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
}}

QFrame#panel {{
    background: {SURFACE};
    border: 1px solid {LINE_SOFT};
    border-radius: 10px;
}}

QLabel#sectionTitle {{
    font-size: 14px;
    font-weight: 700;
    color: {TEXT};
    padding-bottom: 4px;
}}

QFrame#metricCard {{
    background: {SURFACE};
    border: 1px solid {LINE_SOFT};
    border-radius: 10px;
}}

QLabel#metricValue {{
    font-size: 26px;
    font-weight: 700;
    color: {TEXT};
}}

QLabel#metricLabel {{
    font-size: 12px;
    color: {TEXT_SOFT};
}}

QLabel#badgeGreen {{
    background: {GREEN_SOFT};
    color: {GREEN};
    border-radius: 8px;
    padding: 3px 10px;
    font-size: 12px;
    font-weight: 700;
}}

QLabel#badgeOrange {{
    background: {ORANGE_SOFT};
    color: {ORANGE};
    border-radius: 8px;
    padding: 3px 10px;
    font-size: 12px;
    font-weight: 700;
}}

QLabel#badgeBlue {{
    background: {PRIMARY_SOFT};
    color: {PRIMARY};
    border-radius: 8px;
    padding: 3px 10px;
    font-size: 12px;
    font-weight: 700;
}}

QLabel#badgeRed {{
    background: {RED_SOFT};
    color: {RED};
    border-radius: 8px;
    padding: 3px 10px;
    font-size: 12px;
    font-weight: 700;
}}

QFrame#statusCard {{
    background: {SURFACE_ALT};
    border: 1px solid {LINE_SOFT};
    border-radius: 8px;
}}

QFrame#recordCard {{
    background: {SURFACE};
    border: 1px solid {LINE_SOFT};
    border-radius: 8px;
}}

QTableWidget#dataTable {{
    background: {SURFACE};
    alternate-background-color: {SURFACE_ALT};
    border: 1px solid {LINE_SOFT};
    border-radius: 8px;
    gridline-color: {LINE_SOFT};
    font-size: 13px;
}}

QTableWidget#dataTable::item {{
    padding: 6px 10px;
}}

QTableWidget#dataTable::item:selected {{
    background: {PRIMARY_SOFT};
    color: {PRIMARY_DARK};
}}

QHeaderView::section {{
    background: {SURFACE_ALT};
    color: {TEXT_MUTED};
    font-size: 12px;
    font-weight: 700;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid {LINE_SOFT};
}}

QTextEdit#logArea {{
    background: {LOG_BG};
    color: {LOG_TEXT};
    border: 1px solid #21262D;
    border-radius: 8px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
    padding: 10px;
}}

QFrame#dangerZone {{
    background: {DANGER_BG};
    border: 1px solid {DANGER_BORDER};
    border-radius: 10px;
}}

QFrame#dropArea {{
    background: {SURFACE_ALT};
    border: 2px dashed {LINE};
    border-radius: 12px;
}}

QFrame#dropArea:hover {{
    border-color: {PRIMARY};
    background: {PRIMARY_SOFT};
}}

NavigationInterface {{
    background: {SURFACE_ALT};
    border-right: 1px solid {LINE_SOFT};
}}

NavigationInterface QPushButton {{
    border-radius: 7px;
    padding: 6px 10px;
    margin: 1px 4px;
}}

NavigationInterface QPushButton:hover {{
    background: {LINE_SOFT};
    border-radius: 7px;
}}

NavigationTreePanel QTreeWidgetItem:selected,
NavigationTreePanel QListWidget::item:selected {{
    background: {PRIMARY_SOFT};
    color: {PRIMARY_DARK};
    font-weight: 700;
}}
"""

LOG_STYLE = f"""
QTextEdit {{
    background: {LOG_BG};
    color: {LOG_TEXT};
    border: 1px solid #21262D;
    border-radius: 8px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
    padding: 10px;
}}
"""
