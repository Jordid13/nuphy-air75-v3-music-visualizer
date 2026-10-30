"""Record what the visualizer hears (system audio loopback) to a WAV file, for tuning detection offline.
Doesn't touch the keyboard.   python record_audio.py [seconds] [--device "USB Audio"]"""
import sys
import time
import wave
import warnings

import numpy as np
import soundcard as sc

RATE = 48000
secs = float(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else 90
dev = sys.argv[sys.argv.index('--device') + 1] if '--device' in sys.argv else None
speaker = sc.get_speaker(dev) if dev else sc.default_speaker()
mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
out = f'capture_{time.strftime("%H%M%S")}.wav'

warnings.filterwarnings('ignore', category=sc.SoundcardRuntimeWarning)
print(f'recording {secs:.0f} s from {speaker.name} -> {out}')
print('start the song now; the clock below is the time to give me for quiet/loud parts')
chunks = []
with mic.recorder(samplerate=RATE, channels=2) as rec:
    t0 = time.perf_counter()
    last = -1
    while time.perf_counter() - t0 < secs:
        chunks.append(rec.record(numframes=RATE // 10))
        el = int(time.perf_counter() - t0)
        if el != last:
            last = el
            print(f'\r{el // 60}:{el % 60:02d}', end='', flush=True)
audio = np.concatenate(chunks)
pcm = (np.clip(audio, -1, 1) * 32767).astype('<i2')
with wave.open(out, 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(RATE)
    w.writeframes(pcm.tobytes())
print(f'\nsaved {out} ({len(audio) / RATE:.0f} s)')
