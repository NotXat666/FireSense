"""
styles.py — FireSense dark theme with orange accent (matches the logo).

A cohesive design system: layered dark surfaces, a single orange brand accent,
consistent spacing/radii, and clear interactive states (hover / pressed / focus).
"""

# ── Palette ───────────────────────────────────────────────────────────────────
BG0     = "#14151a"   # main content background
BG1     = "#0e0f13"   # sidebar / header (deepest)
BG2     = "#101218"   # log panel / insets
CARD    = "#1b1d24"   # card surface
CARD2   = "#23262f"   # elevated / input surface
CARD_HI = "#272b35"   # hover surface
BORDER  = "#2a2e39"   # default border
BORDER2 = "#363b47"   # lighter border / focus companion
TEXT    = "#eceef2"   # primary text
MUTED   = "#8b93a3"   # secondary text
FAINT   = "#5a6172"   # tertiary / disabled

ORANGE     = "#E8622A"   # brand accent (logo family)
ORANGE_HI  = "#FF7A3D"   # hover
ORANGE_DIM = "#b8481c"   # pressed
AMBER      = "#F5A623"
GREEN      = "#2ecc71"
BLUE       = "#4a9eeb"
RED        = "#e74c3c"
PURPLE     = "#a56cd6"   # guard events

# Per-action colors
ACTION_COLORS = {
    "maintain":  BLUE,
    "block_ip":  ORANGE,
    "tighten":   AMBER,
    "rollback":  GREEN,
}
Q_COLORS = [BLUE, ORANGE, AMBER, GREEN]        # Q0..Q3
Q_NAMES  = ["Q₀ maintain", "Q₁ block_ip", "Q₂ tighten", "Q₃ rollback"]

# status → color
STATUS_COLORS = {"ok": GREEN, "warn": AMBER, "error": RED,
                 "running": ORANGE, "idle": FAINT}


