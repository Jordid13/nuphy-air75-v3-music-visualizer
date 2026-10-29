"""Deliberate test of side speed 0 (fastest), bypassing the driver's guard. Checks: does the keyboard
disconnect/reboot, does 0 stick, how fast does it look, and is the speed still changeable afterwards."""
import time
import numpy as np
import hid
from nuphy import Keyboard, BANK_LIGHT, SIDE, VID, PID, IFACE


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
print('side at start:', saved.hex(' '))
kb.write(BANK_LIGHT, SIDE, [0, 100, saved[2] if saved[2] in (1, 2, 3) else 2, 0, 0, 255, 0, 0])
kb.write(BANK_LIGHT, SIDE + 2, [1])
print(f'speed 1 cycle ~{cycle(kb):.2f} s', flush=True)

print('writing speed 0 ...', flush=True)
try:
    kb._write_raw(BANK_LIGHT, SIDE + 2, [0])
    time.sleep(1.0)
    print('after speed 0:', kb.read(BANK_LIGHT, SIDE, 8).hex(' '))
    print(f'speed 0 cycle ~{cycle(kb):.2f} s', flush=True)
    alive = True
except OSError as e:
    print('KEYBOARD DISCONNECTED after speed 0:', e)
    alive = False
    kb.close()
    for _ in range(40):
        time.sleep(0.5)
        if any(d['interface_number'] == IFACE for d in hid.enumerate(VID, PID)):
            break
    time.sleep(1.5)
    kb = Keyboard()
    print('reconnected; side now:', kb.read(BANK_LIGHT, SIDE, 8).hex(' '))

kb.write(BANK_LIGHT, SIDE, [0])            # make sure we're on flowing for the lock check
kb._write_raw(BANK_LIGHT, SIDE + 2, [2])
time.sleep(0.3)
s = kb.read(BANK_LIGHT, SIDE, 8)
print('lock check: wrote speed 2 ->', s.hex(' '), '| LOCKED' if s[2] != 2 else '| still changeable')
kb.write(BANK_LIGHT, SIDE, bytes.fromhex('04 3c 02 01 00 ff 00 00'))
print('side restored:', kb.read(BANK_LIGHT, SIDE, 8).hex(' '))
kb.close()
