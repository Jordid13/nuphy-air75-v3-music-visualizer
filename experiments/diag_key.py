"""Read-only check: dump raw replies to the handshake and the lighting read."""
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # project root
from visualizer.nuphy import Keyboard, frame

kb = Keyboard()
try:
    for cmd, plain in ((0xFB, bytes.fromhex('01a80000')), (0xD5, bytes.fromhex('11000001'))):
        r = kb._xfer(cmd, plain)
        body = r[8:8 + 17]
        print(f'cmd {cmd:#04x} raw  ', r[:8 + 17].hex(' '))
        for key in (0xF1, 0x33):
            print(f'   xor {key:#04x} ', bytes(b ^ key for b in body).hex(' '))
finally:
    kb.close()
