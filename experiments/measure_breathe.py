"""Measure the side 'breathe' period at each speed setting via the frame buffer (one settings write
per speed). Used to pick a breathe speed that matches a song's tempo."""
import time
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # project root
import numpy as np
from visualizer.nuphy import Keyboard, BANK_LIGHT, SIDE


def side_red(kb):
    r = kb._xfer(0xD2, bytes([3, 279 & 0xFF, 279 >> 8, 0]))      # side LED 9 (bottom), 3 bytes
    return (r[8] ^ kb.key)


kb = Keyboard()
saved = kb.read(BANK_LIGHT, SIDE, 8)
try:
    for speed in range(5):
        kb.write(BANK_LIGHT, SIDE, [3, 100, speed, 0, 0, 255, 0, 0])   # breathe, red
        t0, ts, vs = time.perf_counter(), [], []
        while time.perf_counter() - t0 < 8:
            ts.append(time.perf_counter() - t0)
            vs.append(side_red(kb))
            time.sleep(0.01)
        v = np.array(vs, float) - np.mean(vs)
        # period from autocorrelation peak
        ac = np.correlate(v, v, 'full')[len(v) - 1:]
        dt = np.mean(np.diff(ts))
        lag = np.argmax(ac[int(0.3 / dt):]) + int(0.3 / dt)
        print(f'speed byte {speed}: period ~{lag * dt:.2f} s (min {min(vs)}, max {max(vs)})', flush=True)
finally:
    kb.write(BANK_LIGHT, SIDE, saved)
    kb.close()
