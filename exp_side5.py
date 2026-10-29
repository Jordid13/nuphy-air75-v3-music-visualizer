"""Experiment: put the side light in effect 5 (LOCKS it — factory reset afterwards),
then see whether per-LED colors or the side color reach the strips in that mode.
Asks what you see after each step and saves the answers to exp_side5_answers.json."""
import json
import time
from nuphy import Keyboard, BANK_LIGHT, SIDE

OUT = 'exp_side5_answers.json'
answers = {}


def ask(key, question):
    answers[key] = input(f'\n{question}\n> ').strip()
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(answers, f, indent=1)


kb = Keyboard()
try:
    answers['side_before'] = kb.read(BANK_LIGHT, SIDE, 8).hex(' ')
    ask('baseline', 'BEFORE: what are the side strips doing right now (effect, colors)? Press Enter after answering to start.')

    kb.write(BANK_LIGHT, SIDE, [5], allow_lock=True)
    time.sleep(1)
    ask('A', 'STEP A (side effect 5): what do the LEFT and RIGHT strips look like? Colors, how many LEDs lit, any movement?')

    kb.set_leds([(i, 255, 0, 0) for i in range(83, 111)])
    time.sleep(1)
    ask('B', 'STEP B (sent red to LEDs 83-110): did anything on either strip change? Which LEDs, what color?')

    kb.set_leds([(i, 255, 0, 0) for i in range(83, 93)] + [(i, 0, 0, 255) for i in range(93, 111)])
    time.sleep(1)
    ask('C', 'STEP C (83-92 red, 93-110 blue): any change? Is one strip red and the other blue, or a mix?')

    kb.write(BANK_LIGHT, SIDE + 5, [0, 255, 0])
    time.sleep(1)
    ask('D', 'STEP D (side color set to green): did either strip turn green, fully or partly?')

    kb.write(BANK_LIGHT, SIDE + 1, [10])
    time.sleep(1)
    ask('E', 'STEP E (side brightness 10): did the strips dim? Both, or only one?')

    answers['side_after'] = kb.read(BANK_LIGHT, SIDE, 8).hex(' ')
    ask('notes', 'Anything else you noticed (keys, knob area, blinking)? Enter to finish.')
    print(f'\nSaved to {OUT}. Tell Claude you are done, then factory reset.')
finally:
    kb.close()
