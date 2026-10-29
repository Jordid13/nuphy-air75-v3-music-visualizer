import time
from nuphy import Keyboard, BANK_LIGHT

kb = Keyboard()
try:
    for name, rgb in (('red', [255, 0, 0]), ('green', [0, 255, 0]), ('blue', [0, 0, 255])):
        kb.write(BANK_LIGHT, 6, rgb)
        print('color', name)
        time.sleep(1.0)
    kb.write(BANK_LIGHT, 6, [255, 255, 255])
    print('color white')

    # round-trip write rate: ramp brightness up and down for ~2 s
    n, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < 2.0:
        kb.write(BANK_LIGHT, 1, [20 + (n * 4) % 80])
        n += 1
    dt = time.perf_counter() - t0
    kb.write(BANK_LIGHT, 1, [100])
    print(f'{n} writes in {dt:.2f}s = {n / dt:.0f} writes/s ({dt / n * 1000:.1f} ms each)')
finally:
    kb.close()
