"""Music visualizer for the NuPhy Air75 V3, with a live settings page.

Keys: 16 frequency bands across the keyboard's columns (custom per-LED mode), white flash on kicks.
Side strips: built-in flowing effect, brightness/speed follow the song's sections.
Captures whatever the computer is playing (WASAPI loopback on Windows; BlackHole on macOS, see README). Ctrl+C restores your lighting.
Close NuPhy IO first (it and this script each set their own session key).

  python spectrum.py                 # opens the settings page at http://localhost:8765
  python spectrum.py --no-ui         # no settings page (uses saved settings)
"""
import argparse
import json
import os
import threading
import time
import warnings

import numpy as np
import soundcard as sc

import ui_server
from audio_source import open_capture
from nuphy import Keyboard, BANK_LIGHT, SIDE, MAIN_CUSTOM
from layout import KEYS, N_ROWS, WIDTH

RATE, HOP, FFT = 48000, 1024, 4096      # ~21 ms per update, 11.7 Hz bins
N_BANDS = 16
F_LO, F_HI = 40, 16000
BASS = (40, 150)
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, 'saved_lighting.json')
CRASH_LOG = os.path.join(HERE, 'crash_log.txt')
AGC_TARGET_DB = -20.0       # level the input is normalised to (volume independence)
AGC_SECONDS = 30.0          # slow enough that a chorus still stands out against the verse
FILL_STEPS = 4              # partial top key brightness levels (fewer = fewer packets)
PUNCH_STEPS = 4             # flash fade levels (fewer = fewer packets)
SIDE_MIN_GAP = 0.5          # s between side writes caused by settings changes (each is a flash save)
RISE_GAP = 1.0              # min s between section switches going up (each is a flash save)
FALL_GAP = 4.0              # ... going down
SILENCE_HOLD = 3.0
CALM_DB, HYPE_DB = 10.0, 4.0   # first 5 s only: dB below the loudest stretch for calm / hype
SECTION_RANK = {'silent': 0, 'calm': 1, 'medium': 2, 'hype': 3}


def parse_args():
    p = argparse.ArgumentParser(description='Most settings live on the settings page; these are startup options.')
    p.add_argument('--device', help='Windows: part of the output device name (default: system default); '
                        'macOS: part of the input device name (default: BlackHole)')
    p.add_argument('--side', choices=('flash',),
                   help='special side-strip mode not on the settings page: flash = brightness flashes on kicks '
                        '(wears flash memory!)')
    p.add_argument('--no-ui', action='store_true', help='don\'t open the settings page')
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--no-browser', action='store_true', help='serve the settings page but don\'t open it')
    p.add_argument('--seconds', type=float, help='stop after this long')
    p.add_argument('--stats', action='store_true', help='print link/audio timing every 2 s')
    p.add_argument('--debug-restore', action='store_true', help=argparse.SUPPRESS)
    return p.parse_args()


def band_plan():
    """Per band: (fft_size, bin mask). Long windows only where needed for frequency resolution (bass);
    mids and highs use short windows so they react sooner."""
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


def key_frame(levels, rgb, punch=0.0, punch_rgb=(255, 255, 255)):
    """levels: N_BANDS values in rows (0..N_ROWS); punch 0..1 blends lit keys towards punch_rgb.
    Returns {index: (r,g,b)}."""
    punch = np.ceil(punch * PUNCH_STEPS) / PUNCH_STEPS
    col = tuple(c + (p - c) * punch for c, p in zip(rgb, punch_rgb))
    out = {}
    for idx, row, x in KEYS:
        band = min(int(x / WIDTH * N_BANDS), N_BANDS - 1)
        height = N_ROWS - row                      # bottom row = 1, F-row = 6
        fill = np.clip(levels[band] - (height - 1), 0.0, 1.0)
        fill = np.ceil(fill * FILL_STEPS) / FILL_STEPS
        out[idx] = tuple(int(c * fill) for c in col)
    return out


