"""Does a speed change become VISIBLE when written as part of the full side block (like the visualizer)
versus written alone? Measures the flowing cycle from the live frame after each kind of write."""
import time
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root
import numpy as np
from nuphy import Keyboard, BANK_LIGHT, SIDE


def side_red(kb):
    def rd(n, addr):
        r = kb._xfer(0xD2, bytes([n, addr & 0xFF, addr >> 8, 0]))
        return bytes(b ^ kb.key for b in r[8:8 + n])
    v = rd(54, 252) + rd(6, 306)
    return np.array([v[3 * i] for i in range(20)], float)


def cycle(kb, secs=8):
    t0, ts, fr = time.perf_counter(), [], []
    while time.perf_counter() - t0 < secs:
        ts.append(time.perf_counter() - t0)
        fr.append(side_red(kb))
    x = np.array(fr) - np.mean(fr, axis=0)
    dt = (ts[-1] - ts[0]) / (len(ts) - 1)
    spec = np.abs(np.fft.rfft(x, axis=0)).mean(axis=1)
    f = np.fft.rfftfreq(len(x), dt)
    return 1 / f[1 + np.argmax(spec[1:])]


kb = Keyboard()
saved = kb.read(BANK_LIGHT, SIDE, 8)
try:
    kb.write(BANK_LIGHT, SIDE, [0, 100, 3, 0, 0, 255, 0, 0])
    kb.write(BANK_LIGHT, SIDE + 2, [3])
    print(f'baseline speed 3 (alone):            cycle ~{cycle(kb):.2f} s', flush=True)
    kb.write(BANK_LIGHT, SIDE, [0, 65, 0, 0, 0, 255, 0, 0])          # full block, like the visualizer
    print(f'speed 0 via FULL block (+brightness): cycle ~{cycle(kb):.2f} s  stored {kb.read(BANK_LIGHT, SIDE, 8)[2]}', flush=True)
    kb.write(BANK_LIGHT, SIDE + 2, [3])
    kb.write(BANK_LIGHT, SIDE + 2, [0])
    print(f'speed 0 written ALONE:               cycle ~{cycle(kb):.2f} s  stored {kb.read(BANK_LIGHT, SIDE, 8)[2]}', flush=True)
finally:
    kb.write(BANK_LIGHT, SIDE, saved)
    print('restored:', kb.read(BANK_LIGHT, SIDE, 8).hex(' '))
    kb.close()
