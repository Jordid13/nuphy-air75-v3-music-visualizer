# NuPhy Air75 V3 music visualizer

Drives the lighting of a NuPhy Air75 V3 (USB `19F5:1028`, firmware 1.0.23.6) from whatever the PC is
playing, over the keyboard's reverse-engineered config protocol.

```
python spectrum.py            # close NuPhy IO first; opens the settings page; Ctrl+C restores your lighting
python spectrum.py --no-ui    # no settings page (uses saved settings)
python spectrum.py --stats    # plus link/audio timing every 2 s
```

**Settings page** (`http://localhost:8765`, local only): every tunable — bar height/feel, kick flash
(colour, length, when it may flash, sensitivity), side-strip mode/colour/brightness/speed per section —
applies live. Settings live in named **profiles** (`profiles/*.json`, e.g. `Main`): Save updates the
current one, Save as… makes a new one, and the last-used profile loads on the next start. Strip settings write the
keyboard's flash memory, so they apply when a slider is released; strip speed is limited to 0–3.

- **Keys:** 16-band spectrum across the columns (custom per-LED mode), red, with a white flash on kicks
  in loud parts. The kick threshold adapts to each song (~1 flash per beat).
- **Side strips:** built-in *flowing* effect, always red and on. Brightness and speed follow the song's
  sections (calm / medium / hype, ranked against the song's last minute). Each change is one settings
  save, so they are rate-limited.

Requires `pip install hidapi soundcard numpy`. `python spectrum.py --help` lists the startup options.

## macOS

The keyboard side works the same. Audio is different: macOS can't record what's playing directly,
so you route it through the free virtual device BlackHole once:

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
- Use the keyboard over **USB cable**: the config channel is the USB interface (Bluetooth/2.4 GHz untested).

## Files

| File | What |
|---|---|
| `spectrum.py` | the visualizer |
| `ui_server.py`, `ui.html` | the live settings page (schema + limits in `ui_server.py`) |
| `record_audio.py` | record what the visualizer hears to a WAV, for offline tuning |
| `nuphy.py` | protocol driver (session key, read/write, per-LED colours) with safety guards |
| `layout.py` | key LED index → row / x position (verified on the keyboard) |
| `dump_frame.py` | read the live per-LED colour frame (read-only) |
| everything else | experiments from reverse-engineering; see warnings below |

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
- Streaming D6 writes (e.g. `beat_side.py`, `--side flash`) → flash-memory wear (**permanent**) and key stalls.
- Never send `0xF1` RestoreFactory or `0xEF` SetIapMode (bootloader).

Experiment scripts that deliberately do some of the above: `exp_side5.py`, `test_numlock.py`,
`test_speed0.py`, `measure_breathe.py`, `beat_side.py`.

Known issue: the keyboard occasionally drops off USB for unknown reasons; `spectrum.py` reconnects by
itself and logs the last packets to `crash_log.txt`.
