# Emerge remaining time

A simple, interactive TUI (Terminal User Interface) script written in Python for Gentoo Linux to track ongoing and remaining package compilations using `emerge` and `qlop`.

## Features
- Real-time tracking of the currently compiling package and its ETA.
- List of remaining packages with individual average times and total ETA.
- Fully navigable interface using arrow pages, PgUp/PgDown, Home/End.

## Requirements
- Python 3
- Gentoo Linux (with `qlop` and `portage` tools available)

## Usage
```bash
python3 ert.py
```

## License
This project is licensed under the MIT License - see the LICENSE file for details.
