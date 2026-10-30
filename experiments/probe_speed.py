"""After a factory reset: change the side flowing speed back and forth using only 1-3, reading it back
each time. If speeds 1-3 are safe, every write sticks and the speed is still changeable at the end."""
import time
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # project root
from visualizer.nuphy import Keyboard, BANK_LIGHT, SIDE

SEQUENCE = [3, 2, 1, 2, 3, 1, 3, 2, 1, 2]

kb = Keyboard()
saved = kb.read(BANK_LIGHT, SIDE, 8)
print('side at start:', saved.hex(' '))
try:
    start_speed = saved[2] if saved[2] in (1, 2, 3) else 2
    kb.write(BANK_LIGHT, SIDE, [0, 100, saved[2], 0, 0, 255, 0, 0])      # flowing, keep stored speed
    ok = True
    for v in SEQUENCE:
        kb.write(BANK_LIGHT, SIDE + 2, [v])
        time.sleep(0.5)
        got = kb.read(BANK_LIGHT, SIDE, 8)[2]
        print(f'speed {v}: stored {got}', flush=True)
        if got != v:
            print('STOP: speed did not stick')
            ok = False
            break
    if ok:
        print(f'all {len(SEQUENCE)} changes stuck — speeds 1-3 look safe')
finally:
    kb.write(BANK_LIGHT, SIDE, saved)
    print('side restored:', kb.read(BANK_LIGHT, SIDE, 8).hex(' '))
    kb.close()
