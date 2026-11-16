import os
from pathlib import Path

from platformdirs import user_data_path


def data_dir() -> Path:
    override = os.environ.get("CONSONANCE_DATA_DIR")
    path = Path(override) if override else user_data_path("Consonance", appauthor=False)
    path.mkdir(parents=True, exist_ok=True)
    return path
