"""Live settings for spectrum.py: the settings schema, load/save, and a tiny local web UI
(http://localhost:8765, served by Python's standard library, nothing leaves the PC)."""
import json
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import DATA_DIR

HERE = os.path.dirname(os.path.abspath(__file__))
LEGACY_SETTINGS = os.path.join(DATA_DIR, 'settings.json')        # pre-profiles; migrated to the Main profile
PROFILE_DIR = os.path.join(DATA_DIR, 'profiles')
ACTIVE_FILE = os.path.join(PROFILE_DIR, '_active.txt')
UI_FILE = os.path.join(HERE, 'ui.html')
NAME_RE = re.compile(r'^[A-Za-z0-9 _-]{1,32}$')

# One entry per setting. 'saves': True = changing it writes the keyboard's flash memory, so the UI only
# sends it when a slider is released. Limits are enforced here, not just in the page.
# Page layout only: 'adv' = under Advanced, 'when' = {other key: values} it's shown for,
# 'trio' = calm/medium/hype sliders drawn as one row ('part' names the slider).
SCHEMA = [
    # --- keys: bars
    dict(key='color', group='Keys', label='Colour', type='color', default=[255, 0, 0]),
    dict(key='gain', group='Keys', label='Bar height', type='range', min=0.3, max=3.0, step=0.05, default=1.0,
         help='Taller or shorter bars overall'),
    dict(key='decay', group='Keys', label='Fall-off', type='range', min=0.4, max=0.95, step=0.01, default=0.72,
         help='Higher = bars drop slower and smoother'),
    dict(key='transient', group='Keys', label='Punchiness', type='range', min=0, max=3, step=0.1, default=1.0,
         help='Extra height for hits and new notes over sustained sound'),
    dict(key='headroom', group='Keys', label='Headroom (dB)', type='range', min=0, max=20, step=0.5, default=8.0,
         adv=True, help='How far above the song\'s average a bar must go to reach the top. Lower = fuller keyboard'),
    dict(key='range', group='Keys', label='Range (dB)', type='range', min=8, max=48, step=1, default=24, adv=True,
         help='Loudness span from empty to full bar. Lower = jumpier, higher = calmer'),
    dict(key='memory', group='Keys', label='Loudness memory (s)', type='range', min=2, max=30, step=1, default=8,
         adv=True, help='How long the song\'s average covers. Longer = loud sections stand out more'),
    # --- keys: kick flash
    dict(key='punch_on', group='Kick flash', label='Flash on kicks', type='bool', default=True),
    dict(key='punch_color', group='Kick flash', label='Colour', type='color', default=[255, 255, 255],
         when={'punch_on': [True]}),
    dict(key='flash_when', group='Kick flash', label='Flash during', type='select',
         options=[['hype', 'Hype sections'], ['loud', 'Loud parts'], ['always', 'Whole song']],
         default='hype', when={'punch_on': [True]}),
    dict(key='flash_db', group='Kick flash', label='Loud = within (dB)', type='range', min=1, max=15, step=0.5,
         default=4.0, when={'punch_on': [True], 'flash_when': ['loud']},
         help='How close to the song\'s loudest level counts as loud'),
    dict(key='punch_ms', group='Kick flash', label='Flash length (ms)', type='range', min=30, max=600, step=10,
         default=150, when={'punch_on': [True]}, help='How long a flash takes to fade back'),
    dict(key='adaptive_kicks', group='Kick flash', label='Auto sensitivity', type='bool', default=True, adv=True,
         when={'punch_on': [True]}, help='Adjusts the threshold per song for about one flash per beat'),
    dict(key='kick_db', group='Kick flash', label='Kick threshold (dB)', type='range', min=1, max=15, step=0.25,
         default=4.0, adv=True, when={'punch_on': [True]},
         help='Bass rise within ~30 ms that counts as a kick. Lower = more flashes. With auto on, where it starts'),
    dict(key='flash_gap_ms', group='Kick flash', label='Min gap between flashes (ms)', type='range', min=60,
         max=500, step=10, default=180, adv=True, when={'punch_on': [True]}),
    # --- side strips
    dict(key='side_mode', group='Side strips', label='Mode', type='select', saves=True,
         options=[['auto', 'Follow the song'], ['static', 'Solid colour'], ['off', 'Off'],
                  ['keep', 'Leave as they are']], default='auto'),
    dict(key='side_color', group='Side strips', label='Colour', type='color', saves=True, default=[255, 0, 0],
         when={'side_mode': ['auto', 'static']}),
    dict(key='bright_calm', group='Side strips', label='Brightness: calm', type='range', min=0, max=100, step=5,
         default=35, saves=True, trio='Brightness', part='calm', when={'side_mode': ['auto']}),
    dict(key='bright_medium', group='Side strips', label='Brightness: medium', type='range', min=0, max=100,
         step=5, default=65, saves=True, trio='Brightness', part='medium', when={'side_mode': ['auto']}),
    dict(key='bright_hype', group='Side strips', label='Brightness: hype', type='range', min=0, max=100, step=5,
         default=100, saves=True, trio='Brightness', part='hype', when={'side_mode': ['auto', 'static']}),
    dict(key='speed_calm', group='Side strips', label='Flow speed: calm', type='range', min=0, max=3, step=1,
         default=3, saves=True, trio='Flow speed', part='calm', when={'side_mode': ['auto']},
         help='0 = fastest (~1.6 s cycle), 3 = slowest (~3 s). 4 is blocked: it locks the keyboard\'s speed'),
    dict(key='speed_medium', group='Side strips', label='Flow speed: medium', type='range', min=0, max=3, step=1,
         default=1, saves=True, trio='Flow speed', part='medium', when={'side_mode': ['auto']}),
    dict(key='speed_hype', group='Side strips', label='Flow speed: hype', type='range', min=0, max=3, step=1,
         default=0, saves=True, trio='Flow speed', part='hype', when={'side_mode': ['auto']}),
    dict(key='rise_hold', group='Side strips', label='React to drops (s)', type='range', min=0.05, max=2, step=0.05,
         default=0.15, adv=True, when={'side_mode': ['auto']},
         help='How long louder music must last before the strips switch up'),
    dict(key='fall_hold', group='Side strips', label='React to calm (s)', type='range', min=0.5, max=8, step=0.5,
         default=1.5, adv=True, when={'side_mode': ['auto']},
         help='How long quieter music must last before the strips switch down'),
]
DEFAULTS = {s['key']: s['default'] for s in SCHEMA}
_BY_KEY = {s['key']: s for s in SCHEMA}


