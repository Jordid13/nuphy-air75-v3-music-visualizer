import time
from nuphy import Keyboard, BANK_LIGHT

kb = Keyboard()
try:
    block = kb.read(BANK_LIGHT, 0, 9)
    print('lighting block:', block.hex(' '))
    # read of bank 1 via 0xD2 returns 0xC8 filler, so don't restore from it
    for b in (100, 60, 20, 5, 20, 60, 100):
        kb.write(BANK_LIGHT, 1, [b])
        print('brightness', b)
        time.sleep(0.4)
finally:
    kb.close()
