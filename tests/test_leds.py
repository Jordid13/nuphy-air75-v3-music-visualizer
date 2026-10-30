"""Per-LED test: Esc blue, then sweep indices past the key LEDs to find the side strips."""
import time
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root
from nuphy import Keyboard, BANK_LIGHT, MAIN_CUSTOM

kb = Keyboard()
try:
    state = kb.read(BANK_LIGHT, 0, 9)
    print('main before:', state.hex(' '), flush=True)
    if state[0] != MAIN_CUSTOM:
        kb.write(BANK_LIGHT, 0, [MAIN_CUSTOM])

    print('step 1: all keys off, Esc (index 0) blue', flush=True)
    kb.set_leds([(i, 0, 0, 0) for i in range(83)])
    kb.set_leds([(0, 0, 0, 255)])
    time.sleep(4)

    print('step 2: indices 83-110 red', flush=True)
    kb.set_leds([(i, 255, 0, 0) for i in range(83, 111)])
    time.sleep(6)
finally:
    kb.close()
    print('done (left in custom mode; set lighting in NuPhy IO after reloading it)')