def clean(key, value):
    """Validate one setting; returns the clamped value or raises ValueError."""
    s = _BY_KEY.get(key)
    if s is None:
        raise ValueError(f'unknown setting {key}')
    t = s['type']
    if t == 'range':
        v = float(value)
        v = min(max(v, s['min']), s['max'])
        return int(round(v)) if float(s['step']).is_integer() else v
    if t == 'bool':
        return bool(value)
    if t == 'select':
        if value not in [o[0] for o in s['options']]:
            raise ValueError(f'bad value for {key}')
        return value
    if t == 'color':
        r, g, b = (int(min(max(int(c), 0), 255)) for c in value)
        return [r, g, b]
    raise ValueError(t)


def _path(name):
    if not NAME_RE.match(name or ''):
        raise ValueError('profile names: letters, numbers, spaces, - and _, up to 32 characters')
    return os.path.join(PROFILE_DIR, f'{name}.json')


def profiles():
    try:
        return sorted(f[:-5] for f in os.listdir(PROFILE_DIR) if f.endswith('.json'))
    except OSError:
        return []


def _read(name):
    cfg = dict(DEFAULTS)
    try:
        with open(_path(name)) as f:
            for k, v in json.load(f).items():
                try:
                    cfg[k] = clean(k, v)
                except ValueError:
                    pass
    except (OSError, ValueError):
        pass
    return cfg


