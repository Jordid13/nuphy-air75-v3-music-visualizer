"""Custom-mode checks via the live frame buffer (no need to watch):
1. map SetSignalColor index -> frame index
2. do non-contiguous records in one packet work?
3. how fast can we push packets, with and without waiting for each ack?"""
import time
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root
from nuphy import Keyboard, BANK_LIGHT, MAIN_CUSTOM, CMD_SIGNAL, frame
from dump_frame import read_frame

kb = Keyboard()
main0 = kb.read(BANK_LIGHT, 0, 9)
try:
    kb.write(BANK_LIGHT, 0, [MAIN_CUSTOM, 100])
    kb.set_leds([(i, 0, 0, 0) for i in range(83)])

    # 1. index map: tag each LED with its index in the red channel
    kb.set_leds([(i, 3 * i, 255, 0) for i in range(83)])
    time.sleep(0.3)
    f = read_frame(kb)
    fr = [f[3 * j:3 * j + 3] for j in range(104)]
    mapping = {}
    for j, c in enumerate(fr[:84]):
        if c[1]:
            mapping[j] = round(c[0] * 255 / c[1] / 3) if c[1] else None
    print('frame idx -> signal idx:', mapping)
    print('G values (brightness scaling):', sorted({c[1] for c in fr[:84]}))

    # 2. non-contiguous records in one packet
    kb.set_leds([(i, 0, 0, 0) for i in range(83)])
    recs = [(5, 0, 0, 255), (40, 0, 0, 255), (77, 0, 0, 255)]
    data = b''.join(bytes(r) for r in recs)
    kb._xfer(CMD_SIGNAL, bytes([len(data), 5 * 4, 0, BANK_LIGHT]) + data)
    time.sleep(0.3)
    f = read_frame(kb)
    lit = [j for j in range(84) if any(f[3 * j:3 * j + 3])]
    print('non-contiguous test, frame lit at:', lit)

    # 3a. acked rate (one 14-record packet each)
    pkt = bytes([56, 0, 0, BANK_LIGHT]) + b''.join(bytes((i, 255, 0, 0)) for i in range(14))
    n, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < 1.5:
        kb._xfer(CMD_SIGNAL, pkt); n += 1
    print(f'acked: {n / (time.perf_counter() - t0):.0f} packets/s')
    # (a pipelined test — writing many packets without waiting for acks — was removed:
    #  the keyboard dropped acks and its side light settings got scrambled)
finally:
    kb.write(BANK_LIGHT, 0, main0)
    kb.close()
    print('main restored:', main0.hex(' '))
