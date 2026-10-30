"""Run spectrum.py with the settings page for a few seconds and exercise the API like the page does."""
import json
import subprocess
import sys
import time
import urllib.request

import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # project root
from visualizer.nuphy import Keyboard, BANK_LIGHT, SIDE

URL = 'http://localhost:8765'


def call(path, body=None):
    req = urllib.request.Request(URL + path, data=None if body is None else json.dumps(body).encode(),
                                 method='GET' if body is None else 'POST')
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read())


p = subprocess.Popen([sys.executable, os.path.join(ROOT, 'spectrum.py'), '--seconds', '30', '--no-browser'],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    for _ in range(40):
        time.sleep(0.25)
        try:
            st = call('/api/state')
            break
        except OSError:
            continue
    print('page served; settings:', len(st['schema']), '| status keys:', sorted(st['status']))
    html = urllib.request.urlopen(URL + '/', timeout=3).read().decode()
    print('html ok:', '<title>Keyboard Visualizer</title>' in html)

    print('set gain 1.5 ->', call('/api/settings', {'gain': 1.5})['settings']['gain'])
    print('set speed_hype 4 (should clamp to 3) ->', call('/api/settings', {'speed_hype': 4})['settings']['speed_hype'])
    try:
        call('/api/settings', {'side_mode': 'bogus'})
        print('bogus mode accepted (BAD)')
    except urllib.error.HTTPError as e:
        print('bogus mode rejected:', e.code)
    call('/api/settings', {'side_mode': 'static', 'side_color': [0, 0, 255]})
    time.sleep(1.5)
    call('/api/settings', {'side_mode': 'auto', 'speed_hype': 0})
    call('/api/action', {'name': 'reset_kick'})
    call('/api/defaults', {})
    print('defaults gain ->', call('/api/state')['settings']['gain'])
finally:
    out = p.communicate(timeout=30)[0]
    print('--- spectrum output:')
    print('\n'.join(l[-200:] for l in out.replace('\r', '\n').splitlines() if 'song:' not in l))
    kb = Keyboard()
    print('lighting after exit:', kb.read(BANK_LIGHT, 0, 17).hex(' '))
    kb.close()

