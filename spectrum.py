"""Music spectrum on the NuPhy Air75 V3.

Keys: 16 frequency bands across the keyboard's columns, bars rising from the bottom row (custom mode).
Side strips: solid colour, brightness follows the bass.
Captures whatever the PC is playing (WASAPI loopback). Ctrl+C restores your lighting.
Close NuPhy IO first (it and this script each set their own session key).

  python spectrum.py [--color 255,0,0] [--device "USB Audio"] [--no-side] [--gain 1.0]
"""
import argparse
import ctypes
import json
import os
import threading
import time
import warnings

import numpy as np
import soundcard as sc

from nuphy import Keyboard, BANK_LIGHT, SIDE, MAIN_CUSTOM
from layout import KEYS, N_ROWS, WIDTH

RATE, HOP, FFT = 48000, 1024, 4096      # ~21 ms per update, 11.7 Hz bins
N_BANDS = 16
F_LO, F_HI = 40, 16000
BASS = (40, 150)
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saved_lighting.json')
CRASH_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'crash_log.txt')
FILL_STEPS = 4                          # partial top key brightness levels (fewer = fewer packets)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--color', default='255,0,0', help='R,G,B for bars and side strips')
    p.add_argument('--device', help='part of the output device name (default: system default)')
    p.add_argument('--side', choices=('auto', 'static', 'off', 'keep', 'caps', 'flash'), default='auto',
                   help='auto: flowing effect, speed/brightness/colour follow tempo, loudness and tone (default; a settings save '
                        'at most every 10 s) | static: solid colour, set once | off: dark | keep: leave as is | '
                        'caps: LEFT strip flashes on beats by toggling Caps Lock (no flash-memory writes; '
                        'don\'t type while it runs) | '
                        'flash: beat flashes — each one saves to the keyboard\'s flash memory (wear!) and stalls the keys')
    p.add_argument('--no-side', action='store_true', help='same as --side keep')
    p.add_argument('--gain', type=float, default=1.0, help='>1 makes bars taller')
    p.add_argument('--range', type=float, default=24.0,
                   help='dB from empty to full bar; smaller = jumpier bars, larger = calmer')
    p.add_argument('--headroom', type=float, default=8.0,
                   help='dB above the recent average needed for a full bar; lower = fuller keyboard')
    p.add_argument('--memory', type=float, default=8.0,
                   help='seconds of song the average loudness covers; longer = loud sections stand out more')
    p.add_argument('--adapt', type=float, default=1.0,
                   help='side flashes: dB/s the loudest-level reference falls after loud parts')
    p.add_argument('--decay', type=float, default=0.72,
                   help='bar fall-off per 21 ms (0-1); higher = slower, smoother fall')
    p.add_argument('--flash-db', type=float, default=3.0,
                   help='side strips flash only when the song is within this many dB of its loudest; lower = rarer')
    p.add_argument('--flash-ms', type=float, default=180, help='how long each side flash stays on')
    p.add_argument('--punch-ms', type=float, default=150,
                   help='white flash on the keys on beats in loud parts: fade time (0 = off)')
    p.add_argument('--hit-db', type=float, default=3.0,
                   help='starting bass jump (dB over its recent average) that counts as a kick; '
                        'it then adapts to the song unless --fixed-kicks')
    p.add_argument('--fixed-kicks', action='store_true',
                   help='keep the kick threshold at --hit-db instead of adapting it to each song')
    p.add_argument('--seconds', type=float, help='stop after this long')
    p.add_argument('--stats', action='store_true', help='print link/audio timing every 2 s')
    p.add_argument('--debug-restore', action='store_true', help=argparse.SUPPRESS)
    return p.parse_args()


