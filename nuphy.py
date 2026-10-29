"""Minimal driver for the NuPhy Air75 V3 config channel (USB 19F5:1028, HID interface 3).

Frame (64 bytes, no report ID):
  [0] 0x55 request / 0xAA reply
  [1] command
  [2] 0x00
  [3] checksum = sum(bytes 4..63) & 0xFF
  [4..] payload XOR session key, then zero padding (not XORed)

The session key is set by the host on connect with SetSecretKey (0xEE): 56 random bytes at
offset 8, key = random[20] (or 170 if 0). It lasts until the next SetSecretKey, so NuPhy IO
reconnecting changes it — close NuPhy IO while using this. Command names come from NuPhy IO's
bundle; never send 0xF1 RestoreFactory or 0xEF SetIapMode (bootloader).

Payload for read (0xD5) / write (0xD6): [len][addr lo][addr hi][bank][data...]
(0xD2 is what NuPhy IO polls for the key-press page; it returns 0xC8 filler for bank 1.)

Bank 1 lighting block:
  0  effect      1  brightness 0-100   2  speed    3-5  ?    6-8  R,G,B   (main backlight)
  9  effect     10  brightness 0-100  11  speed   14-16 R,G,B           (side light)

Side effects (from NuPhy IO): 0 across, 1 rainbow, 2 static, 3 breathe, 4 rhythm.
Main effect 21 = SIGNAL_CUSTOM_MODE (per-LED; NuPhy IO offers it from firmware 1.0.16.6).
Air75 V3 LED count: 84 key + 20 side (side = last 20 of the per-LED array).
"""
import os

import hid

VID, PID, IFACE = 0x19F5, 0x1028, 3
CMD_READ, CMD_WRITE = 0xD5, 0xD6     # GetLightState / SetLightState
CMD_SIGNAL = 0xD8                    # SetSignalColor: per-LED colors in custom mode (main effect 21)
MAIN_CUSTOM = 21
CMD_SET_KEY = 0xEE                   # SetSecretKey
BANK_LIGHT = 1
SIDE = 9  # side light block starts here


def checksum(pkt):
    return sum(pkt[4:]) & 0xFF


def frame(cmd, plain, key):
    body = bytes(b ^ key for b in plain)
    pkt = bytearray(64)
    pkt[0], pkt[1] = 0x55, cmd
    pkt[4:4 + len(body)] = body
    pkt[3] = checksum(pkt)
    return bytes(pkt)


def key_frame(rand):
    """SetSecretKey packet as NuPhy IO builds it (byte 4 is window.length there, i.e. 0)."""
    pkt = bytearray(64)
    pkt[0], pkt[1] = 0x55, CMD_SET_KEY
    pkt[8:64] = rand
    pkt[3] = checksum(pkt)
    return bytes(pkt)


