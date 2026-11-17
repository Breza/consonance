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
3. Start Consonance. It looks for the piano every two seconds and connects by itself, so the piano can be switched on before or after the app. The indicator at the top right turns green and names the device. The computer's own "Microsoft GS Wavetable Synth" is never chosen automatically.
4. Ensure the piano receives a piano sound on **Ch 2** and GM2 percussion on **Ch 10**. Consonance does not change your local-control or patch settings. Use the piano's volume control.
5. Open **Home** and press **Start** on the first step of *Today's plan*. Nothing is locked. All eight units and all thirteen pieces are available immediately.

If automatic connection picks nothing (several unnamed interfaces, say), open **Settings**, choose the piano's MIDI In and MIDI Out, and press **Connect**. The choice is remembered, and it survives Windows renumbering the ports. **Disconnect** is respected until you connect again. If the piano is unplugged, practice pauses and the indicator says so; plugging it back in reconnects.

In Settings, channel numbers are shown as 1–16; internally they are 0–15. Computer piano, keyboard input, and percussion must use distinct channels. If your piano sends on a different channel than Consonance is listening to, a banner says which one and offers to switch. Choose the **Piano** click for short C7/G6 notes on the computer-piano channel, or **Off**.

Routine Pause, Again, Next, loop wrap, and mode changes release only notes Consonance owns. **MIDI Panic** deliberately clears notes and sustain on all channels, including notes you hold, and forgets any key the app believes is stuck down. Exit and port changes also invoke that full cleanup.

### Without a piano

Everything works silently from the computer: click the on-screen keys, or type **A S D F G H J K L** for white keys and **W E T Y U O P** for black keys, with **Z/X** to change octave. Key auto-repeat is ignored, and keys are released when you leave the practice screen or the window.

| Key | Action |
| --- | --- |
| Space | Play / Pause |
| R | Again (in the Ear Trainer and Melody Echo: hear it again, free of charge) |
| N | Next |
| H | Hint: light the answer on the keyboard |

These work wherever keyboard focus is on the Practice screen, including inside a dropdown.

## Home

- **Today's plan** answers "what should I do now?". Reviews that have come due are listed first, one step per practice mode, oldest first. New material follows from the first unit that is not yet 80% mastered: at most eight first meetings a day, a few per mode, so new things have room to settle. When nothing is due and the day's new material is met, unfinished items of that unit are offered. Each step has a **Start** button.
- **Practice log**: minutes today, the modes touched, a seven-day chart, your streak, and how many of the 152 items are mastered. Practice for two minutes or forty-five; completed attempts commit immediately. Minutes accrue only while a drill is running and you have played within the last thirty seconds (or the music itself is moving).
- **Free practice**: every unit and every item, each with a status dot: new, learning (with its review box), due now, or mastered. Double-click to open.
- **Games**: Note Rush and Melody Echo, with personal bests.

## Practice

Pick a mode along the top and a **Set**: a unit, *Due now*, or everything. The status line reports each answer. The on-screen keyboard shows held keys in green (wanted), red (not wanted), or orange (nothing asked), and keys the piano is playing in blue. A visual beat display accompanies every click, so count-ins can be followed even with no MIDI Out.

