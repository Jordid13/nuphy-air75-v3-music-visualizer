"""Does a host-side lock-key toggle (which sends an LED output report to the keyboard) trigger rhythm?
Toggles Scroll Lock an even number of times while watching the side LED frame. Read-only on the keyboard."""
import ctypes
import time
from nuphy import Keyboard

VK_SCROLL, KEYUP = 0x14, 0x0002
user32 = ctypes.windll.user32


def tap():
    user32.keybd_event(VK_SCROLL, 0x3A, 0, 0)
    user32.keybd_event(VK_SCROLL, 0x3A, KEYUP, 0)


def side_lit(kb):
    def rd(n, addr):
        r = kb._xfer(0xD2, bytes([n, addr & 0xFF, addr >> 8, 0]))
        return bytes(b ^ kb.key for b in r[8:8 + n])
    v = rd(54, 252) + rd(6, 306)
    return [i for i in range(20) if any(v[3 * i:3 * i + 3])]


kb = Keyboard()
try:
    print('baseline:', side_lit(kb))
    hits = 0
    for n in range(4):
        tap()
        seen = set()
        for _ in range(6):            # watch ~0.3 s after each toggle
            seen |= set(side_lit(kb))
            time.sleep(0.03)
        hits += bool(seen)
        print(f'toggle {n + 1}: lit {sorted(seen)}')
        time.sleep(0.3)
    print(f'{hits}/4 toggles lit the side strip')
finally:
    kb.close()

