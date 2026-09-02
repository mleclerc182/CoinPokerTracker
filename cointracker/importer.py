from __future__ import annotations

from pathlib import Path
from typing import Callable

from .database import TrackerDB
from .parser import ParseError, iter_hand_texts, parse_hand


# current hand, total hands, current filename
ProgressCallback = Callable[[int, int, str], None]


def count_file_hands(path: str | Path) -> int:
    """Count CoinPoker hand headers without loading the file into memory."""
    path = Path(path)
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("CoinPoker Hand #"):
                count += 1
    return count


def import_file(
    db: TrackerDB,
    path: str | Path,
    hero_name: str = "Hero",
    progress: ProgressCallback | None = None,
    *,
    total_hands: int | None = None,
    progress_offset: int = 0,
) -> tuple[int, int, list[str]]:
    path = Path(path)
    errors: list[str] = []
    added = duplicates = 0
    batch = []

    owns_total = total_hands is None
    if total_hands is None:
        total_hands = count_file_hands(path)
    total_hands = max(0, int(total_hands))
    if progress:
        progress(progress_offset, total_hands, path.name)

    with path.open("r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    processed = 0
    for processed, block in enumerate(iter_hand_texts(text, require_complete=True), start=1):
        try:
            batch.append(parse_hand(block, hero_name=hero_name))
        except ParseError as e:
            first = block.splitlines()[0] if block else "Unknown hand"
            errors.append(f"{first}: {e}")

        # Commit in chunks so large imports remain reasonably memory efficient.
        if len(batch) >= 500:
            a, d = db.import_hands(batch)
            added += a
            duplicates += d
            batch.clear()

        if progress:
            progress(progress_offset + processed, total_hands, path.name)

    if batch:
        a, d = db.import_hands(batch)
        added += a
        duplicates += d

    # Header counting is intentionally cheap and streaming. In the unusual case
    # of a truncated final hand, keep the UI total honest once parsing finishes.
    actual_total = progress_offset + processed
    if progress and owns_total and actual_total != total_hands:
        progress(actual_total, actual_total, path.name)

    return added, duplicates, errors


def import_folder(
    db: TrackerDB,
    folder: str | Path,
    hero_name: str = "Hero",
    progress: ProgressCallback | None = None,
) -> tuple[int, int, list[str]]:
    folder = Path(folder)
    paths = sorted(folder.rglob("*.txt"))
    counts = [(path, count_file_hands(path)) for path in paths]
    total_hands = sum(count for _, count in counts)

    total_added = total_dup = 0
    errors: list[str] = []
    processed = 0
    if progress:
        progress(0, total_hands, paths[0].name if paths else folder.name)

    for path, count in counts:
        a, d, e = import_file(
            db,
            path,
            hero_name=hero_name,
            progress=progress,
            total_hands=total_hands,
            progress_offset=processed,
        )
        total_added += a
        total_dup += d
        errors.extend([f"{path.name}: {x}" for x in e])
        processed += count

    if progress and total_hands == 0:
        progress(0, 0, folder.name)
    return total_added, total_dup, errors