- **Key Finder**: find keys by name before or beside staff reading: every white key in any octave, the three landmarks (Middle C, Treble G, Bass F), the black keys under both their names, and major and minor chords in any position.
- **Sight-Reader**: grand-staff notes, harmonic and melodic intervals, triads, and four-note contours that change on every presentation. Prompts are shuffled, never opening a pass with the note just shown; a missed prompt returns after three others. Untimed rolled chords are accepted whenever all required fresh strikes are physically held together and extra keys are released. Spread feedback is Tight ≤35ms, Clean ≤90ms, or Rolled. Damper sustain never substitutes for physically holding a chord.
- **Note Rush**: sixty seconds, one point per note read cleanly at the first attempt, at three levels (4, 11, or 28 notes). Every note also counts as ordinary reading practice for that note.
- **Rhythm Sniper**: read the two bars first, then press Play: a one-bar count-in, then tap the rhythm on **any key**. Taps along with the count-in are ignored. Notes turn green, amber, or red as they are judged and a playhead crosses the bars. Attack feedback uses ±35/75/135ms windows. Hold scoring includes damper sustain, with tolerance max(120ms, 30% of the expected duration). The round reports how early or late you ran and how steady you were. Play repeats the rhythm; Next moves to the next one in the set.
- **Technique Lab**: five-finger patterns right, left, together, parallel and contrary, and one-octave C, G and F major scales with their thumb crossings. The whole pattern is written out with fingering. Either your first two notes establish the pace, or (Settings) a fixed tempo with a one-bar count-in. Timing and velocity charts accompany population standard deviations of inter-onset intervals and note velocities. IOI SD ≤18ms is Excellent; ≤35ms is Good.
- **Ear Trainer**: scale degrees, intervals, and major/minor triads. A single note is always preceded by a sounded C, so it is heard as a degree of the scale rather than guessed. Probing is allowed and counted. R or a rising soft-pedal edge replays without erasing probes or adding a penalty. When you find it, the answer is named and shown on the staff. Mastery still requires a clean first try.
- **Melody Echo**: the piano plays a melody, you echo it, and it grows by one note. A wrong key costs one of three lives and the melody is played again. Three levels (3, 5, or 8 keys); the keys can light up during the piano's turn or stay dark for ear-only play.
- **Song Studio**: choose a piece, the hand you play, Wait or Tempo mode, 25–125% speed, and optionally a range of measures to loop. Every change takes effect at once. Built-ins offer a scrolling staff with a pinned clef and measure numbers, falling notes on a keyboard zoomed to the piece's range, or both.
  - **Wait mode** follows you. Each chord may be played as soon as the previous one is done; if you are ahead of the beat the accompaniment jumps forward to meet you, and if you are behind, the music freezes until you arrive. Earlier notes whose notation still spans the beat may stay held. Nothing is timed and there is no count-in.
  - **Tempo mode** gives a one-bar count-in and grades every attack against the beat. Pausing and resuming gives a fresh count-in from where you stopped. With Auto-Ramp, three consecutive passes at ≥95% accuracy add five percentage points, capped at 100%.

**Note names** and **Key hints** give answers away, so answers given while either is showing are logged but do not count toward mastery; the screen says so. **Landmark guides** tint the G and F lines and both Middle C positions, and are switched on for first-unit reading. After two wrong keys on one prompt (configurable, or off) the answer lights up on the keyboard; that attempt already counts as a miss.

## The pieces

Twelve short teaching arrangements plus one coordination study, in course order: Hot Cross Buns, Mary Had a Little Lamb, Landmark Anchor Waltz, Stepping Stones, Au Clair de la Lune (opening strain), Lightly Row, Ode to Joy (opening theme), Jingle Bells (chorus), Three-Chord Walk, Scarborough Fair, Country Dance with Drone Fifths, Frère Jacques (in F), and Ostinato and Syncopation. The named traditional and classical melodies are public-domain tunes in original elementary arrangements; Landmark Anchor Waltz, Stepping Stones, Three-Chord Walk, Country Dance and the coordination study are original. No two hands ever need the same key at once.

The score structures are the single source for the staff notation and for the checked-in Type 1 MIDI files in `songs/demo/`; a test keeps the two identical. After changing a score, regenerate them with `.\.venv\Scripts\python.exe -m consonance.io.demo_export`.

Finger numbers are starter fingerings worked out from five-finger hand positions: the hand stays put while the music fits, and moves as rarely and as comfortably as possible when it does not. By default a number is printed only where the hand takes a new position. They are always playable, though a teacher may prefer something more elegant for a particular passage.

## Custom MIDI

Use **Song Studio → Import MIDI…**. Each note track must be assigned Right, Left, or Ignore; a track that names its own hand (`rh`, `left`, `treble`…) is pre-selected, and nothing is ever guessed from the notes. Assignments are saved by SHA-256 and a copy of the file is kept in the application data folder under `songs\custom`, so imports reappear next time. Custom files use falling notes.

The app supports SMF Type 1 and Type 0 single-part/single-channel files and never guesses a two-hand split. To take real-world files as they come:

- any key signature is accepted (falling notes do not depend on it);
- percussion on channel 10 is left out, and the dialog says so;
- a key struck again while still sounding ends the earlier note there, and a note left open is closed at the end of its track;
- bars of two, three, or four quarter notes are supported however they are written, so 6/8 is counted as three quarter-note beats and 2/2 as four.

Type 2, SMPTE timing, changing time signatures, other bar lengths (5/4, 9/8, 12/8…), and notes outside the piano's range produce a plain-language message. Chord clustering uses the explicit **0.125 quarter-note beat** threshold, independent of MIDI resolution.

