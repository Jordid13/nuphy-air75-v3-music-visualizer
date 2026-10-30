"""Air75 V3 ANSI key LED layout: SetSignalColor index -> (row, x centre in key units).
Assumes LEDs run left-to-right, row by row (Esc = 0); widths approximate, rows ~16u wide."""

ROWS = [
    # row 0: Esc F1-F12, icon key, Del
    [1] * 15,
    # row 1: ` 1-0 - = Backspace PgUp
    [1] * 13 + [2, 1],
    # row 2: Tab Q-P [ ] \ PgDn
    [1.5] + [1] * 12 + [1.5, 1],
    # row 3: Caps A-L ; ' Enter Home
    [1.75] + [1] * 11 + [2.25, 1],
    # row 4: LShift Z-/ RShift Up End
    [2.25] + [1] * 10 + [1.75, 1, 1],
    # row 5: Ctrl Opt Cmd Space Cmd Fn Ctrl Left Down Right
    [1.25, 1.25, 1.25, 6.25, 1, 1, 1, 1, 1, 1],
]
WIDTH = 16.0
N_ROWS = len(ROWS)


def keys():
    """[(index, row, x_centre)]"""
    out, idx = [], 0
    for r, widths in enumerate(ROWS):
        x = 0.0
        scale = WIDTH / sum(widths) if r == 0 else 1.0   # F-row has fewer units; spread it
        for w in widths:
            out.append((idx, r, (x + w / 2) * scale))
            x += w
            idx += 1
    return out


KEYS = keys()
assert len(KEYS) == 83
