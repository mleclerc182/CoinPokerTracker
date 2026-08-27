from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import QApplication, QProgressDialog

from cointracker.ui import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("CoinPoker Tracker")
    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "coinpoker_tracker.sqlite3"

    migration = QProgressDialog("Preparing tracker database…", "", 0, 0)
    migration.setWindowTitle("CoinPoker Tracker — database update")
    migration.setCancelButton(None)
    migration.setWindowModality(Qt.ApplicationModal)
    migration.setMinimumDuration(0)
    migration.setAutoClose(False)
    migration.setAutoReset(False)
    migration.hide()

    def migration_progress(current: int, total: int):
        if not migration.isVisible():
            migration.show()
        if total > 0:
            migration.setRange(0, total)
            migration.setValue(min(current, total))
            migration.setLabelText(
                f"Recalculating existing hands {current:,} / {total:,}…\n"
                "This happens once after an All-in EV calculation update."
            )
        else:
            migration.setRange(0, 0)
            migration.setLabelText("Preparing tracker database…")
        app.processEvents()

    w = MainWindow(str(db_path), migration_progress=migration_progress)
    migration.close()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
