# Implementation verification

The implementation followed the four requested gates. Each gate passed before work began on the next slice. Checks ran on Windows with the project's Python 3.14.5 virtual environment; the package declares Python >=3.12 and mypy checks against Python 3.12.

| Gate | Ruff | Strict mypy | pytest |
| --- | --- | --- | --- |
| Slice 1: notation, input, event log, Sight-Reader | Passed | Passed, 19 files | 9 passed |
| Slice 2: worker, ledger, rhythm, technique, ear | Passed | Passed, 28 files | 21 passed |
| Slice 3: transport, built-ins, importer, Song Studio | Passed | Passed, 37 files | 28 passed |
| Slice 4 and final regression pass: curriculum, scheduling, dashboard, UI | Passed | Passed, 46 files | 47 passed |

Final commands:

```powershell
.\.venv\Scripts\python.exe -m ruff check
.\.venv\Scripts\python.exe -m mypy --strict src tests
.\.venv\Scripts\python.exe -m pytest -q
```

The tests cover MIDI normalization, damper and soft-pedal edges, repeated notes under damper, fresh strikes and allowed held notes, rolled chords, wrong pitches, spelling and accidental cancellation, layout, ledger cleanup, shared attack windows and duration tolerance, evenness, ear probes, every built-in measure's exact duration and hand overlap, piecewise tempo, Wait pauses, natural wall-clock note expiry, held left-hand notes across checkpoints, MIDI-resolution-independent clustering, importer validation, integrated tempo ramps, scheduling, mastery, local practice dates, retry ordering, and all-screen offscreen instantiation.

The eight units contain **116 distinct practice items**. All six built-ins were exported from their canonical scores into `songs/demo/`.

Additional manual verification used Qt's Windows offscreen plugin to inspect Home, Song Studio split view, and Rhythm Sniper images. An empty offscreen font database initially produced unreadable ordinary interface text; loading the installed Windows Segoe UI typeface corrected it. All musical notation remains vector paths. A real worker-thread smoke run exercised startup, Play, a timestamped test keypress, a durable SQLite attempt, and orderly shutdown without a MIDI device.

Physical Roland NUVOLA-GX testing was unavailable. USB timing, local sound/patch configuration, physical pedal routing, hot unplug/reconnect behavior, and the piano's response to exit/panic messages need confirmation on the connected instrument. The 2ms worker interval is a scheduling target, not a Windows hard-real-time guarantee.
