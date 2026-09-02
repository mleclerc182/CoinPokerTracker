from cointracker.database import TrackerDB
from cointracker.importer import count_file_hands, import_file, import_folder


def _hand_text(hand_id: str, minute: int) -> str:
    return f"""CoinPoker Hand #{hand_id}: NLH (₮0.01/₮0.02) 2026/08/27 07:{minute:02d}:00 EDT
Table '200588' 2-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Villain (₮2 in chips)
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [As Kd]
Hero: raises ₮0.05 to ₮0.06
Villain: folds
Hero: RETURN ₮0.04
*** SHOWDOWN ***
Hero collected ₮0.04 from pot
*** SUMMARY ***
Total pot ₮0.04 | Rake ₮0
Hand was run once
Board [  ]
Game ended: 2026/08/27 07:{minute:02d}:10 EDT
"""


def test_import_file_reports_hand_progress(tmp_path):
    hh = tmp_path / "day.txt"
    hh.write_text(_hand_text("920001", 0) + "\n\n" + _hand_text("920002", 1), encoding="utf-8")
    assert count_file_hands(hh) == 2

    seen = []
    db = TrackerDB(tmp_path / "tracker.sqlite3")
    try:
        assert import_file(db, hh, progress=lambda current, total, name: seen.append((current, total, name)))[:2] == (2, 0)
    finally:
        db.close()

    assert (1, 2, "day.txt") in seen
    assert seen[-1] == (2, 2, "day.txt")


def test_folder_progress_is_cumulative_across_files(tmp_path):
    folder = tmp_path / "histories"
    folder.mkdir()
    (folder / "a.txt").write_text(_hand_text("930001", 0), encoding="utf-8")
    (folder / "b.txt").write_text(_hand_text("930002", 1), encoding="utf-8")

    seen = []
    db = TrackerDB(tmp_path / "tracker.sqlite3")
    try:
        assert import_folder(db, folder, progress=lambda current, total, name: seen.append((current, total, name)))[:2] == (2, 0)
    finally:
        db.close()

    assert any(current == 1 and total == 2 and name == "a.txt" for current, total, name in seen)
    assert any(current == 2 and total == 2 and name == "b.txt" for current, total, name in seen)
    assert all(total == 2 for current, total, name in seen if total)
