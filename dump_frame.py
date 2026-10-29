"""Read-only: dump the live per-LED color frame via GetKeyLightColor (0xD2), as NuPhy IO polls it."""
import sys
import time
from nuphy import Keyboard

CMD_KEY_LIGHT = 0xD2
TOTAL = 312          # 104 LEDs x RGB (84 key + 20 side)


def read_frame(kb):
    out = bytearray()
    for addr in range(0, TOTAL, 54):
        n = min(54, TOTAL - addr)
        r = kb._xfer(CMD_KEY_LIGHT, bytes([n, addr & 0xFF, addr >> 8, 0]))
        out += bytes(b ^ kb.key for b in r[8:8 + n])
    return bytes(out)


if __name__ == '__main__':
    kb = Keyboard()
    try:
        for k in range(int(sys.argv[1]) if len(sys.argv) > 1 else 3):
            f = read_frame(kb)
            leds = [f[i:i + 3].hex() for i in range(0, len(f), 3)]
            print(f'frame {k}: keys 0-83:', ' '.join(leds[:84]))
            print(f'         side 84-103:', ' '.join(leds[84:]))
            time.sleep(0.3)
    finally:
        kb.close()
