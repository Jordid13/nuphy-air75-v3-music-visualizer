# NuPhy Air75 V3 music visualizer

> **Disclaimer: who did what.** This tool was built in conversation between me (the repo owner) and
> Claude, Anthropic's AI model, running in Claude Code.
>
> - **Me:** I came up with the idea and set the goals, and I was the eyes and hands on the actual
>   keyboard. I captured NuPhy IO's USB traffic in the browser so the protocol could be decoded, and I ran
>   every hardware experiment and reported what the lights did. I updated the firmware and factory-reset
>   the keyboard each time an experiment locked or scrambled it. I verified the key layout. Several of the
>   approaches came from me: driving the strips through the keyboard's built-in effects and their
>   parameters, flashing on beats, and making the visuals adapt to each song. I tuned it all by
>   watching it play music, and I decided what to keep.
> - **Claude:** it decoded the protocol from those captures and the NuPhy IO web app's code, designed the
>   experiments, and wrote all of the code. That covers the driver and its safety guards, the audio
>   analysis (spectrum, kick and section detection), the settings page, the macOS port and these docs.
>   Some of its experiments locked or crashed the keyboard and needed a factory reset (see the list
>   below). The macOS port hasn't been tested on a Mac yet.
>
> Unofficial and not affiliated with NuPhy. It writes to your keyboard over an undocumented protocol:
> use at your own risk.

Turns a NuPhy Air75 V3 (USB `19F5:1028`, firmware 1.0.23.6) into a music visualizer for whatever your
computer is playing. It talks to the keyboard over its reverse-engineered config protocol. Runs on
Windows and macOS.

- **Keys:** a 16-band spectrum across the columns, with a flash on kicks. The kick threshold adapts to
  each song (about one flash per beat).
- **Side strips:** the keyboard's built-in *flowing* effect. Its brightness and speed follow the song's
  sections (calm / medium / hype, ranked against the song's last minute).

## Setup

Python 3 and `pip install hidapi soundcard numpy`. Connect the keyboard by **USB cable** (Bluetooth and
2.4 GHz are untested) and close NuPhy IO: it and the visualizer each set their own session key.

- **Windows:** nothing else. The visualizer listens to your default output device (WASAPI loopback).
- **macOS:** one-time audio routing; see [macOS](#macos).

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

- **Start / Stop:** Stop gives the keyboard back (your lighting restored, NuPhy IO usable) and Start
  takes it again. The page stays up until **Quit** (in the ⋯ menu) or Ctrl+C.
- **Status:** the song's current section and tempo; the dot blinks on kicks. Detection details are in
  the footer line.
- **Keys, Kick flash, Side strips:** the main settings, with fine-tuning under **Advanced**. Settings
  only show when they apply (e.g. strip speeds only when the strips follow the song).
- **Profiles:** settings live in named profiles (`data/profiles/*.json`). **Save** updates the current
  one and lights up when there are unsaved changes; **Save as new profile**, **Reset to defaults** and
  **Delete profile** are in the ⋯ menu. The last-used profile loads on the next start.
- Settings marked with an orange dot are stored in the keyboard's flash memory, so they apply when you
  let go of the slider. Strip speed is limited to 0–3 (4 locks the keyboard's speed setting).

## macOS

macOS can't record what's playing directly, so you route the audio through the free virtual device
BlackHole once:

1. `brew install blackhole-2ch`, then log out and back in.
2. **Audio MIDI Setup** → `+` → **Create Multi-Output Device**. Tick your speakers or headphones
   (list them first, so they're the clock source) **and** BlackHole 2ch, and enable drift correction for BlackHole.
3. **System Settings → Sound → Output**: choose the Multi-Output Device.
4. `python3 -m pip install hidapi soundcard numpy`, then `python3 spectrum.py`.

- The volume keys don't work on a Multi-Output Device. Set the volume in Audio MIDI Setup on the speaker
  itself, or switch the output back to your speakers when you're not running the visualizer.
  The visualizer's automatic gain doesn't depend on volume.
- If macOS asks for **Microphone** permission for your terminal, allow it (that's how BlackHole is read).
  If the keyboard isn't found, try allowing **Input Monitoring** for your terminal too.
- `--device "name"` picks a different input (default: BlackHole).

## Files

| Path | What |
|---|---|
| `spectrum.py` | the visualizer — run this |
| `visualizer/nuphy.py` | protocol driver: session key, read/write, per-LED colours, safety guards |
| `visualizer/layout.py` | key LED index → row / x position (verified on the keyboard) |
| `visualizer/audio_source.py` | system-audio capture (Windows loopback / macOS input device) |
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