def band_plan():
    """Per band: (fft_size, bin mask, window). Long windows only where needed for frequency
    resolution (bass); mids and highs use short windows so they react sooner."""
    edges = np.geomspace(F_LO, F_HI, N_BANDS + 1)
    plan = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        n = 4096 if lo < 150 else 2048 if lo < 800 else 1024
        freqs = np.fft.rfftfreq(n, 1 / RATE)
        mask = (freqs >= lo) & (freqs < hi)
        if not mask.any():                        # narrow band: take the nearest bin
            mask[np.argmin(np.abs(freqs - (lo + hi) / 2))] = True
        plan.append((n, mask))
    windows = {n: np.hanning(n) for n in (1024, 2048, 4096)}
    return plan, windows


PUNCH_STEPS = 4                         # white-flash fade levels (fewer = fewer packets)


def key_frame(levels, rgb, punch=0.0):
    """levels: N_BANDS values in rows (0..N_ROWS); punch 0..1 blends lit keys towards white.
    Returns {index: (r,g,b)}."""
    punch = np.ceil(punch * PUNCH_STEPS) / PUNCH_STEPS
    col = tuple(c + (255 - c) * punch for c in rgb)
    out = {}
    for idx, row, x in KEYS:
        band = min(int(x / WIDTH * N_BANDS), N_BANDS - 1)
        height = N_ROWS - row                      # bottom row = 1, F-row = 6
        fill = np.clip(levels[band] - (height - 1), 0.0, 1.0)
        fill = np.ceil(fill * FILL_STEPS) / FILL_STEPS
        out[idx] = tuple(int(c * fill) for c in col)
    return out


# --side auto: the side strips run the built-in FLOWING effect (0), with its parameters following the song.
# Side bytes: effect, brightness, speed (0 fastest .. 4 slowest), isRGB (rainbow), 0, R, G, B
SECTION_BRIGHT = {'silent': 35, 'calm': 35, 'medium': 65, 'hype': 100}   # always on
# tone colours, bass-heavy -> bright: deep red, red-magenta, magenta, purple, blue-violet, blue
TONE_COLORS = [(255, 0, 0), (255, 0, 60), (255, 0, 140), (170, 0, 255), (90, 0, 255), (0, 40, 255)]


def tempo_to_speed(bpm):
    """Faster songs flow faster. Speed byte 0 is the fastest (~1.6 s cycle), 3 the slowest used (~3 s);
    4 is never used (it locks the speed setting)."""
    if bpm is None:
        return 2
    return 1 if bpm >= 125 else 2 if bpm >= 100 else 3


def flowing_look(section, speed, tone):
    # the section sets the speed across the whole visible range (calm ~4 s cycle, hype ~1.6 s);
    # tempo only nudges calm one step faster for fast songs
    if section == 'hype':
        speed = 0
    elif section == 'medium':
        speed = 1
    else:
        speed = 2 if speed <= 1 else 3
    # always red (user's choice); tone is tracked but not used for colour
    return bytes([0, SECTION_BRIGHT[section], speed, 0, 0, 255, 0, 0])


class TempoTracker:
    """BPM from autocorrelation of the bass onset envelope over the last ~8 s (sampled at 100 Hz)."""
    RATE_HZ = 100

    def __init__(self):
        self.env = np.zeros(8 * self.RATE_HZ)
        self.prev = None
        self.acc = 0.0
        self.bpm = None
        self.since_est = 0.0

    def update(self, logmag, dt):
        """logmag: log-magnitude spectrum (bass + low mids) of the newest audio."""
        flux = 0.0 if self.prev is None else float(np.maximum(logmag - self.prev, 0).sum())
        self.prev = logmag
        self.acc += dt
        while self.acc >= 1 / self.RATE_HZ:             # resample to a fixed 100 Hz
            self.acc -= 1 / self.RATE_HZ
            self.env = np.roll(self.env, -1)
            self.env[-1] = flux
        self.since_est += dt
        if self.since_est >= 2.0:
            self.since_est = 0.0
            v = self.env - self.env.mean()
            if v.std() > 1e-6:
                ac = np.correlate(v, v, 'full')[len(v) - 1:]
                lo, hi = int(60 / 180 * self.RATE_HZ), int(60 / 70 * self.RATE_HZ)   # 70-180 BPM
                lags = np.arange(lo, hi + 1)
                bpms = 60 * self.RATE_HZ / lags
                # prefer typical tempos (~100-160): avoids locking onto half or double the real tempo
                prior = np.exp(-0.5 * (np.log2(bpms / 128) / 0.5) ** 2)
                i = int(np.argmax(ac[lo:hi + 1] * prior))
                if ac[lags[i]] > 0.03 * ac[0]:               # skip only if there's no beat at all
                    self.bpm = float(bpms[i])
        return self.bpm


