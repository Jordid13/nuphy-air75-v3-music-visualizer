"""How long do key packets (D8) stall around a side write (D6)? Sequential, one handle."""
import time
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # project root
from visualizer.nuphy import Keyboard, BANK_LIGHT, SIDE, MAIN_CUSTOM, CMD_SIGNAL

kb = Keyboard()
saved = kb.read(BANK_LIGHT, 0, 17)
pkt = bytes([56, 0, 0, BANK_LIGHT]) + b''.join(bytes((i, 255, 0, 0)) for i in range(14))


def d8():
    t = time.perf_counter()
    kb._xfer(CMD_SIGNAL, pkt)
    return 1000 * (time.perf_counter() - t)


try:
    kb.write(BANK_LIGHT, 0, [MAIN_CUSTOM, 100])
    kb.write(BANK_LIGHT, SIDE, [2, 100, 2, 0, 0, 255, 0, 0])
    base = sorted(d8() for _ in range(50))
    print(f'baseline key packet: median {base[25]:.1f} ms, worst {base[-1]:.1f} ms')
    for trial in range(5):
        t = time.perf_counter()
        kb.write(BANK_LIGHT, SIDE + 1, [0 if trial % 2 else 100])
        side_ms = 1000 * (time.perf_counter() - t)
        after = [d8() for _ in range(15)]
        print(f'side write {side_ms:5.1f} ms -> next key packets: ' + ' '.join(f'{a:.1f}' for a in after))
finally:
    kb.write(BANK_LIGHT, 0, saved[:9])
    kb.write(BANK_LIGHT, SIDE, saved[9:17])
    print('restored:', kb.read(BANK_LIGHT, 0, 17).hex(' '))
    kb.close()
