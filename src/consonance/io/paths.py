"""Where Consonance keeps its files."""

import os
from pathlib import Path

from platformdirs import user_data_path


def data_dir() -> Path:
    """Return the per-user data folder, honouring ``CONSONANCE_DATA_DIR``."""
    override = os.environ.get("CONSONANCE_DATA_DIR")
    path = Path(override) if override else user_data_path("Consonance", appauthor=False)
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    """Return the practice database file."""
    return data_dir() / "practice.sqlite3"


def custom_songs_dir() -> Path:
    """Return the folder that keeps copies of imported MIDI files."""
    path = data_dir() / "songs" / "custom"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    """Return the diagnostic log file."""
    return data_dir() / "consonance.log"