def tone_index(mag_lo, freqs):
    """Spectral centroid (log-scaled 300 Hz - 4 kHz) -> index into TONE_COLORS."""
    total = mag_lo.sum()
    if total <= 0:
        return 0
    c = float((mag_lo * freqs).sum() / total)
    x = (np.log(max(c, 300)) - np.log(300)) / (np.log(4000) - np.log(300))
    return int(np.clip(round(x * (len(TONE_COLORS) - 1)), 0, len(TONE_COLORS) - 1))
SECTION_HOLD = 1.5          # s a new look must last before the strips switch (getting quieter)
SECTION_GAP = 4.0           # min s between switches (each is one flash-memory save) (getting quieter)
RISE_HOLD = 0.15            # getting louder reacts fast...
RISE_GAP = 1.0              # ...but still at most one save per second
SECTION_RANK = {'silent': 0, 'calm': 1, 'medium': 2, 'hype': 3}
SILENCE_HOLD = 3.0
CALM_DB, HYPE_DB = 10.0, 4.0   # dB below the song's loudest stretch: < CALM_DB below = calm-ish, within HYPE_DB = hype


class SectionTracker:
    """Classifies the song's current stretch as silent / calm / medium / hype from loudness,
    relative to the loudest stretch heard recently (so it adapts to each song and volume)."""

    def __init__(self):
        self.avg = None          # ~1 s average loudness (dB)
        self.peak = None         # loudest stretch, falls 0.05 dB/s (~3 dB a minute)
        self.silent_for = 0.0
        self.candidate, self.since = 'silent', 0.0
        self.current = None

    def update(self, rms_db, silent, dt, now):
        if silent:
            self.silent_for += dt
        else:
            self.silent_for = 0.0
            a = min(1.0, dt / 1.0)
            self.avg = rms_db if self.avg is None else self.avg + a * (rms_db - self.avg)
            af = min(1.0, dt / 0.15)                       # fast reading, only used for getting louder
            self.fast = rms_db if getattr(self, 'fast', None) is None else self.fast + af * (rms_db - self.fast)
            self.peak = self.avg if self.peak is None else max(self.avg, self.peak - 0.05 * dt)
        if self.silent_for >= SILENCE_HOLD or self.avg is None:
            sec = 'silent'
        elif self.silent_for > 0:
            sec = self.candidate                  # brief gap: keep what we had
        else:
            # rank against the song's own last minute: real songs only vary a few dB between verse and chorus
            self.hist_t = getattr(self, 'hist_t', 0.0) + dt
            if self.hist_t >= 0.1:
                self.hist_t = 0.0
                self.hist = (getattr(self, 'hist', []) + [self.avg])[-600:]
            hist = getattr(self, 'hist', [])

            def classify(level):
                if len(hist) < 50:                       # first 5 s: fall back to distance from the peak
                    below = self.peak - level
                    return 'hype' if below <= HYPE_DB else 'calm' if below >= CALM_DB else 'medium'
                lo, hi = np.percentile(hist, [10, 90])   # the song's quiet and loud levels
                if hi - lo < 1.5:                        # barely any dynamics: stay in the middle
                    return 'medium'
                pos = (level - lo) / (hi - lo)
                return 'hype' if pos >= 0.66 else 'calm' if pos <= 0.33 else 'medium'
            slow, fast = classify(self.avg), classify(self.fast)
            # louder: trust the fast reading (a drop goes straight up); quieter: the slower one (no flicker)
            sec = fast if SECTION_RANK[fast] > SECTION_RANK[slow] else slow
        if sec != self.candidate:
            self.candidate, self.since = sec, now
        return self.candidate, now - self.since