## Local data and scheduling

Data lives in `%LOCALAPPDATA%\Consonance`: `practice.sqlite3`, imported songs, and `consonance.log` (errors only, for diagnosis). To use another profile:

```powershell
$env:CONSONANCE_DATA_DIR = 'C:\PianoPractice\Consonance'
.\.venv\Scripts\consonance.exe
```

SQLite stores sessions and append-only raw attempts, plus preferences and a rebuildable `item_schedule`. There is no account or cloud service. Back up the data folder with the app closed.

**Mastery.** Ten recent attempts determine mastery: at least nine clean first tries, plus median fluency ≤1600ms for notes and keys, ≤2400ms for intervals, ≤3800ms for phrases, or ≤2800ms for triads and chords. Rhythm requires ≥90% hits, jitter ≤35ms, and tempo ≥60 BPM; technique requires ≥90% hits and IOI SD ≤35ms; song mastery requires Tempo mode, ≥90% hits, and ≥80% tempo. A song pass, in either mode, is one attempt. Each piece has two curriculum items, right hand and hands together; the left hand alone can be practised but is not tracked.

**Review boxes.** Box intervals are 4h / 1d / 3d / 7d / 21d; an advance uses the resulting box's interval. A clean, fluent answer advances an item one box **only if the item was new or actually due**. Extra practice before then leaves the box and due date alone, so one sitting cannot push an item three weeks into the future. Slow clean attempts stay in the same box, due in four hours. Mistakes reset to box 1 and, within a running queue, reappear after three intervening prompts. Recommendations move on when 80% of a unit's items are mastered. Free practice remains open throughout.

**What does not count.** Some attempts are logged but never move the schedule in either direction: a prompt or pass you left unfinished without having played a wrong key, anything answered with note names or key hints showing, and game scores. A prompt you left after a wrong key, or asked for a hint on, does count as a miss.

The schedule is always derived from the attempt log. When the rules above change between versions, the app rebuilds it once from the log on start-up; nothing in the log is rewritten.

The judging and display latency settings are independent. Judging offset (default 0ms) is subtracted from input timestamps for timed scoring. Display offset (default +25ms) moves only drawn coordinates. Both accept -150..+150ms. There is no tap calibration; if Rhythm Sniper consistently reports you late by a similar amount while you feel on the beat, enter that amount as the judging offset.

## Development and verification

```powershell
.\.venv\Scripts\python.exe -m ruff format src tests
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy --strict src tests
.\.venv\Scripts\python.exe -m pytest
```

Tests set `QT_QPA_PLATFORM=offscreen`, instantiate all screens, and exercise the core state machines directly with explicit timestamps and no core threads or sleeps. The realtime worker is tested on its own thread against a stand-in for the MIDI ports. What was measured and checked, and what was not, is recorded in `docs/verification.md`. Real USB latency, piano patch selection, local-control behavior, pedal routing, and Windows disconnect behavior still require a connected-hardware acceptance pass.

How the pieces fit:

- `core/` has no Qt, mido, or rtmidi imports, and a test enforces that for its subpackages too. `PracticeEngine` owns the piano state and one active drill from `core/drills/`: a small state machine per practice mode that is driven with explicit times and returns an immutable description of what to draw. The engine takes its randomness from the caller, so without a random source every queue runs in a fixed order and tests are exactly repeatable.
- `RealtimeSessionWorker` is the only owner of musical state. It timestamps MIDI arrivals on RtMidi's thread into a `SimpleQueue`, ticks every 2ms using `time.sleep` (a high-resolution wait on Windows; a timed `Event.wait` rounds up to the ~15ms scheduler tick), dispatches only the next 4ms of output, and publishes a snapshot every 8ms. Saving an attempt updates just that item's schedule from its last ten attempts, so its cost does not grow with the log. Port discovery and hot-plug handling live on the GUI thread. Windows/Python scheduling is not a hard-real-time guarantee.
- The GUI draws snapshots on a 16ms timer and repaints a widget only when what it shows has changed. Engine failures pause practice and are logged; a failed MIDI send closes the ports and says so.
- Notation is original deterministic vector geometry: clefs, accidentals, rests, flags, numerals, tilted noteheads, beams, stems, ledger lines, dots, braces, and barlines use the same painter path renderer, built once per layout. Ordinary interface text uses Windows Segoe UI; no music font is used.

Licensed under **0BSD**; see `LICENSE`.
