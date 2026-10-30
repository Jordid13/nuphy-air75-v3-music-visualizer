"""Where the visualizer's audio comes from: whatever the computer is playing.

Windows: WASAPI loopback of an output device (default: the system default).
macOS 14.2+: a Core Audio system-audio tap (mac_tap.swift, built on first use), so your own output
device and its volume keys stay as they are. With --device it records that input device instead
(e.g. BlackHole fed by a Multi-Output Device, for older macOS). See README "macOS".
"""
import os
import platform
import subprocess
import sys
import time
import warnings

import numpy as np
import soundcard as sc

from . import DATA_DIR

IS_MAC = sys.platform == 'darwin'
TAP_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mac_tap.swift')
TAP_BIN = os.path.join(DATA_DIR, 'mac_tap')

MAC_HELP = """no input device matching {name!r}. Inputs found: {inputs}"""

OLD_MAC_HELP = """macOS {version} can't tap system audio (needs 14.2+). Route it through BlackHole instead:
  1. brew install blackhole-2ch          (then log out and back in, or reboot)
  2. Audio MIDI Setup > + > Create Multi-Output Device; tick your speakers/headphones AND BlackHole 2ch
  3. System Settings > Sound > Output: choose that Multi-Output Device
  4. run with --device BlackHole"""


def _tap_binary():
    """The tap helper, compiled from mac_tap.swift the first time (and after it changes)."""
    if not os.path.exists(TAP_BIN) or os.path.getmtime(TAP_BIN) < os.path.getmtime(TAP_SRC):
        print('building the macOS audio tap helper (first run only)...')
        try:
            r = subprocess.run(['swiftc', '-O', TAP_SRC, '-o', TAP_BIN], capture_output=True, text=True)
        except FileNotFoundError:
            raise SystemExit('swiftc not found: install the Xcode command line tools with  xcode-select --install')
        if r.returncode:
            raise SystemExit(f'building {TAP_SRC} failed:\n{r.stderr}')
    return TAP_BIN


class _TapRecorder:
    """Same use as a soundcard recorder: record(numframes) -> float32 array (frames, 2)."""

    def __init__(self, samplerate):
        self.rate = samplerate

    def __enter__(self):
        self.proc = subprocess.Popen([_tap_binary()], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        line = self.proc.stderr.readline().decode()
        if not line.startswith('rate '):
            self.proc.wait()
            raise SystemExit((line + self.proc.stderr.read().decode()).strip() or 'audio tap failed to start')
        self.tap_rate = int(line.split()[1])
        os.set_blocking(self.proc.stdout.fileno(), False)
        self.raw = b''
        self.pending = np.zeros((0, 2), np.float32)
        return self

    def __exit__(self, *exc):
        self.proc.terminate()
        self.proc.wait()

    def _read(self):
        try:
            chunk = os.read(self.proc.stdout.fileno(), 1 << 20)
        except BlockingIOError:
            chunk = None
        if chunk == b'':
            raise RuntimeError('the macOS audio tap stopped: ' + self.proc.stderr.read().decode().strip())
        self.raw += chunk or b''
        n = len(self.raw) // 8 * 8                      # whole stereo float32 frames
        a = np.frombuffer(self.raw[:n], np.float32).reshape(-1, 2)
        self.raw = self.raw[n:]
        if self.tap_rate != self.rate and len(a):
            # shortcut: per-chunk linear resampling, fine for analysis; use a real resampler if recordings matter
            t = np.arange(0, len(a), self.tap_rate / self.rate)
            a = np.stack([np.interp(t, np.arange(len(a)), a[:, c]) for c in (0, 1)], 1).astype(np.float32)
        return a

    def record(self, numframes=None):
        """numframes=None: whatever has arrived (maybe nothing); otherwise wait for exactly that many."""
        self.pending = np.concatenate([self.pending, self._read()])
        while numframes is not None and len(self.pending) < numframes:
            time.sleep(0.005)
            self.pending = np.concatenate([self.pending, self._read()])
        n = len(self.pending) if numframes is None else numframes
        out, self.pending = self.pending[:n], self.pending[n:]
        return out


class _SystemAudio:
    def recorder(self, samplerate, channels=2, blocksize=None):
        return _TapRecorder(samplerate)


def open_capture(device=None):
    """(display name, soundcard-style microphone) for the system audio."""
    if hasattr(sc, 'SoundcardRuntimeWarning'):  # only the Windows backend has it
        warnings.filterwarnings('ignore', category=sc.SoundcardRuntimeWarning)  # "data discontinuity"
    if IS_MAC and device:
        try:
            mic = sc.get_microphone(device)
        except IndexError:
            inputs = ', '.join(repr(m.name) for m in sc.all_microphones()) or 'none'
            raise SystemExit(MAC_HELP.format(name=device, inputs=inputs))
        return mic.name, mic
    if IS_MAC:
        version = platform.mac_ver()[0]
        if tuple(int(x) for x in version.split('.')[:2]) < (14, 2):
            raise SystemExit(OLD_MAC_HELP.format(version=version))
        _tap_binary()                                    # build now, before the keyboard is touched
        return 'system audio (macOS tap)', _SystemAudio()
    speaker = sc.get_speaker(device) if device else sc.default_speaker()
    return speaker.name, sc.get_microphone(id=str(speaker.name), include_loopback=True)
