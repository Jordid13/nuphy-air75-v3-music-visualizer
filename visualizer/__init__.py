"""The visualizer's modules: keyboard driver (nuphy), key layout, audio capture, settings page.
Run the visualizer with spectrum.py in the project root."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')        # per-machine files: profiles, saved lighting, logs (not in git)
os.makedirs(DATA_DIR, exist_ok=True)
