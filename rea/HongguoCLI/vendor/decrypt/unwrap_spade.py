"""Readable reconstruction of the bundled CPython 3.11 bytecode.

This is reconstructed Python, not the author's original source.  The legacy
``unwrap_spade.pyc`` is retained for comparison but is not loaded by this module.
The version-1 spade transform and its original CLI behavior are preserved.
"""

import base64


def _popcount(x):
    """Count set bits after restricting an integer to 32 bits."""
    return bin(x & 0xFFFFFFFF).count("1")


def _s8(v):
    """Interpret the low byte of an integer as a signed eight-bit value."""
    v &= 0xFF
    return v - 256 if v >= 128 else v


def _strncmp0(a, b, n):
    """Compare at most n bytes, treating missing bytes as a NUL terminator."""
    for k in range(n):
        ca = a[k] if k < len(a) else 0
        cb = b[k] if k < len(b) else 0
        if ca != cb:
            return False
        if ca == 0:
            return True
    return True


def unwrap_v1(spade, flag=0):
    """Unwrap a byte sequence or hex string; unsupported payloads return None.

    ``flag`` selects the arithmetic direction used by the original transform.
    As in the bytecode, a decoded value is returned as Latin-1 text; callers
    must separately validate whether it is a 32-character hexadecimal key.
    """
    if isinstance(spade, str):
        spade = bytes.fromhex(spade)
    length = len(spade)
    if length < 3:
        return None

    tag = spade[0] ^ spade[1] ^ spade[2]
    suffix_length = tag - 48
    if suffix_length < 1:
        return None
    payload_length = length - tag + 47
    if payload_length < 1 or 1 + payload_length > length:
        return None
    decoded = bytearray(spade[1:1 + payload_length])

    # The suffix identifies newer app/web variants that this v1 algorithm
    # intentionally does not handle.  Retain its C-style NUL comparison.
    suffix = bytearray(suffix_length)
    previous_even = spade[length - suffix_length - 2]
    previous_odd = spade[length - suffix_length - 1]
    for i in range(suffix_length):
        suffix[i] = previous_odd ^ previous_even ^ spade[i + length - suffix_length]
    if (_strncmp0(suffix, b"app_v2", suffix_length)
            or _strncmp0(suffix, b"web_v2", suffix_length)):
        return None

    previous_odd, previous_even = 85, 250
    for i in range(payload_length):
        current = decoded[i]
        bits = _popcount(i)
        next_even, next_odd = current, previous_odd
        if i & 1:
            next_even, next_odd, previous_even = previous_even, current, previous_odd
        delta = bits + 21 if flag else _s8(-21 - bits)
        decoded[i] = (delta + (previous_even ^ current)) & 0xFF
        previous_odd, previous_even = next_odd, next_even

    first = decoded[0]
    if 48 <= first <= 57:
        padding = first - 48
    elif 97 <= first <= 122:
        padding = first - 87
    else:
        return None
    end = payload_length - (padding & 0xFF)
    if end < 2:
        return None
    return bytes(decoded[1:end]).decode("latin1", "replace")


def spade_to_key(spade_a_b64, flag=0):
    """Decode an API's Base64 spade_a value and apply the v1 transform."""
    return unwrap_v1(base64.b64decode(spade_a_b64), flag)


# Original bundled known-answer vectors retained for regression tests.
_TRUTH = [
    ("93bc1df253ba1bf7618b19c448b806f64d810afc45b715fe5eb925f26cbf12f541ba098282",
     "287216bfa89e662a0f748120c305e199"),
    ("a1bc2ff164b91df04dbf00f17dba00f47cbb35c27b922aec67a628eb52972fdc7ea036a7a7",
     "d742b28967e4e6c92b699f4375add27f"),
    ("9cbc12fb588721cd69b739f977b70be7429c08e074990ec847843dcc738638cf76b33ebcbc",
     "113fb30d9767d80e3edbb905b052204f"),
    ("a3bc2df760ba2bc27b8b34c04a8907f557be19f249be35c748ba03f64fbc1ff161ba29a2a2",
     "b5674a8384f25d757585dadf343274d5"),
    ("9cbc12f45aba11f76fb814f444bd15f459b225cb5e8c15dd459a0fd170ac0ad358aa108b8b",
     "121846f9d5829130ebc0397023feaf8c"),
]


def _selftest():
    ok = 0
    for sp, expected in _TRUTH:
        got = unwrap_v1(sp, 0)
        hit = got == expected
        ok += hit
        print(f"{'OK ' if hit else 'FAIL'} {got} == {expected}")
    print(f"{ok}/{len(_TRUTH)} passed")
    return ok == len(_TRUTH)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        sp = sys.argv[1]
        flag = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        try:
            key = (spade_to_key(sp, flag)
                   if not all(c in "0123456789abcdefABCDEF" for c in sp)
                   else unwrap_v1(sp, flag))
        except Exception:
            key = unwrap_v1(sp, flag)
        print(key)
    else:
        _selftest()
