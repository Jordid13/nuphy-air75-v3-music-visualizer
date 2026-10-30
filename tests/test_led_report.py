"""Send the keyboard's LED output report (Num=1, Caps=2, Scroll=4) directly, without touching
Windows' lock state, and watch the side strips."""
import time
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # project root
import hid
from visualizer.nuphy import Keyboard, VID, PID


def side_lit(kb):
    def rd(n, addr):
        r = kb._xfer(0xD2, bytes([n, addr & 0xFF, addr >> 8, 0]))
        return bytes(b ^ kb.key for b in r[8:8 + n])
    v = rd(54, 252) + rd(6, 306)
    return [i for i in range(20) if any(v[3 * i:3 * i + 3])]


kb = Keyboard()
for d in hid.enumerate(VID, PID):
    if d['usage_page'] == 1 and d['usage'] == 6:   # keyboard collections
        dev = hid.device()
        try:
            dev.open_path(d['path'])
        except OSError as e:
            print(f"if{d['interface_number']}: open failed: {e}")
            continue
        for bits in (0x02, 0x00, 0x01, 0x00, 0x04, 0x00):
            try:
                n = dev.write(bytes([0x00, bits]))
                time.sleep(0.15)
                print(f"if{d['interface_number']} leds={bits:#04x} write={n} side lit={side_lit(kb)}")
            except OSError as e:
                print(f"if{d['interface_number']} write failed: {e}")
                break
        dev.close()
kb.close()
