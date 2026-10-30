"""WARNING: every brightness change here is a SetLightState write that the keyboard saves to flash
memory (~20 ms each). Streaming them wears the flash — use spectrum.py instead.

Drive the Air75 V3 side light from whatever the PC is playing.

Captures the default speaker via WASAPI loopback and drives side light brightness:
  --mode level  brightness follows loudness continuously (auto-gain)
  --mode beat   flash on bass beats, then decay
Ctrl+C restores the original side light settings.

  python beat_side.py [--mode level] [--effect N] [--color R,G,B] [--floor 0]
"""
import argparse
import threading
import time
import warnings

import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # project root
import numpy as np
import soundcard as sc

from visualizer.nuphy import Keyboard, BANK_LIGHT, SIDE

RATE, CHUNK = 48000, 1024            # ~21 ms per chunk
BASS = (40, 160)                     # Hz band for kick/bass
HISTORY = int(1.0 * RATE / CHUNK)    # ~1 s of energy history
REFRACTORY = 0.12                    # s, min gap between beats


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=('level', 'beat'), default='level')
    p.add_argument('--floor', type=int, default=0, help='resting brightness 0-100')
    p.add_argument('--sens', type=float, default=1.4, help='beat mode: threshold vs recent average')
    p.add_argument('--decay', type=float, default=0.82, help='falloff per chunk (0-1)')
    p.add_argument('--color', default='255,0,0', help='R,G,B for the side light')
    p.add_argument('--effect', type=int, help='side light effect ID to use (solid one, once known)')
    p.add_argument('--device', help='part of the output device name to listen to (default: system default)')
    p.add_argument('--seconds', type=float, help='stop after this long (default: run until Ctrl+C)')
    return p.parse_args()


def main():
    args = parse_args()
    kb = Keyboard()
    orig = kb.read(BANK_LIGHT, SIDE, 8)
    if args.effect is not None:
        kb.write(BANK_LIGHT, SIDE, [args.effect])
    kb.write(BANK_LIGHT, SIDE + 5, [int(c) for c in args.color.split(',')])

    level = [0.0]
    stop = threading.Event()

    def writer():
        # sends at whatever rate the keyboard acks (~49/s), skipping unchanged values
        last = None
        while not stop.is_set():
            b = round(args.floor + (100 - args.floor) * level[0])
            if b != last:
                kb.write(BANK_LIGHT, SIDE + 1, [b])
                last = b
            else:
                time.sleep(0.005)

    wt = threading.Thread(target=writer, daemon=True)
    wt.start()

    freqs = np.fft.rfftfreq(CHUNK, 1 / RATE)
    band = (freqs >= BASS[0]) & (freqs <= BASS[1])
    window = np.hanning(CHUNK)
    hist = np.zeros(HISTORY)
    hi, last_beat, beats = 0, 0.0, 0
    peak = 1e-6  # level mode auto-gain: slowly decaying running max

    speaker = sc.get_speaker(args.device) if args.device else sc.default_speaker()
    mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
    print(f'listening to {speaker.name} — Ctrl+C to stop')
    warnings.filterwarnings('ignore', category=sc.SoundcardRuntimeWarning)  # silence "data discontinuity"
    try:
        with mic.recorder(samplerate=RATE, channels=2, blocksize=CHUNK) as rec:
            t_end = time.perf_counter() + args.seconds if args.seconds else float('inf')
            while time.perf_counter() < t_end:
                mono = rec.record(numframes=CHUNK).mean(axis=1)
                if args.mode == 'level':
                    rms = float(np.sqrt(np.mean(mono ** 2)))
                    peak = max(rms, peak * 0.999)
                    target = rms / peak if rms > 1e-4 else 0.0   # silence -> off
                    target = target ** 1.5                       # more contrast between quiet and loud
                    # fast attack, slower release
                    level[0] = target if target > level[0] else level[0] * args.decay + target * (1 - args.decay)
                    continue
                energy = float(np.sum(np.abs(np.fft.rfft(mono * window))[band] ** 2))
                avg = hist.mean()
                hist[hi % HISTORY] = energy
                hi += 1
                now = time.perf_counter()
                if hi > HISTORY and energy > avg * args.sens and energy > 1e-3 and now - last_beat > REFRACTORY:
                    level[0] = 1.0
                    last_beat = now
                    beats += 1
                    print(f'\rbeats: {beats}', end='', flush=True)
                else:
                    level[0] *= args.decay
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        wt.join(1.0)  # let an in-flight write finish so it can't land after the restore
        kb.write(BANK_LIGHT, SIDE, orig)
        kb.close()
        print('\nside light restored')


if __name__ == '__main__':
    main()
