"""Does Num Lock (host lock state -> LED report) light anything? Toggles it 4 times, watches every LED."""
import ctypes
import time
from nuphy import Keyboard
from dump_frame import read_frame

user32 = ctypes.windll.user32
VK_NUMLOCK = 0x90


def tap():
    user32.keybd_event(VK_NUMLOCK, 0x45, 0x0001, 0)            # extended-key flag for Num Lock
    user32.keybd_event(VK_NUMLOCK, 0x45, 0x0001 | 0x0002, 0)


def lit(f):
    return [j for j in range(104) if any(f[3 * j:3 * j + 3])]


kb = Keyboard()
try:
    base = read_frame(kb)
    print('Num Lock on at start:', bool(user32.GetKeyState(VK_NUMLOCK) & 1))
    for n in range(4):
        tap()
        time.sleep(0.4)
        f = read_frame(kb)
        diff = [j for j in range(104) if f[3 * j:3 * j + 3] != base[3 * j:3 * j + 3]]
        side = [j - 84 for j in lit(f) if j >= 84]
        print(f'toggle {n + 1}: NumLock={bool(user32.GetKeyState(VK_NUMLOCK) & 1)} '
              f'side lit={side} | LEDs differing from start: {len(diff)} {diff[:12]}')
finally:
    kb.close()
