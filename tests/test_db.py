from pathlib import Path

import pytest

from consonance.core.db import Attempt, AttemptLog


def test_durable_append_only_log(tmp_path: Path) -> None:
    log = AttemptLog(tmp_path / "practice.db")
    session = log.start_session("sight")
    attempt = Attempt(session, "sight", "note:treble:C4", (60,), (60,), True, 1, 900)
    log.append(attempt)
    log.close()
    log = AttemptLog(tmp_path / "practice.db")
    assert log.attempts() == [attempt]
    with pytest.raises(Exception, match="append only"):
        log.connection.execute("DELETE FROM attempt_log")
    log.close()
