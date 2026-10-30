# NuPhy Air75 V3 music visualizer

> [!NOTE]
> **Who built what.** Made by me (the repo owner) together with Claude, Anthropic's AI model, in Claude Code.
>
> **Me**
> - Came up with the idea and set the goals
> - Captured NuPhy IO's USB traffic so the protocol could be decoded
> - Ran every hardware test and reported what the lights did
> - Updated the firmware and factory-reset the keyboard whenever a test broke it
> - Verified the key layout
> - Ideas: use the strips' built-in effects, flash on the beat, adapt to each song
> - Tuned it by watching it play music and decided what to keep
>
> **Claude**
> - Decoded the protocol from my captures and the NuPhy IO web app's code
> - Designed the experiments
> - Wrote all of the code: the driver and its safety guards, the audio analysis, the settings page,
>   the macOS port, and these docs
> - Some of its experiments locked or crashed the keyboard and needed a factory reset (see the list below)
> - Tested the macOS port on a Mac (2026-10-30), fixed what broke, and replaced the BlackHole routing
>   with a system-audio tap; see [macOS](#macos)

> [!WARNING]
> Unofficial and not affiliated with NuPhy. This tool writes to your keyboard over an undocumented
> protocol, so use it at your own risk.

Turns a NuPhy Air75 V3 (USB `19F5:1028`, firmware 1.0.23.6) into a music visualizer for whatever your
computer is playing. It talks to the keyboard over its reverse-engineered config protocol.

- **Keys:** a 16-band spectrum with a flash on kicks. The kick threshold adapts to each song (about one
  flash per beat). Four styles:
  - **Bars:** classic bars, growing from the bottom, top, left or right.
  - **Mirror:** bars grow up and down from the middle rows.
  - **Rings:** bass glows in the centre, treble towards the edges.
  - **Waterfall:** a scrolling spectrogram; the F-row is now.

  The frequency range the bars cover is adjustable (default 40–16,000 Hz). The keys go dark in silence.
- **Side strips:** the keyboard's built-in *flowing* effect. Its brightness and speed follow the song's
  sections (calm / medium / hype, ranked against the song's last minute).

## Support

| | Audio capture | Status |
|---|---|---|
| **Windows** | WASAPI loopback of your output device | where it was developed; works |
| **macOS 14.2+** | Core Audio system-audio tap; your output and volume keys unchanged | tested on macOS 27.0.1 |
| **macOS before 14.2** | BlackHole virtual device + Multi-Output Device | should work: the same path (`--device BlackHole`) was tested on 27.0.1; volume keys don't |
| **Linux** | soundcard's loopback (PulseAudio monitor) | untested |

Keyboard: NuPhy Air75 V3 on firmware 1.0.23.6, over a USB cable. Bluetooth and 2.4 GHz are untested;
other NuPhy models and firmware versions are unknown.

## Setup

Python 3 and `pip install hidapi soundcard numpy`. Connect the keyboard by **USB cable** and close
NuPhy IO: it and the visualizer each set their own session key.

- **Windows:** nothing else. The visualizer listens to your default output device (WASAPI loopback).
- **macOS:** the Xcode command line tools and one permission; see [macOS](#macos).

## Running it

```
python spectrum.py                 # opens the settings page; Ctrl+C quits and restores your lighting
python spectrum.py --no-ui         # no settings page (uses the last-used profile)
python spectrum.py --device "USB"  # a different audio device (part of its name)
python spectrum.py --stats         # print link/audio timing every 2 s
python spectrum.py --help          # all startup options
```

Your own lighting is restored whenever the visualizer stops. If a run ends without restoring it, the
next run restores your lighting when it stops.

## Settings page

`http://localhost:8765` opens on start (local only; nothing leaves your computer). Changes apply live.

- **Live keyboard:** at the top, the keys in the colours the visualizer is sending them right now. The
  side strips run the keyboard's own effect, so they're drawn from its settings (colour, brightness, speed).
- **Start / Stop:** Stop gives the keyboard back (your lighting restored, NuPhy IO usable) and Start
  takes it again. The page stays up until **Quit** (in the ⋯ menu) or Ctrl+C.
- **Status:** the song's current section and tempo; the dot blinks on kicks. Detection details are in
  the footer line.
- **Keys, Kick flash, Side strips:** the main settings, with fine-tuning under **Advanced**. Settings
  only show when they apply (e.g. strip speeds only when the strips follow the song). Keys has the style,
  the direction bars grow from (Bars only), and the frequency range.
- **Profiles:** settings live in named profiles (`data/profiles/*.json`). **Save** updates the current
  one and lights up when there are unsaved changes; **Save as new profile**, **Reset to defaults** and
  **Delete profile** are in the ⋯ menu. The last-used profile loads on the next start.
- Settings marked with an orange dot are stored in the keyboard's flash memory, so they apply when you
  let go of the slider. Strip speed is limited to 0–3 (4 locks the keyboard's speed setting).

## macOS

On macOS 14.2 and later the visualizer records the system audio directly with a Core Audio tap. Your
output device and its volume keys stay exactly as they are; no virtual audio device or routing needed.

1. `python3 -m pip install hidapi soundcard numpy`, and the Xcode command line tools
   (`xcode-select --install`), which build the small tap helper (`visualizer/mac_tap.swift`) on the
   first run, into `data/mac_tap`.
2. **System Settings → Privacy & Security → Screen & System Audio Recording**: under
   **System Audio Recording Only**, add your terminal app (Terminal, iTerm, Ghostty…) and turn it on.
   Without it macOS gives the visualizer silence, with no error.
3. `python3 spectrum.py`.

- The visualizer hears the audio before your volume is applied, so muting doesn't make it go dark.
  Its automatic gain doesn't depend on volume anyway.
- The tap only starts once the Mac plays something, so the keys stay dark until then.
- If the keyboard isn't found, try allowing **Input Monitoring** for your terminal too.

**macOS before 14.2:** route the audio through the free virtual device BlackHole instead:

1. `brew install blackhole-2ch`, then log out and back in.
2. **Audio MIDI Setup** → `+` → **Create Multi-Output Device**. Tick your speakers or headphones
   (list them first, so they're the clock source) **and** BlackHole, and enable drift correction for BlackHole.
3. **System Settings → Sound → Output**: choose the Multi-Output Device.
4. `python3 spectrum.py --device BlackHole`, and allow **Microphone** access for your terminal if asked.

The volume keys don't work on a Multi-Output Device; set the volume in Audio MIDI Setup or switch the output
back when you're not running the visualizer. `--device` with part of any input's name works on 14.2+ too.

**Tested on a Mac** (2026-10-30, macOS 27.0.1, Python 3.13, keyboard over USB): system-audio tap with the
output on a USB audio device (~165 key frames/s), the BlackHole fallback (~175 key frames/s), the settings
page and lighting restore. Fixed along the way: a start-up crash on macOS (`soundcard.SoundcardRuntimeWarning`
only exists on Windows, so it's now silenced only there).

## Files

| Path | What |
|---|---|
| `spectrum.py` | the visualizer — run this |
| `visualizer/nuphy.py` | protocol driver: session key, read/write, per-LED colours, safety guards |
| `visualizer/layout.py` | key LED index → row / x position (verified on the keyboard) |
| `visualizer/audio_source.py` | system-audio capture (Windows loopback / macOS tap or input device) |
| `visualizer/mac_tap.swift` | macOS system-audio tap helper, built on first run |
| `visualizer/ui_server.py`, `ui.html` | the settings page; the settings schema and limits are in `ui_server.py` |
| `tools/record_audio.py` | record what the visualizer hears to a WAV in `data/`, for offline tuning |
| `tools/dump_frame.py` | read the live per-LED colour frame (read-only) |
| `experiments/`, `tests/` | one-off hardware scripts from reverse-engineering the keyboard — not automated tests. Read the warnings below before running any |
| `data/` | per-machine files, not in git: profiles, your saved lighting, crash log, recordings, experiment output |

Scripts in the subfolders run from any working folder, e.g. `python tools/record_audio.py 60`.

## Protocol summary

64-byte HID reports on interface 3, no report ID. `[0]` 0x55 request / 0xAA reply, `[1]` command,
`[3]` checksum = sum(bytes 4..63), payload XOR a per-session key set with `0xEE` SetSecretKey.
Payload `[len][addr lo][addr hi][bank][data…]`.

| Cmd | Name | Notes |
|---|---|---|
| D5 / D6 | Get / SetLightState | bank 1: main 0–8, side 9–16. **D6 saves to flash on every change (~20 ms)** |
| D8 | SetSignalColor | per-LED `[idx][R][G][B]`, keys 0–82, fast (~2 ms), not saved |
| D2 | GetKeyLightColor | live frame of all 104 LEDs (84 keys + 20 side) |

## Things that break the keyboard (all recoverable with a factory reset unless noted)

- Side effect ≥ 5 → side light locked. Driver refuses it.
- Side speed 4, or changing speed while the side effect is static/rhythm → speed setting locked.
  Driver refuses / works around it. Speeds 0–3 are fine.
- Per-LED index ≥ 104 → keyboard reboots.
- Toggling Num Lock → keyboard reboots.
- Writing packets without waiting for acks → scrambled settings.
- Streaming D6 writes (e.g. `experiments/beat_side.py`, `--side flash`) → flash-memory wear (**permanent**) and key stalls.
- Never send `0xF1` RestoreFactory or `0xEF` SetIapMode (bootloader).

Scripts that deliberately do some of the above: `experiments/exp_side5.py`, `experiments/measure_breathe.py`,
`experiments/beat_side.py`, `tests/test_numlock.py`, `tests/test_speed0.py`.

Known issue: the keyboard occasionally drops off USB for unknown reasons; `spectrum.py` reconnects by
itself and logs the last packets to `data/crash_log.txt`.
