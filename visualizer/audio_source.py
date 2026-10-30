"""Where the visualizer's audio comes from: whatever the computer is playing.

Windows: WASAPI loopback of an output device (default: the system default).
macOS: there is no loopback, so it records an input device that carries the system audio —
by default BlackHole (https://existential.audio/blackhole/), fed by a Multi-Output Device
that sends sound to both your speakers and BlackHole. See README "macOS".
"""
import sys
import warnings

import soundcard as sc

IS_MAC = sys.platform == 'darwin'
MAC_DEFAULT_INPUT = 'BlackHole'

MAC_HELP = """no input device matching {name!r}.
On macOS the visualizer listens to a virtual input that carries the system audio:
  1. brew install blackhole-2ch          (then log out and back in, or reboot)
  2. Audio MIDI Setup > + > Create Multi-Output Device; tick your speakers/headphones AND BlackHole 2ch
  3. System Settings > Sound > Output: choose that Multi-Output Device
Or pass --device with part of another input's name. Inputs found: {inputs}"""


def open_capture(device=None):
    """(display name, soundcard microphone) for the system audio."""
    if hasattr(sc, 'SoundcardRuntimeWarning'):  # only the Windows backend has it
        warnings.filterwarnings('ignore', category=sc.SoundcardRuntimeWarning)  # "data discontinuity"
    if IS_MAC:
        name = device or MAC_DEFAULT_INPUT
        try:
            mic = sc.get_microphone(name)
        except IndexError:
            inputs = ', '.join(repr(m.name) for m in sc.all_microphones()) or 'none'
            raise SystemExit(MAC_HELP.format(name=name, inputs=inputs))
        return mic.name, mic
    speaker = sc.get_speaker(device) if device else sc.default_speaker()
    return speaker.name, sc.get_microphone(id=str(speaker.name), include_loopback=True)
