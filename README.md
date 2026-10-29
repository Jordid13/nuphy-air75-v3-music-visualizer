# NuPhy Air75 V3 music visualizer

Drives the lighting of a NuPhy Air75 V3 (USB `19F5:1028`, firmware 1.0.23.6) from whatever the PC is
playing, over the keyboard's reverse-engineered config protocol.

```
python spectrum.py            # close NuPhy IO first; Ctrl+C restores your lighting
python spectrum.py --stats    # plus link/audio timing every 2 s
```

- **Keys:** 16-band spectrum across the columns (custom per-LED mode), red, with a white flash on kicks
  in loud parts. The kick threshold adapts to each song (~1 flash per beat).
- **Side strips:** built-in *flowing* effect, always red and on. Brightness and speed follow the song's
  sections (calm / medium / hype, ranked against the song's last minute). Each change is one settings
  save, so they are rate-limited.

Requires `pip install hidapi soundcard numpy`. See `python spectrum.py --help` for tuning options.

## Files

| File | What |
|---|---|
| `spectrum.py` | the visualizer |
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
