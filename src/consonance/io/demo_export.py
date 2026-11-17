"""Write every built-in score to ``songs/demo`` as a Standard MIDI File.

Run ``python -m consonance.io.demo_export`` from the repository root after changing a score,
so the checked-in MIDI files stay identical to the notation.
"""

import sys
from pathlib import Path

from consonance.core.builtin_scores import ALL_SCORES
from consonance.io.smf import export_midi


def export_all(folder: Path) -> list[Path]:
    """Export each built-in score into ``folder`` and return the files written."""
    written = []
    for score in ALL_SCORES:
        path = folder / f"{score.song_id}.mid"
        export_midi(score.compile(), path)
        written.append(path)
    return written


def main() -> int:
    """Export into the folder given on the command line, or ``songs/demo``."""
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("songs") / "demo"
    for path in export_all(folder):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
