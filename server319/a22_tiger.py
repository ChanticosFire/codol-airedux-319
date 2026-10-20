# Vendored from codol-ember/工具-tools/launch319-reference/reference/launch/demonware/a22_tiger.py.
# Tiger/192 for the 0.0.2.2 auth ticket.
#
# The S-boxes live in tiger_sboxes.py, generated from Servers/Shared/Tiger.cs.  They used to be
# parsed out of that file at import time, but it sits two levels ABOVE the server tree, so a lobby
# deployed without it (the container, a VPS) failed this import, fell back to a zeroed auth
# ticket, and every client was refused with 716 INCORRECT_PASSWORD.  The self-test below still
# checks the baked tables against the client's own digests.
#
# SELF-TEST: the live Frida trace (re/alpha0022/recv-trace.log) captured two real input/output
# pairs from the client's own Tiger, so this module can be checked against the actual binary rather
# than against a spec:
# Publication omits the client-derived password test vector.
#     Tiger("ym9iewfdbgllbnq=") -> 588c2e26dab3b8c7...
# Run this file directly to verify both.

import struct

from .tiger_sboxes import T1, T2, T3, T4

M64 = (1 << 64) - 1


def _round(a, b, c, x, mul):
    c = (c ^ x) & M64
    a = (a - (T1[c & 0xFF] ^ T2[(c >> 16) & 0xFF] ^
              T3[(c >> 32) & 0xFF] ^ T4[(c >> 48) & 0xFF])) & M64
    b = (b + (T4[(c >> 8) & 0xFF] ^ T3[(c >> 24) & 0xFF] ^
              T2[(c >> 40) & 0xFF] ^ T1[(c >> 56) & 0xFF])) & M64
    b = (b * mul) & M64
    return a, b, c


def _pass(a, b, c, x, mul):
    a, b, c = _round(a, b, c, x[0], mul)
    b, c, a = _round(b, c, a, x[1], mul)
    c, a, b = _round(c, a, b, x[2], mul)
    a, b, c = _round(a, b, c, x[3], mul)
    b, c, a = _round(b, c, a, x[4], mul)
    c, a, b = _round(c, a, b, x[5], mul)
    a, b, c = _round(a, b, c, x[6], mul)
    b, c, a = _round(b, c, a, x[7], mul)
    return a, b, c


def _key_schedule(x):
    x = list(x)
    x[0] = (x[0] - (x[7] ^ 0xA5A5A5A5A5A5A5A5)) & M64
    x[1] ^= x[0]
    x[2] = (x[2] + x[1]) & M64
    x[3] = (x[3] - (x[2] ^ ((~x[1] & M64) << 19) & M64)) & M64
    x[4] ^= x[3]
    x[5] = (x[5] + x[4]) & M64
    x[6] = (x[6] - (x[5] ^ ((~x[4] & M64) >> 23))) & M64
    x[7] ^= x[6]
    x[0] = (x[0] + x[7]) & M64
    x[1] = (x[1] - (x[0] ^ ((~x[7] & M64) << 19) & M64)) & M64
    x[2] ^= x[1]
    x[3] = (x[3] + x[2]) & M64
    x[4] = (x[4] - (x[3] ^ ((~x[2] & M64) >> 23))) & M64
    x[5] ^= x[4]
    x[6] = (x[6] + x[5]) & M64
    x[7] = (x[7] - (x[6] ^ 0x0123456789ABCDEF)) & M64
    return x


def _compress(state, block):
    a, b, c = state
    aa, bb, cc = a, b, c
    x = list(struct.unpack('<8Q', block))
    # The reference macro is
    #     pass(a,b,c,5)  key_schedule  pass(c,a,b,7)  key_schedule  pass(b,c,a,9)
    # i.e. a/b/c are PERSISTENT variables passed in a different ORDER each time -- not values
    # rotated between passes. Rotating the values instead produces a plausible-looking but wrong
    # digest, which is what the first cut did.
    a, b, c = _pass(a, b, c, x, 5)
    x = _key_schedule(x)
    c, a, b = _pass(c, a, b, x, 7)
    x = _key_schedule(x)
    b, c, a = _pass(b, c, a, x, 9)
    a ^= aa
    b = (b - bb) & M64
    c = (c + cc) & M64
    return [a & M64, b, c]


def tiger(data, pad=0x01):
    """Tiger/192. pad=0x01 is Tiger1 (the bdSDK / TencentAuth `new Tiger(1)` variant)."""
    state = [0x0123456789ABCDEF, 0xFEDCBA9876543210, 0xF096A5B4C3B2E187]
    n = len(data)
    buf = bytearray(data)
    buf.append(pad)
    while len(buf) % 64 != 56:
        buf.append(0)
    buf += struct.pack('<Q', n * 8)
    for off in range(0, len(buf), 64):
        state = _compress(state, bytes(buf[off:off + 64]))
    return struct.pack('<3Q', *state)


if __name__ == '__main__':
    # Both vectors are the CLIENT's own output, captured live -- not spec test vectors.
    cases = [
        (b"ym9iewfdbgllbnq=",
         "588c2e26dab3b8c7", "first 8 bytes = the request's constant tail"),
    ]
    ok = True
    for data, expect, what in cases:
        got = tiger(data).hex()
        good = got.startswith(expect)
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  Tiger({data.decode()!r})")
        print(f"      got      {got}")
        print(f"      expected {expect}{'...' if len(expect) < 48 else ''}   <- {what}")
    print("\nALL PASS" if ok else "\nMISMATCH - do not use")

