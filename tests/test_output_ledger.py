from consonance.core.midi_output import MidiOutputLedger, OutputNote


def test_routine_cleanup_is_non_destructive() -> None:
    """Verify routine cleanup is non destructive."""
    messages: list[tuple[int, ...]] = []
    ledger = MidiOutputLedger(messages.append)
    ledger.schedule(OutputNote(1, 60, 0.5))
    ledger.schedule(OutputNote(2, 64, 0.5))
    ledger.advance_to(0.995)
    assert not messages
    ledger.advance_to(1)
    ledger.release_computer_notes()
    ledger.advance_to(3)
    assert messages == [(0x91, 60, 80), (0x81, 60, 0)]
    assert all(m[0] & 15 != 0 and m[0] & 0xF0 != 0xB0 for m in messages)


def test_full_panic_and_natural_expiry() -> None:
    """Verify full panic and natural expiry."""
    messages: list[tuple[int, ...]] = []
    ledger = MidiOutputLedger(messages.append)
    ledger.schedule(OutputNote(0, 60, 0.5))
    ledger.advance_to(0)
    ledger.advance_to(0.5)
    assert not ledger.active
    ledger.full_hardware_panic()
    for channel in range(16):
        assert (0xB0 | channel, 123, 0) in messages
        assert (0xB0 | channel, 64, 0) in messages
