"""Read-only recorder: while you type in rhythm mode, log every change in the side LED frame
and the readable state blocks, to find the LED order and anything that tracks the rhythm level.
Writes rhythm_log.txt."""
import time
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # project root
from visualizer.nuphy import Keyboard, BANK_LIGHT

CMD_KEY_LIGHT = 0xD2
PHASES = [(5, 'IDLE - do not touch the keyboard'),
          (10, 'SOFT - press one key gently, about once a second'),
          (10, 'FAST - type as fast as you can (in Notepad, not this window)'),
          (8, 'IDLE - stop and let it fade')]


def xread(kb, cmd, n, addr=0, bank=0):
    r = kb._xfer(cmd, bytes([n, addr & 0xFF, addr >> 8, bank]))
    return bytes(b ^ kb.key for b in r[8:8 + n])


def side_frame(kb):
    return xread(kb, CMD_KEY_LIGHT, 54, 252) + xread(kb, CMD_KEY_LIGHT, 6, 306)


kb = Keyboard()
last = {}
lines = []
try:
    input('Open Notepad next to this window, then press Enter here to start recording...')
    t0 = time.perf_counter()
    for dur, label in PHASES:
        print(f'\n>>> {label} ({dur}s)', flush=True)
        lines.append(f'# {time.perf_counter() - t0:6.2f} {label}')
        end = time.perf_counter() + dur
        while time.perf_counter() < end:
            t = time.perf_counter() - t0
            cur = {
                'side': side_frame(kb),
                'light': kb.read(BANK_LIGHT, 0, 22),
                'func': xread(kb, 0xE1, 4, 0, 1),
                'sleep': xread(kb, 0xF3, 4),
            }
            for k, v in cur.items():
                if last.get(k) != v:
                    if k == 'side':
                        lit = [i for i in range(20) if any(v[3 * i:3 * i + 3])]
                        lines.append(f'{t:6.2f} side lit={lit} ' + ' '.join(v[i:i + 3].hex() for i in range(0, 60, 3)))
                    else:
                        lines.append(f'{t:6.2f} {k} {v.hex(" ")}')
                    last[k] = v
            time.sleep(0.05)
finally:
    kb.close()
    with open(os.path.join(ROOT, 'data', 'rhythm_log.txt'), 'w') as f:
        f.write('\n'.join(lines))
    print(f'\nDone - {len(lines)} lines saved to rhythm_log.txt. Tell Claude.')