def side_look(cfg, section):
    """Side bytes for the current settings: effect, brightness, speed, isRGB, 0, R, G, B.
    Effects: 0 flowing, 2 static. None = leave the strips alone. Speeds are 0-3 (4 locks the keyboard)."""
    mode = cfg['side_mode']
    r, g, b = cfg['side_color']
    if mode == 'keep':
        return None
    if mode == 'off':
        return bytes([2, 0, 2, 0, 0, r, g, b])
    if mode == 'static':
        return bytes([2, cfg['bright_hype'], 2, 0, 0, r, g, b])
    sec = 'calm' if section == 'silent' else section          # always on
    return bytes([0, cfg[f'bright_{sec}'], cfg[f'speed_{sec}'], 0, 0, r, g, b])


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


class SectionTracker:
    """Classifies the song's current stretch as silent / calm / medium / hype from loudness, ranked
    against the song's own last minute (so it adapts to each song and to compressed masters)."""

    def __init__(self):
        self.avg = None          # ~1 s average loudness (dB)
        self.fast = None         # ~0.15 s average, only used for getting louder
        self.peak = None         # loudest stretch, falls 0.05 dB/s
        self.hist, self.hist_t = [], 0.0
        self.silent_for = 0.0
        self.candidate, self.since = 'silent', 0.0

    def _classify(self, level):
        if len(self.hist) < 50:                       # first 5 s: fall back to distance from the peak
            below = self.peak - level
            return 'hype' if below <= HYPE_DB else 'calm' if below >= CALM_DB else 'medium'
        lo, hi = np.percentile(self.hist, [10, 90])   # the song's quiet and loud levels
        if hi - lo < 1.5:                             # barely any dynamics: stay in the middle
            return 'medium'
        pos = (level - lo) / (hi - lo)
        return 'hype' if pos >= 0.66 else 'calm' if pos <= 0.33 else 'medium'

    def update(self, rms_db, silent, dt, now):
        if silent:
            self.silent_for += dt
        else:
            self.silent_for = 0.0
            self.avg = rms_db if self.avg is None else self.avg + min(1.0, dt / 1.0) * (rms_db - self.avg)
            self.fast = rms_db if self.fast is None else self.fast + min(1.0, dt / 0.15) * (rms_db - self.fast)
            self.peak = self.avg if self.peak is None else max(self.avg, self.peak - 0.05 * dt)
            self.hist_t += dt
            if self.hist_t >= 0.1:
                self.hist_t = 0.0
                self.hist = (self.hist + [self.avg])[-600:]
        if self.silent_for >= SILENCE_HOLD or self.avg is None:
            sec = 'silent'
        elif self.silent_for > 0:
            sec = self.candidate                      # brief gap: keep what we had
        else:
            slow, fast = self._classify(self.avg), self._classify(self.fast)
            # louder: trust the fast reading (a drop goes straight up); quieter: the slower one (no flicker)
            sec = fast if SECTION_RANK[fast] > SECTION_RANK[slow] else slow
        if sec != self.candidate:
            self.candidate, self.since = sec, now
        return self.candidate


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
    cfg = ui_server.load()
    status = {}
    lock = threading.Lock()
    stop = threading.Event()
    flashing = args.side == 'flash'
    source, mic = open_capture(args.device)      # before touching the keyboard, so a missing device exits cleanly
    if flashing:
        print('WARNING: --side flash saves to the keyboard\'s flash memory on every flash (~2 writes per beat).\n'
              '         Fine for a quick look; avoid long sessions.')
        cfg['side_mode'] = 'off'

    kb = Keyboard()
    saved = saved_lighting(kb)

    def setup(kb, look):
        kb.write(BANK_LIGHT, 0, [MAIN_CUSTOM, 100])
        kb.set_leds([(i, 0, 0, 0) for i, _, _ in KEYS])
        if look is not None:
            kb.write(BANK_LIGHT, SIDE, look)

    ctx = {'kb': kb}

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

    with lock:
        first_look = side_look(cfg, 'silent')
    setup(kb, first_look)
    target = {'keys': key_frame(np.zeros(N_BANDS), tuple(cfg['color'])), 'side': 0, 'look': first_look}
    st = {'frames': 0, 'leds': 0, 'key_s': 0.0, 'side': 0, 'side_s': 0.0, 'hops': 0, 'samples': 0}

    def writer():
        sent = {i: (0, 0, 0) for i, _, _ in KEYS}
        w = {'look': first_look, 'side': -1, 'side_t': 0.0}
        while not stop.is_set():
            try:
                write_once(sent, w)
            except OSError as e:
                kb2 = reconnect(str(e))
                if kb2 is None:
                    return
                with lock:
                    cur_look = target['look']
                try:
                    setup(kb2, cur_look)
                except OSError:
                    continue
                sent.update({i: (0, 0, 0) for i in sent})
                w['look'] = cur_look

    def write_once(sent, w):
        kb = ctx['kb']
        with lock:
            side, look, keys = target['side'], target['look'], dict(target['keys'])
        now = time.perf_counter()
        if look is not None and look != w['look']:
            kb.write(BANK_LIGHT, SIDE, look)             # one flash save per change (rate-limited upstream)
            st['side'] += 1
            w['look'] = look
        if flashing and side != w['side'] and now - w['side_t'] > 0.03:
            kb.write(BANK_LIGHT, SIDE + 1, [side])
            w['side'], w['side_t'] = side, time.perf_counter()
        changed = [(i, *c) for i, c in keys.items() if sent[i] != c]
        if changed:
            t = time.perf_counter()
            kb.set_leds(changed)
            st['key_s'] += time.perf_counter() - t
            st['frames'] += 1
            st['leds'] += len(changed)
            for i, *c in changed:
                sent[i] = tuple(c)
        else:
            time.sleep(0.004)

    wt = threading.Thread(target=writer, daemon=True)
    wt.start()

    kick = {'thr': cfg['kick_db'], 't': time.perf_counter(), 'hits': 0, 'loud_s': 0.0,
            'adaptive': cfg['adaptive_kicks'], 'flashes': []}

    quit_req = threading.Event()

    def on_action(name):
        if name == 'reset_kick':
            with lock:
                kick.update(thr=cfg['kick_db'], hits=0, loud_s=0.0)
        elif name == 'quit':
            quit_req.set()                               # main loop ends; lighting is restored

    if not args.no_ui:
        url = ui_server.start(cfg, status, lock, args.port, open_browser=not args.no_browser, on_action=on_action)
        print(f'settings page: {url}')

    plan, windows = band_plan()
    buf = np.zeros(FFT)
    agc = {'db': None, 'gain': 1.0, 'digital_silence': True}
    levels = np.zeros(N_BANDS)
    avg_db = None                  # average band loudness over the last `memory` seconds (dB)
    short_db = None                # per-band level over the last ~0.3 s, for punchiness
    SHORT_S = 0.3
    tilt = np.zeros(N_BANDS)       # slow per-band average, removes the bass-heavy spectral tilt
    hop_s = HOP / RATE             # reference step: per-hop rates below are scaled to real elapsed time
    rms_ref = None                 # loudest recent level (dB), for the "loud parts" flash mode
    bass_hist = []                 # bass level (dB) of the last few 10 ms steps, for kick attacks
    sections = SectionTracker()
    tempo = TempoTracker()
    f1k = np.fft.rfftfreq(HOP, 1 / RATE)
    tempo_band = (f1k >= 40) & (f1k <= 400)          # kick + snare body
    short_win = np.hanning(HOP)
    short_bass = (f1k >= BASS[0]) & (f1k <= BASS[1])
    section = applied_section = want_section = 'silent'
    want_look, want_since, last_switch = first_look, 0.0, -FALL_GAP
    last_flash = -1.0
    t_status = 0.0

    print(f'listening to {source} — Ctrl+C to stop')
    warnings.filterwarnings('ignore', category=sc.SoundcardRuntimeWarning)
    try:
        with mic.recorder(samplerate=RATE, channels=2, blocksize=256) as rec:
            t_end = time.perf_counter() + args.seconds if args.seconds else float('inf')
            t_stats = t_prev = time.perf_counter()
            while time.perf_counter() < t_end and not quit_req.is_set():
                # take whatever audio has arrived (never a backlog), analyse the newest window
                data = rec.record(numframes=None)
                if len(data) == 0:
                    time.sleep(0.002)
                    continue
                with lock:
                    c = dict(cfg)                         # this pass's settings (the page can change them)
                mono = data.mean(axis=1)[-FFT:]
                # automatic gain: hold the song's ~30 s level constant so system/player volume doesn't matter
                raw_rms = float(np.sqrt(np.mean(mono ** 2)))
                agc['digital_silence'] = raw_rms < 1e-7
                if not agc['digital_silence']:
                    raw_db = 20 * np.log10(raw_rms)
                    if agc['db'] is None:
                        agc['db'] = raw_db
                    elif raw_db > agc['db'] - 40:                 # ignore near-silence (fade-outs, gaps)
                        # >15 dB away: the volume was changed, catch up in ~3 s; otherwise adapt slowly
                        secs = 3.0 if abs(raw_db - agc['db']) > 15 else AGC_SECONDS
                        agc['db'] += min(1.0, len(mono) / RATE / secs) * (raw_db - agc['db'])
                    agc['gain'] = float(np.clip(10 ** ((AGC_TARGET_DB - agc['db']) / 20), 0.5, 1000.0))
                mono = mono * agc['gain']
                buf = np.roll(buf, -len(mono))
                buf[-len(mono):] = mono
                t_now = time.perf_counter()
                k = (t_now - t_prev) / hop_s          # elapsed time in hops
                dt = k * hop_s
                t_prev = t_now
                st['hops'] += 1
                st['samples'] += len(mono)
                if args.stats and t_now - t_stats >= 2.0:
                    el = t_now - t_stats
                    f = max(st['frames'], 1)
                    print(f"key frames/s {st['frames'] / el:5.1f} | leds/frame {st['leds'] / f:5.1f} | "
                          f"ms/frame {1000 * st['key_s'] / f:5.1f} | side writes/s {st['side'] / el:4.1f} | "
                          f"audio reads/s {st['hops'] / el:5.1f}, "
                          f"{1000 * st['samples'] / max(st['hops'], 1) / RATE:4.1f} ms each", flush=True)
                    for key in st:
                        st[key] = 0
                    t_stats = t_now

                # --- spectrum bars
                # silent = no signal at all, or 40 dB below the song's normal level (at any volume)
                silent = agc['digital_silence'] or np.sqrt(np.mean(buf[-HOP:] ** 2)) < 10 ** ((AGC_TARGET_DB - 40) / 20)
                mags = {n: np.abs(np.fft.rfft(buf[-n:] * w)) * (FFT / n) for n, w in windows.items()}
                energy = np.array([mags[n][m].mean() for n, m in plan])
                db = 20 * np.log10(energy + 1e-9)
                if silent:
                    new = np.zeros(N_BANDS)
                else:
                    tilt = db if not tilt.any() else tilt + min(1.0, dt / 20.0) * (db - tilt)   # ~20 s
                    comp = db - (tilt - tilt.mean())                   # flatten bass vs treble
                    now_db = comp.mean()
                    avg_db = now_db if avg_db is None else avg_db + min(1.0, dt / c['memory']) * (now_db - avg_db)
                    top = avg_db + c['headroom']                       # full bar
                    short_db = comp.copy() if short_db is None else short_db + min(1.0, dt / SHORT_S) * (comp - short_db)
                    # sustained sound settles at its normal height; rises above the recent level jump higher
                    lively = comp + c['transient'] * np.maximum(comp - short_db, 0)
                    norm = (lively - (top - c['range'])) / c['range'] * c['gain']
                    new = np.clip(norm, 0, 1) * N_ROWS
                levels = np.where(new > levels, new, levels * c['decay'] ** k)

                # --- sections and tempo
                now = time.perf_counter()
                loud_db = 20 * np.log10(np.sqrt(np.mean(mono ** 2)) + 1e-9)
                section = sections.update(loud_db, silent, dt, now)
                newest = buf[-HOP:]
                bpm = tempo.update(np.log(np.abs(np.fft.rfft(newest * short_win))[tempo_band] + 1e-6), dt)

                # --- kicks: a sharp rise in bass over the last ~30 ms (its attack), checked every ~10 ms
                if kick['adaptive'] != c['adaptive_kicks']:          # toggled on the page: restart from slider
                    kick.update(adaptive=c['adaptive_kicks'], thr=c['kick_db'], hits=0, loud_s=0.0)
                thr = kick['thr'] if c['adaptive_kicks'] else c['kick_db']
                gap = c['flash_gap_ms'] / 1000
                if not silent:
                    steps = max(1, len(mono) // 512)
                    for s in range(steps - 1, -1, -1):
                        end = len(buf) - s * 512
                        win = buf[end - HOP:end]
                        rms_db = 20 * np.log10(np.sqrt(np.mean(win ** 2)) + 1e-9)
                        rms_ref = rms_db if rms_ref is None else max(rms_db, rms_ref - 512 / RATE)   # falls 1 dB/s
                        bass_db = 20 * np.log10(np.abs(np.fft.rfft(win * short_win))[short_bass].mean() + 1e-9)
                        rise = bass_db - min(bass_hist) if bass_hist else 0.0
                        bass_hist.append(bass_db)
                        del bass_hist[:-3]
                        when = c['flash_when']
                        allowed = (section == 'hype' if when == 'hype'
                                   else rms_db >= rms_ref - c['flash_db'] if when == 'loud' else True)
                        if allowed:
                            kick['loud_s'] += 512 / RATE
                        if allowed and rise > thr and now - last_flash > gap:
                            last_flash = now
                            kick['hits'] += 1
                            kick['flashes'].append(now)
                # adapt the kick threshold to the song: aim for about one flash per beat while flashing is allowed
                if c['adaptive_kicks'] and now - kick['t'] >= 4.0:
                    if kick['loud_s'] >= 1.5:
                        rate = kick['hits'] / kick['loud_s']
                        beats = (bpm or 120) / 60
                        if rate > 1.5 * beats:
                            kick['thr'] = min(15.0, kick['thr'] * 1.2)     # catching more than kicks
                        elif rate < 0.7 * beats:
                            kick['thr'] = max(1.0, kick['thr'] / 1.2)      # missing soft kicks
                    kick.update(t=now, hits=0, loud_s=0.0)

                # --- side strips: switch looks on section changes (and settings changes), rate-limited
                look = side_look(c, section)
                if look != want_look:
                    want_look, want_since, want_section = look, now, section
                rising = SECTION_RANK[want_section] > SECTION_RANK[applied_section]
                hold = c['rise_hold'] if rising else c['fall_hold']
                if want_section == applied_section:                     # only a settings change
                    hold, min_gap = 0.0, SIDE_MIN_GAP
                else:
                    min_gap = RISE_GAP if rising else FALL_GAP
                if want_look != target['look'] and now - want_since >= hold and now - last_switch >= min_gap:
                    applied_section, last_switch = want_section, now
                    with lock:
                        target['look'] = want_look

                # --- keys
                since_hit = now - last_flash
                punch = max(0.0, 1 - since_hit / (c['punch_ms'] / 1000)) if c['punch_on'] else 0.0
                frame = key_frame(levels, tuple(c['color']), punch, tuple(c['punch_color']))
                with lock:
                    target['keys'] = frame
                    target['side'] = 100 if since_hit < 0.18 else 0

                # --- status for the page and the terminal
                if now - t_status >= 0.25:
                    t_status = now
                    kick['flashes'] = [t for t in kick['flashes'] if now - t < 4.0]
                    cur = target['look']
                    with lock:
                        status.update(section=section, strips=applied_section if cur is not None else None,
                                      speed=cur[2] if cur else None, brightness=cur[1] if cur else None,
                                      bpm=bpm, kick_db=thr, gain_db=20 * np.log10(agc['gain']),
                                      flash_rate=len(kick['flashes']) / 4.0, flashing=since_hit < 0.15)
                    if not args.stats:
                        bpm_s = f'{bpm:5.1f}' if bpm else '  ?  '
                        print(f'\rsong: {section:6s} bpm {bpm_s} | strips: {applied_section:6s} | '
                              f'kick {thr:4.1f} dB | gain {20 * np.log10(agc["gain"]):+3.0f} dB   ',
                              end='', flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        wt.join(1.0)
        for attempt in range(2):
            try:
                if attempt:
                    time.sleep(2)
                    ctx['kb'] = Keyboard()
                ctx['kb'].write(BANK_LIGHT, 0, saved[:9])
                ctx['kb'].write(BANK_LIGHT, SIDE, saved[9:17])
                if args.debug_restore:
                    print('saved:', saved.hex(' '))
                    print('now  :', ctx['kb'].read(BANK_LIGHT, 0, 17).hex(' '))
                ctx['kb'].close()
                print('\nlighting restored')
                break
            except (OSError, StopIteration) as e:
                if attempt:
                    print(f'\ncould not restore lighting ({e}); run spectrum.py again and stop it to restore')


if __name__ == '__main__':
    main()
