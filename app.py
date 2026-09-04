from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from cointracker.ui import MainWindow


def resource_path(relative_path: str) -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller --onedir puts bundled data under _internal
        return Path(sys.executable).resolve().parent / "_internal" / relative_path

    return Path(__file__).resolve().parent / relative_path


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("CoinPoker Tracker")

    app.setWindowIcon(
        QIcon(str(resource_path("assets/coinpoker_tracker.png")))
    )

    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "coinpoker_tracker.sqlite3"

    w = MainWindow(
        str(db_path),
    )
    w.setWindowIcon(
        QIcon(str(resource_path("assets/coinpoker_tracker.png")))
    )
    w.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
