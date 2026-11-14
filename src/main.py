import sys

from PySide6.QtWidgets import QApplication

import config
from ui import MainWindow


def main():
    config.ensure_dirs()
    uri = next((a for a in sys.argv[1:] if a.lower().startswith(("roblox-player:", "roblox:"))), None)
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # we quit ourselves (tray mode while Roblox runs)
    win = MainWindow(config.Config(), launch_uri=uri)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