def _set_active(name):
    with open(ACTIVE_FILE, 'w') as f:
        f.write(name)


def active():
    try:
        with open(ACTIVE_FILE) as f:
            name = f.read().strip()
        if name in profiles():
            return name
    except OSError:
        pass
    return profiles()[0] if profiles() else 'Main'


def load():
    """Settings of the last-used profile (creating Main, from an old settings.json if there is one)."""
    os.makedirs(PROFILE_DIR, exist_ok=True)
    if not profiles():
        cfg = dict(DEFAULTS)
        try:
            with open(LEGACY_SETTINGS) as f:
                for k, v in json.load(f).items():
                    try:
                        cfg[k] = clean(k, v)
                    except ValueError:
                        pass
        except (OSError, ValueError):
            pass
        save(cfg, 'Main')
    return _read(active())


def save(cfg, name=None):
    """Save to the given profile (default: the active one) and make it active."""
    name = name or active()
    os.makedirs(PROFILE_DIR, exist_ok=True)
    with open(_path(name), 'w') as f:
        json.dump(cfg, f, indent=1)
    _set_active(name)


def switch(name):
    if name not in profiles():
        raise ValueError(f'no profile {name}')
    _set_active(name)
    return _read(name)


def delete(name):
    if name not in profiles():
        raise ValueError(f'no profile {name}')
    if len(profiles()) == 1:
        raise ValueError('can\'t delete the only profile')
    os.remove(_path(name))
    if active() == name or name not in profiles():
        _set_active(profiles()[0])


def start(cfg, status, lock, port=8765, open_browser=True, on_action=None):
    """Serve the UI in a background thread. cfg/status are shared dicts guarded by lock.
    on_action(name) handles buttons like 'reset_kick'. Returns the URL."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ('/', '/index.html'):
                with open(UI_FILE, 'rb') as f:
                    body = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == '/api/state':
                with lock:
                    name = active()
                    self._json({'settings': cfg, 'status': status, 'schema': SCHEMA,
                                'profiles': profiles(), 'profile': name, 'unsaved': cfg != _read(name)})
            else:
                self._json({'error': 'not found'}, 404)

        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0)
            try:
                data = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return self._json({'error': 'bad json'}, 400)
            if self.path == '/api/settings':
                try:
                    upd = {k: clean(k, v) for k, v in data.items()}
                except (ValueError, TypeError) as e:
                    return self._json({'error': str(e)}, 400)
                with lock:
                    cfg.update(upd)
                    return self._json({'settings': cfg})
            if self.path == '/api/save':                       # {} = active profile, {"name": ...} = save as
                try:
                    with lock:
                        save(cfg, data.get('name'))
                except ValueError as e:
                    return self._json({'error': str(e)}, 400)
                return self._json({'ok': True, 'profiles': profiles(), 'profile': active()})
            if self.path == '/api/profile/load':
                try:
                    new = switch(data.get('name'))
                except ValueError as e:
                    return self._json({'error': str(e)}, 400)
                with lock:
                    cfg.update(new)
                    return self._json({'settings': cfg, 'profiles': profiles(), 'profile': active()})
            if self.path == '/api/profile/delete':
                try:
                    delete(data.get('name'))
                except ValueError as e:
                    return self._json({'error': str(e)}, 400)
                return self._json({'profiles': profiles(), 'profile': active()})
            if self.path == '/api/defaults':
                with lock:
                    cfg.update(DEFAULTS)
                    return self._json({'settings': cfg})
            if self.path == '/api/action' and on_action:
                on_action(data.get('name'))
                return self._json({'ok': True})
            self._json({'error': 'not found'}, 404)

    for p in range(port, port + 10):
        try:
            srv = ThreadingHTTPServer(('127.0.0.1', p), Handler)
            break
        except OSError:
            continue
    else:
        raise RuntimeError('no free port for the settings page')
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f'http://localhost:{srv.server_address[1]}/'
    if open_browser:
        webbrowser.open(url)
    return url
