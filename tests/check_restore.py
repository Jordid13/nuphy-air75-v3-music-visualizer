"""Run spectrum briefly, then show which lighting writes happened at the end (to debug restore)."""
import subprocess
import sys
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from nuphy import Keyboard, BANK_LIGHT, SIDE

kb = Keyboard()
kb.write(BANK_LIGHT, 0, bytes.fromhex('06 32 02 00 01 00 00 05 80'))
kb.write(BANK_LIGHT, SIDE, bytes.fromhex('04 3c 02 01 00 ff 00 00'))
print('before:', kb.read(BANK_LIGHT, 0, 17).hex(' '))
kb.close()

subprocess.run([sys.executable, os.path.join(ROOT, 'spectrum.py'), '--seconds', '2', '--debug-restore'])

kb = Keyboard()
print('after: ', kb.read(BANK_LIGHT, 0, 17).hex(' '))
kb.close()