VK_CAPITAL = 0x14
_user32 = ctypes.windll.user32


def caps_is_on():
    return bool(_user32.GetKeyState(VK_CAPITAL) & 1)


def tap_caps():
    _user32.keybd_event(VK_CAPITAL, 0x3A, 0, 0)
    _user32.keybd_event(VK_CAPITAL, 0x3A, 0x0002, 0)


def saved_lighting(kb):
    """The user's own lighting to restore on exit. If the keyboard is still in the visualizer's
    state (a previous run didn't restore), use the copy saved by that run instead."""
    cur = kb.read(BANK_LIGHT, 0, 17)
    if cur[0] != MAIN_CUSTOM:
        with open(STATE_FILE, 'w') as f:
            json.dump(cur.hex(), f)
        return cur
    try:
        with open(STATE_FILE) as f:
            return bytes.fromhex(json.load(f))
    except (OSError, ValueError):
        return bytes.fromhex('06 32 02 00 01 00 00 05 80 04 3c 02 01 00 ff 00 00')   # rainbow + rhythm


def main():
    args = parse_args()
    if args.no_side:
        args.side = 'keep'
    flashing = args.side == 'flash'
    capsing = args.side == 'caps'
    if capsing:
        print('Caps mode: the left strip flashes by toggling Caps Lock — don\'t type while this runs.')
    if flashing:
        print('WARNING: --side flash saves to the keyboard\'s flash memory on every flash (~2 writes per beat).\n'
              '         Fine for a quick look; avoid long sessions.')
    rgb = tuple(int(c) for c in args.color.split(','))
    kb = Keyboard()
    saved = saved_lighting(kb)
    caps_at_start = caps_is_on()
    if capsing and caps_at_start:
        tap_caps()                                       # start from Caps off so flashes are on/off

    def setup(kb, side_look=None):
        kb.write(BANK_LIGHT, 0, [MAIN_CUSTOM, 100])
        kb.set_leds([(i, 0, 0, 0) for i, _, _ in KEYS])
        if args.side == 'auto':
            kb.write(BANK_LIGHT, SIDE, side_look or flowing_look('silent', 2, 0))
        elif args.side != 'keep':
            # static, rainbow flag off, our colour; one write now, none while running (unless flashing)
            bright = {'static': 100, 'off': 0, 'flash': 0, 'caps': 0}[args.side]
            kb.write(BANK_LIGHT, SIDE, [2, bright, 2, 0, 0, *rgb])

    def reconnect(reason):
        """The keyboard dropped off USB (it reboots on some inputs). Log what it last got, wait, reconnect."""
        try:
            ctx['kb'].dump_history(CRASH_LOG, reason)
            ctx['kb'].close()
        except Exception:
            pass
        print(f'\nkeyboard disconnected ({reason}) — last packets saved to crash_log.txt; reconnecting...',
              flush=True)
        while not stop.is_set():
            time.sleep(0.5)
            try:
                ctx['kb'] = Keyboard()
                print('reconnected', flush=True)
                return ctx['kb']
            except Exception:
                continue
        return None

    setup(kb)
    ctx = {'kb': kb}

    target = {'keys': key_frame(np.zeros(N_BANDS), rgb), 'side': 0}
    # (side_sent starts at -1 so the first flash state is always sent; only used with --side flash)
    lock = threading.Lock()
    stop = threading.Event()

    st = {'frames': 0, 'leds': 0, 'key_s': 0.0, 'side': 0, 'side_s': 0.0, 'hops': 0}

    def writer():
        sent = {i: (0, 0, 0) for i, _, _ in KEYS}
        side_sent, side_t = -1, 0.0
        look_sent = flowing_look('silent', 2, 0) if args.side == 'auto' else None
        while not stop.is_set():
            try:
                look_sent, side_sent, side_t = write_once(sent, look_sent, side_sent, side_t)
            except OSError as e:
                kb2 = reconnect(str(e))
                if kb2 is None:
                    return
                with lock:
                    cur_look = target.get('look')
                try:
                    setup(kb2, cur_look)
                except OSError:
                    continue
                sent.update({i: (0, 0, 0) for i in sent})
                look_sent = cur_look if args.side == 'auto' else None

    def write_once(sent, look_sent, side_sent, side_t):
        kb = ctx['kb']
        if True:
            with lock:
                side = target['side']
            now = time.perf_counter()
            # side flashes first, so they never wait behind a key frame (min gap so writes can't pile up)
            with lock:
                look = target.get('look')
            if look is not None and look != look_sent:
                kb.write(BANK_LIGHT, SIDE, look)         # --side auto: one save per section change
                st['side'] += 1
                look_sent = look
            if capsing and (side > 0) != caps_is_on() and now - side_t > 0.03:
                tap_caps()                               # Windows sends the Caps light state to the keyboard
                st['side'] += 1
                side_sent, side_t = side, time.perf_counter()
            elif flashing and side != side_sent and now - side_t > 0.03:
                kb.write(BANK_LIGHT, SIDE + 1, [side])
                st['side'] += 1
                st['side_s'] += time.perf_counter() - now
                side_sent, side_t = side, time.perf_counter()
            with lock:
                keys = dict(target['keys'])
            changed = [(i, *c) for i, c in keys.items() if sent[i] != c]
            if changed:
                t = time.perf_counter()
                kb.set_leds(changed)
                st['key_s'] += time.perf_counter() - t
                st['frames'] += 1
                st['leds'] += len(changed)
                for i, *c in changed:
                    sent[i] = tuple(c)
            if not changed:
                time.sleep(0.004)
        return look_sent, side_sent, side_t

    wt = threading.Thread(target=writer, daemon=True)
    wt.start()

    plan, windows = band_plan()
    buf = np.zeros(FFT)
    levels = np.zeros(N_BANDS)
    avg_db = None                  # average band loudness over the last --memory seconds (dB)
    short_db = None                # per-band level over the last ~0.3 s, for transient emphasis
    TRANSIENT = 1.0                # how much changes (hits, new notes) are boosted over sustained level
    SHORT_S = 0.3
    tilt = np.zeros(N_BANDS)       # slow per-band average, removes the bass-heavy spectral tilt
    hop_s = HOP / RATE             # reference step: per-hop rates below are scaled to real elapsed time
    rms_ref = None                 # loudness reference for side flashes (dB), same slow fall as the keys
    bass_avg = None                # recent bass level (dB), for detecting hits
    sections = SectionTracker() if args.side == 'auto' else None
    tempo = TempoTracker()
    f1k = np.fft.rfftfreq(HOP, 1 / RATE)
    tempo_band = (f1k >= 40) & (f1k <= 400)          # kick + snare body
    t_status = 0.0
    tone_f = 0.0                                  # smoothed tone index
    freqs2k = np.fft.rfftfreq(2048, 1 / RATE)
    tone_band = (freqs2k >= 100) & (freqs2k <= 8000)
    applied_look = flowing_look('silent', 2, 0)
    want_look, want_since, last_switch = applied_look, 0.0, -SECTION_GAP
    applied_section = want_section = 'silent'
    last_flash = -1.0
    kick = {'thr': args.hit_db, 't': time.perf_counter(), 'hits': 0, 'loud_s': 0.0}
    FLASH_HOLD = args.flash_ms / 1000
    REFRACTORY = max(0.12, FLASH_HOLD)   # a hit during a flash doesn't restart it
    short_win = np.hanning(HOP)
    short_bass = (np.fft.rfftfreq(HOP, 1 / RATE) >= BASS[0]) & (np.fft.rfftfreq(HOP, 1 / RATE) <= BASS[1])

    speaker = sc.get_speaker(args.device) if args.device else sc.default_speaker()
    mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
    print(f'listening to {speaker.name} — Ctrl+C to stop')
    warnings.filterwarnings('ignore', category=sc.SoundcardRuntimeWarning)
    try:
        with mic.recorder(samplerate=RATE, channels=2, blocksize=256) as rec:
            t_end = time.perf_counter() + args.seconds if args.seconds else float('inf')
            t_stats = t_prev = time.perf_counter()
            while time.perf_counter() < t_end:
                # take whatever audio has arrived (never a backlog), analyse the newest window
                data = rec.record(numframes=None)
                if len(data) == 0:
                    time.sleep(0.002)
                    continue
                mono = data.mean(axis=1)[-FFT:]
                buf = np.roll(buf, -len(mono))
                buf[-len(mono):] = mono
                t_now = time.perf_counter()
                k = (t_now - t_prev) / hop_s          # elapsed time in hops
                t_prev = t_now
                st['hops'] += 1
                st['samples'] = st.get('samples', 0) + len(mono)
                if args.stats and t_now - t_stats >= 2.0:
                    dt = t_now - t_stats
                    f = max(st['frames'], 1)
                    print(f"key frames/s {st['frames'] / dt:5.1f} | leds/frame {st['leds'] / f:5.1f} | "
                          f"ms/frame {1000 * st['key_s'] / f:5.1f} | side writes/s {st['side'] / dt:4.1f} "
                          f"({1000 * st['side_s'] / max(st['side'], 1):4.1f} ms) | "
                          f"audio reads/s {st['hops'] / dt:5.1f}, "
                          f"{1000 * st['samples'] / max(st['hops'], 1) / RATE:4.1f} ms each", flush=True)
                    for key in st:
                        st[key] = 0
                    t_stats = t_now
                silent = np.sqrt(np.mean(buf[-HOP:] ** 2)) < 1e-4
                mags = {n: np.abs(np.fft.rfft(buf[-n:] * w)) * (FFT / n) for n, w in windows.items()}
                energy = np.array([mags[n][m].mean() for n, m in plan])
                db = 20 * np.log10(energy + 1e-9)
                if silent:
                    new = np.zeros(N_BANDS)
                else:
                    tilt = db if not tilt.any() else tilt + min(1.0, k * hop_s / 20.0) * (db - tilt)   # ~20 s
                    comp = db - (tilt - tilt.mean())                   # flatten bass vs treble
                    now_db = comp.mean()
                    a = min(1.0, k * hop_s / args.memory)
                    avg_db = now_db if avg_db is None else avg_db + a * (now_db - avg_db)
                    top = avg_db + args.headroom                       # full bar
                    sa = min(1.0, k * hop_s / SHORT_S)
                    short_db = comp.copy() if short_db is None else short_db + sa * (comp - short_db)
                    # sustained sound settles at its normal height; rises above the recent level jump higher
                    lively = comp + TRANSIENT * np.maximum(comp - short_db, 0)
                    norm = (lively - (top - args.range)) / args.range * args.gain
                    new = np.clip(norm, 0, 1) * N_ROWS
                levels = np.where(new > levels, new, levels * args.decay ** k)

                now = time.perf_counter()
                if not silent:
                    # audio can arrive in ~40 ms bursts: check every 512-sample step of the new audio, oldest first
                    steps = max(1, len(mono) // 512)
                    a = 1 - 0.95 ** (512 / HOP)                      # same ~0.4 s bass average as before
                    for s in range(steps - 1, -1, -1):
                        end = len(buf) - s * 512
                        win = buf[end - HOP:end]                     # 21 ms window: no smearing
                        rms_db = 20 * np.log10(np.sqrt(np.mean(win ** 2)) + 1e-9)
                        rms_ref = rms_db if rms_ref is None else max(rms_db, rms_ref - args.adapt * 512 / RATE)
                        bass_db = 20 * np.log10(np.abs(np.fft.rfft(win * short_win))[short_bass].mean() + 1e-9)
                        bass_avg = bass_db if bass_avg is None else bass_avg + a * (bass_db - bass_avg)
                        is_loud = rms_db >= rms_ref - args.flash_db
                        if is_loud:
                            kick['loud_s'] += 512 / RATE
                        if is_loud and bass_db > bass_avg + kick['thr'] and now - last_flash > REFRACTORY:
                            last_flash = now
                            kick['hits'] += 1
                # adapt the kick threshold to the song: aim for about one flash per beat in the loud parts
                if not args.fixed_kicks and now - kick['t'] >= 4.0:
                    if kick['loud_s'] >= 1.5:
                        rate = kick['hits'] / kick['loud_s']
                        beats = (tempo.bpm or 120) / 60
                        if rate > 1.3 * beats:
                            kick['thr'] = min(9.0, kick['thr'] * 1.2)      # catching more than kicks
                        elif rate < 0.6 * beats:
                            kick['thr'] = max(0.8, kick['thr'] / 1.2)      # missing soft kicks
                    kick.update(t=now, hits=0, loud_s=0.0)
                if sections:
                    dt = k * hop_s
                    loud_db = 20 * np.log10(np.sqrt(np.mean(mono ** 2)) + 1e-9)
                    section, _ = sections.update(loud_db, silent, dt, now)
                    newest = buf[-HOP:]
                    low_spec = np.abs(np.fft.rfft(newest * short_win))[tempo_band]
                    bpm = tempo.update(np.log(low_spec + 1e-6), dt)
                    if not silent:
                        tone_f += min(1.0, dt / 3.0) * (tone_index(mags[2048][tone_band], freqs2k[tone_band]) - tone_f)
                    look = flowing_look(section, tempo_to_speed(bpm), int(round(tone_f)))
                    if look != want_look:
                        want_look, want_since, want_section = look, now, section
                    rising = SECTION_RANK[want_section] > SECTION_RANK[applied_section]
                    hold, gap = (RISE_HOLD, RISE_GAP) if rising else (SECTION_HOLD, SECTION_GAP)
                    if (want_look != applied_look and now - want_since >= hold
                            and now - last_switch >= gap):
                        applied_look, applied_section, last_switch = want_look, want_section, now
                        with lock:
                            target['look'] = applied_look
                    if not args.stats and now - t_status >= 1.0:
                        t_status = now
                        bpm_s = f'{bpm:5.1f}' if bpm else '  ?  '
                        print(f'\rsong: {section:6s} bpm {bpm_s} | strips: {applied_section:6s} '
                              f'speed {applied_look[2]} brightness {applied_look[1]:3d} | '
                              f'kick {kick["thr"]:3.1f} dB   ', end='', flush=True)
                since_hit = now - last_flash
                punch = max(0.0, 1 - since_hit / (args.punch_ms / 1000)) if args.punch_ms > 0 else 0.0
                with lock:
                    target['keys'] = key_frame(levels, rgb, punch)
                    target['side'] = 100 if since_hit < FLASH_HOLD else 0
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        wt.join(1.0)
        if capsing and caps_is_on() != caps_at_start:
            tap_caps()
        for attempt in range(2):
            try:
                if attempt:
                    time.sleep(2)
                    ctx['kb'] = Keyboard()
                ctx['kb'].write(BANK_LIGHT, 0, saved[:9])
                ctx['kb'].write(BANK_LIGHT, SIDE, saved[9:17])
                if args.debug_restore:
                    print('saved:', saved.hex(' '))
                    for t, cmd, plain in ctx['kb'].history[-8:]:
                        if cmd in (0xD5, 0xD6):
                            print(f'  {cmd:#04x} {plain.hex(" ")}')
                    print('now  :', ctx['kb'].read(BANK_LIGHT, 0, 17).hex(' '))
                ctx['kb'].close()
                print('\nlighting restored')
                break
            except (OSError, StopIteration) as e:
                if attempt:
                    print(f'\ncould not restore lighting ({e}); run spectrum.py again and stop it to restore')


if __name__ == '__main__':
    main()
