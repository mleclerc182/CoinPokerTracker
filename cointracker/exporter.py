from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, Iterable

from .database import TrackerDB


class ExportCancelled(Exception):
    """Raised when a hand-history export is cancelled by the user."""


def _cancelled(check: Callable[[], bool] | None) -> bool:
    return bool(check is not None and check())


def _ordered_rows_for_ids(db: TrackerDB, hand_ids: Iterable[str]):
    """Return database rows in the same order as the requested hand IDs."""
    ordered_ids = list(dict.fromkeys(str(hand_id) for hand_id in hand_ids))
    if not ordered_ids:
        return []

    rows = db.hands_by_ids(ordered_ids, limit=-1)
    by_id = {
        str(row["hand_id"]): row
        for row in rows
    }
    return [
        by_id[hand_id]
        for hand_id in ordered_ids
        if hand_id in by_id
    ]


def _matching_rows(
    db: TrackerDB,
    *,
    filters: dict | None,
    hand_ids: Iterable[str] | None,
):
    if hand_ids is not None:
        return _ordered_rows_for_ids(db, hand_ids)

    return db.hands(
        dict(filters) if filters is not None else {},
        limit=-1,
    )


def export_hands(
    db_path: str,
    target: str,
    *,
    filters: dict | None = None,
    hand_ids: Iterable[str] | None = None,
    progress: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> int:
    """Export stored original hand histories to one text file.

    ``hand_ids`` takes precedence over ``filters``. When neither is supplied,
    every stored hand is exported.

    The destination is replaced only after a complete successful export, so a
    cancellation or error cannot leave a partial hand-history file behind.
    """
    if filters is not None and hand_ids is not None:
        raise ValueError("Pass either filters or hand_ids, not both.")

    target_path = Path(target).expanduser()
    parent = target_path.parent
    if not parent.exists():
        raise FileNotFoundError(f"Export folder does not exist: {parent}")

    db = TrackerDB(db_path)
    temp_path: Path | None = None

    try:
        if _cancelled(is_cancelled):
            raise ExportCancelled()

        rows = _matching_rows(
            db,
            filters=filters,
            hand_ids=hand_ids,
        )
        total = len(rows)

        if progress is not None:
            progress(0, total)

        # The UI explicitly treats a zero-count export as "no file written".
        if total == 0:
            return 0

        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            dir=str(parent),
        )
        temp_path = Path(temp_name)

        exported = 0
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            for row in rows:
                if _cancelled(is_cancelled):
                    raise ExportCancelled()

                hand_id = str(row["hand_id"])
                raw = db.raw_hand(hand_id)
                if raw is None:
                    raise RuntimeError(
                        f"Stored hand {hand_id} has no original hand history."
                    )

                text = str(raw).rstrip("\r\n")
                output.write(text)
                output.write("\n\n")
                exported += 1

                if progress is not None:
                    progress(exported, total)

            output.flush()
            os.fsync(output.fileno())

        if _cancelled(is_cancelled):
            raise ExportCancelled()

        os.replace(temp_path, target_path)
        temp_path = None
        return exported

    finally:
        db.close()
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
