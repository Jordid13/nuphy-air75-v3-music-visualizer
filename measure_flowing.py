"""How different do flowing speeds 1-3 actually look? Records the live side frame at each speed and
estimates the pattern's cycle time (dominant frequency at each LED, averaged). Speeds 1-3 only."""
import time
import numpy as np
from nuphy import Keyboard, BANK_LIGHT, SIDE


def side(kb):
    def rd(n, addr):
        r = kb._xfer(0xD2, bytes([n, addr & 0xFF, addr >> 8, 0]))
        return bytes(b ^ kb.key for b in r[8:8 + n])
    v = rd(54, 252) + rd(6, 306)
    return np.array([v[3 * i] for i in range(20)], float)     # red channel per LED


kb = Keyboard()
saved = kb.read(BANK_LIGHT, SIDE, 8)
try:
    kb.write(BANK_LIGHT, SIDE, [0, 100, 2, 0, 0, 255, 0, 0])
    for sp in (3, 2, 1):
        kb.write(BANK_LIGHT, SIDE + 2, [sp])
        time.sleep(0.5)
        t0, ts, fr = time.perf_counter(), [], []
        while time.perf_counter() - t0 < 6:
            ts.append(time.perf_counter() - t0)
            fr.append(side(kb))
        fr = np.array(fr)
        dt = (ts[-1] - ts[0]) / (len(ts) - 1)
        x = fr - fr.mean(axis=0)
        spec = np.abs(np.fft.rfft(x, axis=0)).mean(axis=1)
        freqs = np.fft.rfftfreq(len(x), dt)
        f = freqs[1 + np.argmax(spec[1:])]
        print(f'speed {sp}: {len(ts) / 6:.0f} samples/s | pattern cycle ~{1 / f:.2f} s | '
              f'brightness range {fr.min():.0f}-{fr.max():.0f}', flush=True)
finally:
    kb.write(BANK_LIGHT, SIDE, saved)
    print('side restored:', kb.read(BANK_LIGHT, SIDE, 8).hex(' '))
    kb.close()