class Keyboard:
    def __init__(self):
        path = next(d['path'] for d in hid.enumerate(VID, PID) if d['interface_number'] == IFACE)
        self.dev = hid.device()
        self.dev.open_path(path)
        self.history = []
        for attempt in range(5):
            self.key = self._set_key()
            if self._key_ok():
                break
            import time as _t
            _t.sleep(0.05)        # keyboard was busy (e.g. saving settings) and missed the key; retry
        else:
            raise RuntimeError('keyboard did not accept a session key after 5 tries')

    def _key_ok(self):
        """GetAppDefine (0xFB) reply byte 8 decodes to 0 only if the keyboard uses our key."""
        r = self._xfer(0xFB, bytes([0x01, 0xA8, 0, 0]))
        return (r[8] ^ self.key) == 0

    def close(self):
        self.dev.close()

    def _set_key(self):
        rand = os.urandom(56)
        self.dev.write(b'\x00' + key_frame(rand))
        while True:
            r = self.dev.read(64, 500)
            if not r:
                raise TimeoutError('no reply to SetSecretKey')
            if r[0] == 0xAA and r[1] == CMD_SET_KEY:
                return rand[20] or 170

    def dump_history(self, path, note=''):
        """Write the last packets sent (plaintext) to a file — for diagnosing keyboard crashes."""
        import time as _t
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f'--- {_t.strftime("%Y-%m-%d %H:%M:%S")} {note}\n')
            for t, cmd, plain in self.history:
                f.write(f'{t:10.3f} cmd {cmd:#04x} {plain.hex(" ")}\n')

    def _xfer(self, cmd, plain, timeout_ms=500):
        import time as _t
        self.history.append((_t.perf_counter(), cmd, bytes(plain)))
        del self.history[:-30]
        req = frame(cmd, plain, self.key)
        self.dev.write(b'\x00' + req)  # leading 0 = no report ID
        while True:
            r = self.dev.read(64, timeout_ms)
            if not r:
                raise TimeoutError(f'no reply to cmd {cmd:#04x}')
            # other readers (NuPhy IO polling) see the same input reports; match ours
            if r[0] == 0xAA and r[1] == cmd and bytes(r[4:8]) == req[4:8]:
                return bytes(r)

    def read(self, bank, addr, length):
        # firmware ignores the read address and always returns from 0, so read up to addr+length and slice
        n = addr + length
        r = self._xfer(CMD_READ, bytes([n, 0, 0, bank]))
        return bytes(b ^ self.key for b in r[8:8 + n])[addr:]

    def write(self, bank, addr, data, allow_lock=False):
        # side effect values >= 5 put the side light in a state that ignores later effect writes
        # (happened twice; only a factory reset cleared it). allow_lock=True for deliberate experiments.
        if (not allow_lock and bank == BANK_LIGHT and addr <= SIDE < addr + len(data)
                and data[SIDE - addr] > 4):
            raise ValueError(f'refusing side effect {data[SIDE - addr]} (>4 locks the side light)')
        # Changing the side speed while the side effect is — or is being switched from/to — static (2) or
        # rhythm (4), the effects with no speed setting, locks the speed setting until a factory reset
        # (happened three times). So: never change speed in such a write. Switching to an effect that has
        # a speed is done in two steps: effect first (old speed kept), then the speed on its own.
        sp = SIDE + 2
        set_speed_after = None
        if bank == BANK_LIGHT and addr <= sp < addr + len(data):
            cur_effect, cur_speed = self.read(BANK_LIGHT, SIDE, 3)[0], self.read(BANK_LIGHT, sp, 1)[0]
            new_effect = data[SIDE - addr] if addr <= SIDE else cur_effect
            want = data[sp - addr]
            if want != cur_speed and (cur_effect in (2, 4) or new_effect in (2, 4)):
                data = bytearray(data)
                data[sp - addr] = cur_speed
                if new_effect not in (2, 4):
                    set_speed_after = want
            # Side speed 4 locks the speed setting (every lock so far ended stuck at 4): only 0-3 may be
            # written, unless 4 is already stored. (0 was tested deliberately and is fine.)
            final = set_speed_after if set_speed_after is not None else data[sp - addr]
            if final == 4 and final != cur_speed:
                raise ValueError('refusing side speed 4 (locks the speed setting); use 0-3')
        self._write_raw(bank, addr, data)
        if set_speed_after is not None:
            self._write_raw(bank, sp, [set_speed_after])

    def _write_raw(self, bank, addr, data):
        self._xfer(CMD_WRITE, bytes([len(data), addr & 0xFF, addr >> 8, bank]) + bytes(data))

    def set_leds(self, leds):
        """leds: iterable of (index, r, g, b). Sent as SetSignalColor records, 14 per packet.
        Matches NuPhy IO: addr = byte offset of the first record (index * 4)."""
        leds = list(leds)
        for i in range(0, len(leds), 14):
            chunk = leds[i:i + 14]
            data = b''.join(bytes(rec) for rec in chunk)
            addr = chunk[0][0] * 4
            self._xfer(CMD_SIGNAL, bytes([len(data), addr & 0xFF, addr >> 8, BANK_LIGHT]) + data)


if __name__ == '__main__':
    # Self-check against packets captured from NuPhy IO
    assert frame(CMD_WRITE, bytes.fromhex('01010001 64'), 0xF1).hex(' ').startswith('55 d6 00 56 f0 f0 f1 f0 95')
    assert frame(CMD_READ, bytes.fromhex('11000001'), 0xF1).hex(' ').startswith('55 d5 00 b2 e0 f1 f1 f0')
    print('framing ok')
