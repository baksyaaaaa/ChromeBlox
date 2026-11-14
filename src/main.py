import sys

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

import config
import shortcuts
from ui import MainWindow


def main():
    config.ensure_dirs()
    uri = next((a for a in sys.argv[1:] if a.lower().startswith(("roblox-player:", "roblox:"))), None)
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)  # needed for the sign-in window
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # we quit ourselves (tray mode while Roblox runs)
    cfg = config.Config()
    shortcuts.first_run(cfg)
    win = MainWindow(cfg, launch_uri=uri)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
