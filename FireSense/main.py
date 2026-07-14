"""
main.py — FireSense entry point
"""

import sys
import os

# Resolve base dir — handles both normal run and PyInstaller .exe
if getattr(sys, "frozen", False):
    _BASE = sys._MEIPASS          # extracted temp folder inside the .exe
    _HERE = _BASE
else:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _BASE = _HERE

_AF_DIR = os.path.join(_BASE, "FireSenseCli")
for p in [_HERE, _AF_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

ASSETS = os.path.join(_HERE, "assets")
LOGO   = os.path.join(ASSETS, "logo_transparent.png")
ICON   = os.path.join(ASSETS, "icon.ico")
if not os.path.exists(LOGO):
    LOGO = os.path.join(ASSETS, "logo.png")
if not os.path.exists(ICON):
    ICON = LOGO

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui     import QIcon
from PyQt6.QtCore    import Qt, QTimer
from ui.main_window  import FireSenseWindow, SplashScreen


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FireSense")
    app.setOrganizationName("FireRL")
    app.setWindowIcon(QIcon(ICON))

    try:
        app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    except Exception:
        pass

    # ── Startup splash (centered logo + italic tagline) ─────────────────────
    splash = SplashScreen(LOGO)
    splash.center_on_screen()
    splash.show()
    app.processEvents()

    window = FireSenseWindow(logo_path=LOGO)
    window.setWindowIcon(QIcon(ICON))

    def _reveal():
        window.show()
        window.raise_(); window.activateWindow()
        splash.close()

    # brief minimum splash time so the tagline reads as intentional, not a flash
    QTimer.singleShot(1100, _reveal)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
