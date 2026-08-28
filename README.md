# CoinPoker Tracker

A simple, lightweight cash-game tracker for **CoinPoker** on Windows.

CoinPoker Tracker imports your local CoinPoker hand-history files and gives you a clean way to review results, basic poker stats, sessions, positions, all-in adjusted results, and profit graphs.

It is intentionally a **simple tracker**, not a full poker analysis suite.

## Download

**[Download the latest Windows release](https://github.com/mleclerc182/CoinPokerTracker/releases/latest)**

Open the latest release and download:

`CoinPokerTracker-Setup.exe`

> **Windows SmartScreen:** The installer may currently show an "unrecognized app" warning because the application is not code-signed. You will need to choose **Run anyway**.

## What it does

CoinPoker Tracker currently provides:

- Import of CoinPoker cash-game hand-history files
- Duplicate-safe hand importing
- Overall winnings and bb/100
- VPIP, PFR, 3-Bet, WWSF, WTSD, and W$SD
- All-in adjusted results
- Splash-pot tracking
- Run-it-twice / multi-run tracking
- Profit graphs
- Session results
- Position results
- Individual hand-history viewing
- Basic date, stakes, Splash, and runout filtering
- Customizable Overview stat cards
- Local SQLite database storage

Your hand histories and tracker database stay on your computer. The tracker does not require your CoinPoker login credentials.

## What it is not

This project is deliberately focused on straightforward results tracking.

It does **not** aim to compete with full-featured commercial poker tracking software and currently does not provide features such as:

- Graphical hand replayers
- HUDs
- Advanced opponent analysis
- Detailed report builders
- Extensive custom filtering
- Range analysis
- Solver integration
- Database synchronization across devices

If you need deep hand analysis or highly configurable reports, this probably is not the right tool. The goal is simply to provide an easy way to track and review CoinPoker cash-game results.

## System requirements

- **64-bit Windows**
- **Windows 10 version 1809 or later**
- **Windows 11**

Windows 7, Windows 8, and Windows 8.1 are not supported.

Python is **not** required when installing the Windows release.

## Basic usage

1. Install CoinPoker Tracker using `CoinPokerTracker-Setup.exe`.
2. Open the application.
3. Use **Import → Import hand-history file** or **Import → Import folder**.
4. Select your CoinPoker hand-history file(s).
5. Review your results from the Overview, Hands, Sessions, and Position tabs.

Previously imported hands are detected automatically, so importing the same history again will not duplicate them.

## Data storage

The tracker stores its local database in your Windows application-data directory.

Uninstalling the application does not intentionally remove your tracker database, so reinstalling or upgrading the application should preserve your imported data.

As with any locally stored data you care about, keeping a backup is recommended.

## Bugs and feature requests

Bug reports and feature requests are welcome through **GitHub Issues**.

When requesting a feature, please keep in mind that the project is intended to remain a relatively simple CoinPoker tracker rather than grow into a full poker analysis platform.

I am **not currently looking to manage outside code contributions or pull requests**. Issues are still very welcome for:

- Bug reports
- Small usability improvements
- Feature ideas that fit the project's scope

## Building from source

The project is written in Python using PySide6.

For a local Windows development build, clone the repository and run:

```bat
build_windows.bat
```

The packaged application will be created under:

```text
dist\CoinPokerTracker\
```

The Windows installer is built with Inno Setup using:

```text
installer\CoinPokerTracker.iss
```

## Disclaimer

CoinPoker Tracker is an independent, unofficial project and is **not affiliated with, endorsed by, or sponsored by CoinPoker**.

Poker involves financial risk. This software is provided as a tracking tool only and does not guarantee the accuracy of third-party hand-history data or future results.