DARK_THEME = f"""
/* ── Global ──────────────────────────────────────────────────
   Only the window paints the base color. Generic child QWidgets stay
   TRANSPARENT so they never paint a dark box over a card/header — named
   surfaces (#sidebar, #card, inputs…) opt back in to a solid background. */
QMainWindow {{ background-color: {BG0}; }}
QWidget {{
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QLabel, QCheckBox {{ background: transparent; }}
QToolTip {{ background-color: {CARD2}; color: {TEXT}; border: 1px solid {BORDER2};
            border-radius: 6px; padding: 5px 9px; font-size: 12px; }}

/* ── Sidebar ──────────────────────────────────────────────── */
#sidebar {{
    background-color: {BG1};
    border-right: 1px solid {BORDER};
    min-width: 224px; max-width: 224px;
}}
#app_title {{ color: #ffffff; font-size: 21px; font-weight: 800;
              letter-spacing: 0.5px; }}
#app_subtitle {{ color: {ORANGE}; font-size: 10px; font-weight: 700;
                 letter-spacing: 3px; }}

#sidebar_nav QPushButton {{
    background-color: transparent; color: {MUTED}; border: none;
    border-radius: 9px; text-align: left; padding: 11px 16px;
    margin: 2px 12px; font-size: 13px; font-weight: 500;
}}
#sidebar_nav QPushButton:hover {{ background-color: {CARD}; color: {TEXT}; }}
#sidebar_nav QPushButton[active="true"] {{
    background-color: rgba(232,98,42,0.14);
    color: {ORANGE_HI};
    border-left: 3px solid {ORANGE};
    border-top-left-radius: 0; border-bottom-left-radius: 0;
    margin-left: 0; padding-left: 25px; font-weight: 700;
}}

#legend_title {{ color: {FAINT}; font-size: 10px; font-weight: 700;
                  letter-spacing: 1.5px; padding-bottom: 2px; }}
#legend_item  {{ color: {MUTED}; font-size: 11.5px; }}

/* ── Header bar ─────────────────────────────────────────── */
#header_bar {{
    background-color: {BG1};
    border-bottom: 1px solid {BORDER};
    min-height: 62px; max-height: 62px;
}}
#section_title {{ color: #ffffff; font-size: 18px; font-weight: 700;
                  letter-spacing: 0.2px; }}
#section_sub   {{ color: {MUTED}; font-size: 12px; }}

/* ── Cards ──────────────────────────────────────────────── */
#card {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
#card_title {{ color: {MUTED}; font-size: 10px; font-weight: 700;
               letter-spacing: 1.5px; }}
#card_value {{ color: #ffffff; font-size: 27px; font-weight: 800; }}
#card_hint  {{ color: {FAINT}; font-size: 11px; }}
#card_icon  {{ font-size: 15px; }}

/* ── Empty-state placeholder ─────────────────────────────── */
#empty_state {{ color: {FAINT}; font-size: 13px; padding: 26px; }}

/* ── Status pills ────────────────────────────────────────── */
#status_running {{ background-color: rgba(232,98,42,0.15); color: {ORANGE_HI};
    border: 1px solid {ORANGE}; border-radius: 14px; padding: 6px 15px;
    font-size: 12px; font-weight: 700; }}
#status_stopped {{ background-color: rgba(90,97,114,0.12); color: {MUTED};
    border: 1px solid {FAINT}; border-radius: 14px; padding: 6px 15px;
    font-size: 12px; font-weight: 700; }}
#status_connecting {{ background-color: rgba(245,166,35,0.13); color: {AMBER};
    border: 1px solid {AMBER}; border-radius: 14px; padding: 6px 15px;
    font-size: 12px; font-weight: 700; }}

/* ── Buttons ────────────────────────────────────────────── */
#btn_primary {{
    background-color: {ORANGE}; color: #ffffff; border: none;
    border-radius: 9px; padding: 10px 24px; font-size: 13px; font-weight: 700;
}}
#btn_primary:hover {{ background-color: {ORANGE_HI}; }}
#btn_primary:pressed {{ background-color: {ORANGE_DIM}; }}
#btn_primary:disabled {{ background-color: #33363f; color: #6b7280; }}

#btn_ghost {{
    background-color: transparent; color: {ORANGE_HI};
    border: 1px solid {ORANGE}; border-radius: 9px;
    padding: 10px 22px; font-size: 13px; font-weight: 700;
}}
#btn_ghost:hover {{ background-color: rgba(232,98,42,0.12); }}
#btn_ghost:pressed {{ background-color: rgba(232,98,42,0.20); }}
#btn_ghost:disabled {{ color: {FAINT}; border-color: #33363f; }}

#btn_stop {{
    background-color: transparent; color: {MUTED};
    border: 1px solid {BORDER2}; border-radius: 9px;
    padding: 10px 22px; font-size: 13px; font-weight: 700;
}}
#btn_stop:hover {{ background-color: rgba(231,76,60,0.12); color: {RED}; border-color: {RED}; }}
#btn_stop:pressed {{ background-color: rgba(231,76,60,0.22); }}
#btn_stop:disabled {{ color: {FAINT}; border-color: #33363f; }}

#btn_clear {{
    background-color: transparent; color: {MUTED};
    border: 1px solid {BORDER}; border-radius: 7px;
    padding: 6px 14px; font-size: 12px;
}}
#btn_clear:hover {{ background-color: {CARD2}; color: {TEXT}; }}

/* ── Inputs ─────────────────────────────────────────────── */
QLineEdit, QSpinBox {{
    background-color: {CARD2}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 8px;
    padding: 9px 12px; font-size: 13px; selection-background-color: {ORANGE};
    selection-color: #ffffff;
}}
QLineEdit:hover, QSpinBox:hover {{ border: 1px solid {BORDER2}; }}
QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {ORANGE}; background-color: {BG2}; }}
QLineEdit::placeholder {{ color: {FAINT}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 18px; border: none;
    background: {CARD_HI}; }}
QSpinBox::up-button {{ border-top-right-radius: 8px; }}
QSpinBox::down-button {{ border-bottom-right-radius: 8px; }}
QSpinBox::up-arrow {{ image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-bottom: 5px solid {MUTED}; }}
QSpinBox::down-arrow {{ image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {MUTED}; }}
#field_label {{ color: {MUTED}; font-size: 11px; font-weight: 600;
                letter-spacing: 0.3px; }}

QCheckBox {{ color: {TEXT}; font-size: 13px; spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {FAINT}; background: {CARD2}; }}
QCheckBox::indicator:checked {{ background: {ORANGE}; border-color: {ORANGE};
    image: none; }}
QCheckBox::indicator:hover {{ border-color: {ORANGE_HI}; }}

/* ── Table ──────────────────────────────────────────────── */
QTableWidget {{
    background-color: {BG2}; alternate-background-color: {CARD};
    border: 1px solid {BORDER}; border-radius: 10px;
    gridline-color: transparent; selection-background-color: rgba(232,98,42,0.28);
    selection-color: #ffffff; outline: none;
}}
QTableWidget::item {{ padding: 7px 10px; border: none; }}
QTableWidget::item:hover {{ background-color: {CARD_HI}; }}
QHeaderView::section {{
    background-color: {BG1}; color: {MUTED}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 9px 10px;
    font-size: 11px; font-weight: 700; letter-spacing: 0.5px;
}}
QTableCornerButton::section {{ background-color: {BG1}; border: none; }}

/* ── Log panel ──────────────────────────────────────────── */
#log_panel {{
    background-color: {BG2}; color: #b6bccb;
    border: 1px solid {BORDER}; border-radius: 10px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px; padding: 12px;
    selection-background-color: {ORANGE}; selection-color: #ffffff;
}}

/* ── Stage row (clickable to toggle) ────────────────────── */
#stage_row {{
    background-color: {CARD2}; border: 1px solid {BORDER};
    border-radius: 10px;
}}
#stage_row:hover {{ background-color: {CARD_HI}; border-color: {BORDER2}; }}
#stage_row[checked="true"] {{
    background-color: rgba(232,98,42,0.10);
    border: 1px solid rgba(232,98,42,0.55);
}}
#stage_row[checked="true"]:hover {{ background-color: rgba(232,98,42,0.16); }}
#stage_name {{ color: {TEXT}; font-size: 13px; font-weight: 700; }}
#stage_desc {{ color: {MUTED}; font-size: 11px; }}
#stage_status {{ font-size: 12px; font-weight: 700; }}

/* ── Info strip (Monitor) ───────────────────────────────── */
#info_strip QLabel {{ font-size: 12px; }}

/* ── Divider / scrollbars ───────────────────────────────── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{ color: {BORDER}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #363b47; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #363b47; border-radius: 5px; min-width: 28px; }}
QScrollBar::handle:horizontal:hover {{ background: {FAINT}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ── Splash ─────────────────────────────────────────────── */
#splash {{ background-color: {BG1}; border: 1px solid {BORDER2}; border-radius: 18px; }}
#splash_title {{ color: #ffffff; font-size: 30px; font-weight: 800; letter-spacing: 1px; }}
#splash_sub {{ color: {ORANGE}; font-size: 12px; font-weight: 700; letter-spacing: 5px; }}
#splash_status {{ color: {MUTED}; font-size: 13px; font-style: italic;
                  letter-spacing: 0.3px; }}
"""
