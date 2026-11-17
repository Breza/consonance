from consonance.core.song import AutoRamp


def test_three_clean_passes_raise_tempo_and_reset() -> None:
    """Verify three clean passes raise tempo and reset."""
    ramp = AutoRamp(True)
    assert ramp.complete_pass(0.95, 0.7, tempo_mode=True) == 0.7
    assert ramp.complete_pass(0.99, 0.7, tempo_mode=True) == 0.7
    assert ramp.complete_pass(0.95, 0.7, tempo_mode=True) == 0.75
    assert ramp.streak == 0
    ramp.complete_pass(1, 0.95, tempo_mode=True)
    ramp.complete_pass(1, 0.95, tempo_mode=True)
    assert ramp.complete_pass(1, 0.95, tempo_mode=True) == 1
    ramp.complete_pass(1, 0.7, tempo_mode=True)
    assert ramp.complete_pass(0.94, 0.7, tempo_mode=True) == 0.7
    assert ramp.streak == 0
    ramp.complete_pass(1, 0.7, tempo_mode=False)
    assert ramp.streak == 0
