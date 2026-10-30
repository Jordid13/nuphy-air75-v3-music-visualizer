"""Visual check of visualizer/layout.py: each row its own colour, and a white column at x ~ 8u."""
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # project root
from visualizer.nuphy import Keyboard, BANK_LIGHT, MAIN_CUSTOM
from visualizer.layout import KEYS

COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255)]

kb = Keyboard()
main0 = kb.read(BANK_LIGHT, 0, 9)
try:
    kb.write(BANK_LIGHT, 0, [MAIN_CUSTOM, 100])
    kb.set_leds([(i, *COLORS[r]) for i, r, x in KEYS])
    a = input('\nRows should be: F-row RED, number row GREEN, QWERTY row BLUE, ASDF row YELLOW, '
              'ZXCV row CYAN, bottom row MAGENTA.\nIs every key in each row the right colour? '
              'If not, which keys are wrong?\n> ')
    kb.set_leds([(i, 0, 0, 0) for i, r, x in KEYS])
    kb.set_leds([(i, 255, 255, 255) for i, r, x in KEYS if abs(x - 8) < 0.6])
    b = input('\nNow only a few keys should be white, forming a rough vertical column in the middle '
              '(around 7 / U / J / M / space).\nWhich keys are lit?\n> ')
    with open(os.path.join(ROOT, 'data', 'layout_answers.txt'), 'w', encoding='utf-8') as f:
        f.write(f'rows: {a}\ncolumn: {b}\n')
finally:
    kb.write(BANK_LIGHT, 0, main0)
    kb.close()
    print('saved data/layout_answers.txt, keyboard lighting restored')
