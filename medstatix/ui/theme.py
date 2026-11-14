"""Modern Qt stylesheet (light / dark)."""

PALETTES = {
    "light": dict(bg="#F5F7FB", panel="#FFFFFF", text="#1D2433", sub="#5B6B82", border="#DCE3EE", accent="#0B6BCB",
                  accent2="#0FA3B1", hover="#E8F1FC", sel="#D3E6FB", side="#0E2A47", sidetext="#DCE8F5", sidesel="#1C4F80"),
    "dark": dict(bg="#11151C", panel="#1A202B", text="#E6EAF2", sub="#9AA7BA", border="#2B3443", accent="#4C9BFF",
                 accent2="#2BC4CF", hover="#232C3A", sel="#24456E", side="#0B1018", sidetext="#C9D5E6", sidesel="#1F3B5E"),
}


def stylesheet(theme="light", rtl=False):
    p = PALETTES.get(theme, PALETTES["light"])
    return f"""
* {{ font-family: 'Segoe UI', 'Tahoma', 'Noto Sans Arabic', Arial; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {p['bg']}; color: {p['text']}; }}
QWidget {{ color: {p['text']}; }}
QToolBar {{ background: {p['panel']}; border: none; border-bottom: 1px solid {p['border']}; padding: 4px; spacing: 4px; }}
QToolButton {{ padding: 6px 10px; border-radius: 8px; color: {p['text']}; }}
QToolButton:hover {{ background: {p['hover']}; }}
QToolButton#primary {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {p['accent']}, stop:1 {p['accent2']}); color: white; font-weight: 600; }}
QMenuBar {{ background: {p['panel']}; color: {p['text']}; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {p['sel']}; }}
QMenu {{ background: {p['panel']}; color: {p['text']}; border: 1px solid {p['border']}; }}
QTreeWidget#nav {{ background: {p['side']}; color: {p['sidetext']}; border: none; font-size: 10pt; padding: 4px; }}
QTreeWidget#nav::item {{ padding: 5px 4px; border-radius: 6px; }}
QTreeWidget#nav::item:selected {{ background: {p['sidesel']}; color: white; }}
QTreeWidget#nav::item:hover {{ background: {p['sidesel']}; }}
QLineEdit#navsearch {{ background: rgba(255,255,255,0.10); color: {p['sidetext']}; border: 1px solid rgba(255,255,255,0.25); border-radius: 8px; padding: 6px; }}
QWidget#sidebar {{ background: {p['side']}; }}
QLabel#brand {{ color: white; font-size: 17pt; font-weight: 700; padding: 10px 8px 0 8px; }}
QLabel#tagline {{ color: {p['sidetext']}; font-size: 8.5pt; padding: 0 8px 8px 8px; }}
QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 10px; background: {p['panel']}; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 8px 18px; margin-right: 2px; color: {p['sub']}; border-bottom: 3px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {p['accent']}; border-bottom: 3px solid {p['accent']}; }}
QTableView {{ background: {p['panel']}; gridline-color: {p['border']}; selection-background-color: {p['sel']}; selection-color: {p['text']};
             alternate-background-color: {p['bg']}; border: none; }}
QHeaderView::section {{ background: {p['bg']}; color: {p['text']}; border: none; border-right: 1px solid {p['border']};
                        border-bottom: 1px solid {p['border']}; padding: 5px; font-weight: 600; }}
QTextBrowser {{ background: {p['panel']}; border: none; }}
QPushButton {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 7px 16px; }}
QPushButton:hover {{ background: {p['hover']}; }}
QPushButton#primary {{ background: {p['accent']}; color: white; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: {p['accent2']}; }}
QPushButton#choice {{ text-align: {'right' if rtl else 'left'}; padding: 12px 16px; font-size: 10.5pt; }}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 6px; padding: 5px; }}
QListWidget {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 6px; }}
QListWidget::item:selected {{ background: {p['sel']}; color: {p['text']}; }}
QGroupBox {{ border: 1px solid {p['border']}; border-radius: 10px; margin-top: 14px; padding: 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {p['accent']}; }}
QStatusBar {{ background: {p['panel']}; color: {p['sub']}; border-top: 1px solid {p['border']}; }}
QLabel#hint {{ color: {p['sub']}; }}
QLabel#h1 {{ font-size: 14pt; font-weight: 700; color: {p['accent']}; }}
QSplitter::handle {{ background: {p['border']}; }}
QScrollBar:vertical {{ width: 10px; background: transparent; }}
QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 5px; min-height: 30px; }}
"""


def output_css(theme="light"):
    from ..report.export import HTML_CSS
    if theme == "dark":
        return HTML_CSS + """
body{color:#E6EAF2;background:#1A202B;} h2{color:#7DB8FF;} h3{color:#A9C8F0;} .subtitle,.note,.tnote,.caption{color:#9AA7BA;}
table.apa th{background:#232C3A;border-color:#ccc;} table.apa caption{color:#A9C8F0;} table.apa tr:last-child td{border-color:#ccc;}
.interpret{background:#1D2C42;} .methods{background:#1C2E22;} .warning{background:#3A2E1A;}"""
    return HTML_CSS
