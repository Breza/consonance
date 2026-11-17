# Implementation verification

## Practice desk and 90-day overview (2026-11-17)

Built on the 0.2.0 usability pass below, preserving its automatic connection, daily plan,
eight practice modes, on-screen keyboard, games, curriculum, and score rendering.

| Check | Result |
| --- | --- |
| `ruff check` | Passed |
| `mypy --strict src tests` | Passed, 71 files |
| `pytest -q` | 165 passed |

New coverage checks the inclusive 90-calendar-day window, same-day deduplication, gaps,
future dates, local midnight and historical DST, completed versus abandoned answers,
assisted completions, context-sensitive quiet suggestions, comparable reading insights,
saved song section/hands/tempo/loop restoration, a one-click practice start, an optional
short-session stopping point, open curriculum chapters, date rollover, and missing imports.
Existing musical grading, transport, worker, port handling, and notation tests still pass.

Offscreen visual QA inspected first-use, returning, and laptop layouts on isolated sample
profiles at 1200 x 900 and 900 x 900. A regression test also checks 900 x 700. Home has no
horizontal overflow at these sizes. The Practice page now scrolls and wraps mode buttons,
so hidden panels no longer force the entire window beyond the available screen.

A real worker smoke run on a separate test profile exercised Begin, a timestamped answer,
Finish, SQLite persistence, and the resulting single lesson-day count. It opened no MIDI
ports. The previews use sample history; the player's actual practice database was not
modified for testing. Physical piano acceptance testing remains outstanding.

## Usability pass (0.2.0)

Checks ran on Windows 11 with the project's Python 3.14.5 virtual environment; the package declares Python >=3.12 and mypy checks against Python 3.12. **No piano or other MIDI instrument was connected at any point.**

| Check | Result |
| --- | --- |
| `ruff format --check src tests` | Clean |
| `ruff check src tests` | Passed |
| `mypy --strict src tests` | Passed, 68 files |
| `pytest` | 152 passed |

### What the tests cover

Everything listed for the first draft below, plus: five-finger-position fingering and chord fingering; one clef/key/time header per system, beat-to-x mapping, centred whole-measure rests, ledger lines in both clefs, beam direction, accidentals on reading cards; every built-in score (complete measures, no key needed by both hands at once, playable fingerings) and byte-for-byte agreement between the scores and the MIDI files in `songs/demo/`; prompt ordering with and without a random source and the three-prompt retry gap; review-box promotion only when due, exclusion of blameless, assisted and game attempts, and equality of incremental schedule updates with a full replay of 600 randomised attempts; the daily plan for new, returning and capped learners; Key Finder any-octave matching, hints, assisted flags, and abandon rules; Rhythm Sniper preview, any-key tapping, ignored count-in taps, live grading marks and playhead; Technique Lab count-in, pattern layout and evenness results; Ear Trainer reference tone, free replay and answer reveal; both games including personal bests; Wait-mode early notes, one attempt per pass, restart after a finished pass, Tempo-mode resume with a re-anchored count-in, and section identities; tolerant MIDI import; tolerant settings loading; the realtime worker on its own thread against a stand-in port (persistence, lazy session rows, connection errors, wrong-channel detection, a failing output, panic, and a stored game best); and the interface: every screen, mode, curriculum item and song view rendered offscreen, the requests each control sends, typed and clicked note input, shortcuts, the Home plan, settings validation, and port appearance, loss and renumbering. A seeded fuzz test drives the engine with random commands, notes, pedals and reconfigurations (and a simulated player who usually answers correctly) and checks that nothing raises, that every scheduled output note is valid and off the player's channel, and that unfinished timed passes are never logged as misses; a longer run of the same driver, 330 seeds of 1,500 steps, also found nothing.

### What was measured

Measured on the development machine with the worker's output going to an in-memory stand-in rather than a MIDI driver, so these describe scheduling, not the device. "Before" is the first draft's code run through the same script.

| Measurement | Before | After |
| --- | --- | --- |
| Worker tick (`Event.wait(2ms)` versus `time.sleep(2ms)`) | mean 7.8ms, p95 16.3ms | mean 2.0ms, p95 2.7ms |
| Error in the interval between metronome clicks at 120 BPM | mean 4.5ms, worst 12.8ms | mean 0.6–1.0ms, worst 2.4–2.7ms |
| Worker thread CPU, idle in Rhythm Sniper / during a round | 27% / 15% of a core | 2–6% / 4–5% |
| Whole application CPU, idle on the Practice screen (offscreen) | 17% of a core | 5–8% |
| Time on the MIDI thread to save one answer, 5,000 / 20,000 attempts logged | 211ms / 964ms | about 0.1–0.2ms at either size |

### What was looked at

Every screen was rendered headlessly and inspected as an image, both with Qt's offscreen plugin and with the native Windows font engine: Home for a new learner and for one with history, Settings, and each practice mode in several states (prompt, wrong key with the answer revealed, count-in, mid-round, result, Wait and Tempo song views in split, staff and falling-note layouts). A threaded run with the real worker, real timers and injected key input went through four modes and its database was inspected afterwards. The application's own `main()` start-up and shut-down path was exercised headlessly.

### What was not verified

- Anything involving the physical Roland NUVOLA-GX: USB latency, the sound and patch setup, local-control behaviour, pedal routing, and how the piano responds to exit and panic messages.
- Automatic connection and hot-plug handling against real Windows MIDI drivers. The logic is tested with simulated port lists only; real port names, and how long Windows takes to list ports with the piano attached, were not observed.
- The interface on a real display with a person using it: the renders are static images, and nothing was judged by ear.
- An independent second-reader review of the core was started but did not complete, so the core has been checked by its author, the tests and the fuzzer only.
- The starter fingerings are generated by a rule (fewest and most comfortable hand shifts between five-finger positions). They are checked to be playable hand positions, not to be what a teacher would choose.

The 2ms worker interval is a scheduling target, not a Windows hard-real-time guarantee.

## First draft (0.1.0)

The implementation followed the four requested gates. Each gate passed before work began on the next slice.

| Gate | Ruff | Strict mypy | pytest |
| --- | --- | --- | --- |
| Slice 1: notation, input, event log, Sight-Reader | Passed | Passed, 19 files | 9 passed |
| Slice 2: worker, ledger, rhythm, technique, ear | Passed | Passed, 28 files | 21 passed |
| Slice 3: transport, built-ins, importer, Song Studio | Passed | Passed, 37 files | 28 passed |
| Slice 4 and final regression pass: curriculum, scheduling, dashboard, UI | Passed | Passed, 46 files | 47 passed |

The tests covered MIDI normalization, damper and soft-pedal edges, repeated notes under damper, fresh strikes and allowed held notes, rolled chords, wrong pitches, spelling and accidental cancellation, layout, ledger cleanup, shared attack windows and duration tolerance, evenness, ear probes, every built-in measure's exact duration and hand overlap, piecewise tempo, Wait pauses, natural wall-clock note expiry, held left-hand notes across checkpoints, MIDI-resolution-independent clustering, importer validation, integrated tempo ramps, scheduling, mastery, local practice dates, retry ordering, and all-screen offscreen instantiation. All of these remain in the suite. Run unmodified against the 0.2.0 code, 46 of the 47 original tests pass; the one that does not asserts that there are six built-in pieces, and there are now twelve.

Physical Roland NUVOLA-GX testing was unavailable then as now.
