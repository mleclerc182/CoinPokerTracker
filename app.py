from __future__ import annotations

import sys
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QEventLoop, QStandardPaths, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

STARTUP_PROGRESS_DELAY_MS = 0


def create_migration_progress(app: QApplication):
    """Show database work immediately so startup never appears unresponsive."""
    dialog = QProgressDialog("Updating database fields…\nPlease wait.", "", 0, 0)
    dialog.setWindowTitle("CoinPoker Tracker")
    dialog.setMinimumWidth(380)
    dialog.setWindowModality(Qt.ApplicationModal)
    dialog.setWindowFlag(Qt.WindowCloseButtonHint, False)
    dialog.setCancelButton(None)
    dialog.setMinimumDuration(STARTUP_PROGRESS_DELAY_MS)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    last_refresh = None
    last_message = None

    def update(completed: int, total: int, message: str | None = None):
        nonlocal last_refresh, last_message
        now = monotonic()
        total = max(1, total)
        completed = max(0, min(completed, total))
        finished = completed >= total
        if (
            last_refresh is not None
            and now - last_refresh < 0.05
            and not finished
            and message == last_message
        ):
            return
        last_refresh = now
        last_message = message
        # Always use a determinate range. Qt renders 0/0 as a solid blue
        # busy bar on some platforms, which looks misleadingly complete.
        dialog.setRange(0, total)
        dialog.setValue(completed)
        if message:
            dialog.setLabelText(message)
        elif total > 5:
            dialog.setLabelText(
                "Updating database fields…\n"
                f"Processed {completed:,} of {total:,} stored hands."
            )
        else:
            dialog.setLabelText(
                "Updating database fields…\n"
                "Checking and repairing stored statistics."
            )
        if not finished:
            dialog.show()
        app.processEvents(QEventLoop.ExcludeUserInputEvents)

    return dialog, update


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

    progress_dialog, update_progress = create_migration_progress(app)
    # Show before opening SQLite. Database connection, schema checks, and
    # regression detection all happen before their own progress callbacks.
    update_progress(
        0,
        5,
        "Starting CoinPoker Tracker…\nPreparing to open the database.",
    )
    try:
        # Import after the startup window exists. A partially updated source
        # tree can otherwise fail here before Qt has anything visible.
        from cointracker.ui import MainWindow

        w = MainWindow(
            str(db_path),
            migration_progress=update_progress,
        )
        w.setWindowIcon(
            QIcon(str(resource_path("assets/coinpoker_tracker.png")))
        )
        w.show()
        update_progress(5, 5, "CoinPoker Tracker is ready.")
    except Exception as exc:
        progress_dialog.close()
        QMessageBox.critical(
            None,
            "CoinPoker Tracker could not start",
            "The tracker could not open or update its database.\n\n"
            "Close any older CoinPoker Tracker window and try again.\n\n"
            f"{type(exc).__name__}: {exc}",
        )
        return 1

    # Show the main window before closing the startup window.
    progress_dialog.close()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
