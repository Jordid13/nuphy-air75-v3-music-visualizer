import time
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # project root
from visualizer.nuphy import Keyboard, BANK_LIGHT, SIDE

kb = Keyboard()
try:
    orig = kb.read(BANK_LIGHT, SIDE, 8)
    print('side block:', orig.hex(' '), flush=True)

    print('brightness pulse', flush=True)
    for b in (100, 50, 10, 0, 10, 50, 100):
        kb.write(BANK_LIGHT, SIDE + 1, [b])
        time.sleep(0.5)

    # guess: bytes 14-16 (da 06 06 ~ red) are R,G,B
    for name, rgb in (('green?', [0, 255, 0]), ('blue?', [0, 0, 255])):
        kb.write(BANK_LIGHT, SIDE + 5, rgb)
        print(name, kb.read(BANK_LIGHT, SIDE, 8).hex(' '), flush=True)
        time.sleep(3)
finally:
    kb.write(BANK_LIGHT, SIDE, orig)
    print('restored', kb.read(BANK_LIGHT, SIDE, 8).hex(' '))
    kb.close()
