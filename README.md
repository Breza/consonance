# Consonance

A local Windows 11 piano-learning application for the 88-key Roland NUVOLA-GX over USB MIDI. The piano makes all sound. Consonance never synthesizes audio or echoes the keys you play.

## Install and run (PowerShell)

Install 64-bit Python 3.12 or newer, then from this directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\consonance.exe
```

You can also run `.\.venv\Scripts\python.exe -m consonance.ui.app`. The project is developed and checked on Windows; it includes no macOS/Linux device adaptations. If your Python version needs to compile `python-rtmidi`, install the Microsoft C++ build tools or use Python 3.12 with a compatible wheel.

## Connect the Roland

1. Connect and power on the piano using its USB MIDI connection. Install the Windows driver appropriate to your hardware if Windows does not expose a MIDI port.
2. Keep **Local Control ON**. Set the physical keyboard's transmit channel to **MIDI Ch 1**.
3. In Consonance, click **Refresh**, choose the piano's MIDI In and MIDI Out ports, then **Connect**. Port names depend on the installed driver.
4. Ensure the piano receives a piano sound on **Ch 2** and GM2 percussion on **Ch 10**. Consonance does not change your local-control or patch settings. Use the piano's volume control.
5. Open **Home**, choose a Free Practice item, then press **Play**. Nothing is locked. All eight units and all six pieces are available immediately.

In Settings, channel numbers are shown as 1–16; internally they are 0–15. Computer piano, keyboard input, and percussion must use distinct channels. Choose **Piano** metronome for short C7/G6 clicks on the computer-piano channel, or **Off**.

Routine Pause, Replay, Seek, loop wrap, and scene changes release only notes Consonance owns. **MIDI Panic** deliberately clears notes and sustain on all channels, including notes you hold. Exit and port disconnect also invoke that full cleanup.

Unplugged development keys are silent: **A S D F G H J K L** are white keys, **W E T Y U O P** are black keys, **Z/X** change octave, and **R** replays. Key auto-repeat is ignored. Click the practice area if a dropdown has keyboard focus.

## Practice

- **Daily Due Queue / Free Practice:** due reviews have a count badge. Choose a review or explore any unit. Practice for two minutes or forty-five; completed attempts commit immediately. Pausing or leaving a drill also records an incomplete attempt if you have started answering. The local practice log shows today's minutes, your streak, the last seven days, and modes touched.
- **Sight-Reader:** grand-staff notes, harmonic and melodic intervals, triads, and changing four-note contours. Note names and landmark guides are optional; guides default on for Unit 1. Untimed rolled chords are accepted whenever all required fresh strikes are physically held together and extra keys are released. Spread feedback is Tight ≤35ms, Clean ≤90ms, or Rolled. Damper sustain never substitutes for physically holding a chord.
- **Technique Lab:** right, left, together, parallel, and contrary five-finger patterns. Settings select a steady tempo or let the first two notes establish the pace. Timing and velocity charts accompany population standard deviations of inter-onset intervals and note velocities. IOI SD ≤18ms is Excellent; ≤35ms is Good.
- **Ear Trainer:** listen to a note, interval, or major/minor triad on the piano and reproduce it. Probing is allowed and counted. R or a rising soft-pedal edge replays without erasing probes or adding a penalty. Mastery still requires a clean first try. Press Play for the next ear prompt.
- **Rhythm Sniper:** two bars after a one-bar count-in, including 4/4 and 3/4 rhythm cells, rests, eighths, dotted notes, and longer holds. Play C4. Attack feedback uses ±35/75/135ms windows. Hold scoring includes damper sustain, with tolerance max(120ms, 30% of the expected duration). The round reports rush/drag mean and jitter.
- **Song Studio:** select a piece, hands, Wait/Tempo mode, and 25–125% tempo, then **Load selection** and **Play**. Built-ins offer scrolling staff, falling notes, or split view. Wait Mode freezes accompaniment at each checkpoint and permits earlier notes whose notation still spans that beat. Already-sounding accompaniment releases on wall time. Select A/B measure numbers, enable looping, and optionally Auto-Ramp: three consecutive Tempo passes at ≥95% accuracy add five percentage points, capped at 100%.

The six short teaching arrangements are Landmark Anchor Waltz, Stepping Stones, Au Clair de la Lune (opening strain), Ode to Joy (opening theme), Scarborough Fair, and Country Dance with Drone Fifths. The three named traditional/classical melodies are public-domain arrangements; the others are original. Their score structures are the source for both staff notation and the checked-in Type 1 MIDI files in `songs/demo/`.

## Custom MIDI

Use **Song Studio → Import MIDI…**. Each note track must be assigned Right, Left, or Ignore. Assignments are saved by SHA-256, and imported copies are retained in `songs/custom/` and the application data folder. Custom files use falling notes. The app supports SMF Type 1 and Type 0 single-part/single-channel drills; it never guesses a two-hand split. Type 2, SMPTE timing, percussion, unsupported time/key signatures, malformed note pairs, and out-of-piano-range notes produce validation messages. Only 2/4, 3/4, and 4/4, and keys through two sharps/flats are in scope. Chord clustering uses the explicit **0.125 quarter-note beat** threshold, independent of MIDI resolution; this is the numeric threshold specified for v1.

## Local data and scheduling

Data lives in `%LOCALAPPDATA%\Consonance\practice.sqlite3`. To use another profile:

```powershell
$env:CONSONANCE_DATA_DIR = 'C:\PianoPractice\Consonance'
.\.venv\Scripts\consonance.exe
```

SQLite stores sessions and append-only raw attempts, plus preferences and a rebuildable `item_schedule`. There is no account or cloud service. Back up the data folder with the app closed.

Ten recent attempts determine mastery: at least nine clean first tries, plus median fluency ≤1600ms for notes, ≤2400ms for intervals, ≤3800ms for phrases, or ≤2800ms for triads. Rhythm requires ≥90% hits, jitter ≤35ms, and tempo ≥60 BPM; technique requires ≥90% hits and IOI SD ≤35ms; song mastery requires Tempo mode, ≥90% hits, and ≥80% tempo. Slow clean attempts stay in the same box, due in four hours. Mistakes reset to box 1 and reappear after three intervening prompts within a running reading queue. Clean fluent attempts advance toward box 5. Box intervals are 4h / 1d / 3d / 7d / 21d; an advance uses the resulting box's interval. Recommendations move on when 80% of a unit's items are mastered. Free Practice remains open throughout.

The judge and visual latency settings are independent. Judge offset (default 0ms) is subtracted from input timestamps for timed scoring. Visual offset (default +25ms) moves only drawn coordinates. Both accept -150..+150ms. There is no tap calibration.

## Development and verification

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy --strict src tests
.\.venv\Scripts\python.exe -m pytest
```

Tests set `QT_QPA_PLATFORM=offscreen`, instantiate all screens, and exercise core state machines directly with explicit timestamps and no core threads or sleeps. The four implementation gates are recorded in `docs/verification.md`. Real USB latency, piano patch selection, local-control behavior, pedal routing, and Windows disconnect behavior still require a connected-hardware acceptance pass.

`core/` has no Qt, mido, or rtmidi imports. `RealtimeSessionWorker` owns musical state, timestamps MIDI arrivals into `SimpleQueue`, targets 2ms ticks, and dispatches only the next 4ms of output. Immutable snapshots cross into the 16ms Qt render timer. Windows/Python scheduling is not a hard-real-time guarantee. Notation is original deterministic vector geometry: clefs, accidentals, rests, flags, numerals, tilted noteheads, beams, stems, ledger lines, dots, braces, and barlines use the same painter path renderer. Ordinary interface text uses Windows Segoe UI; no music font is used.

Licensed under **0BSD**; see `LICENSE`.
