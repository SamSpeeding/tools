"""Local Helios + Medusa v3 for the verified aid=8662 request profile.

The caller owns URL construction, device selection, JSON serialization and the
JAR's other six headers. We sign their exact URL/body with the JAR's x-khronos;
we never read the wall clock, register devices, import a plugin or make requests.
The protocol is adapted from the audited reference, not a new cryptosystem.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import secrets
import struct
from urllib.parse import parse_qsl, urlsplit

from ._primitives import AES_V3, SM3, get_key_hash, hash_f13, rl8

APP_ID = "8662"
LICENSE_ID = "1588093228"  # Platform signing context, NOT a downloader activation code.
MAGIC = bytes.fromhex("f7e85ffad7d7dc3bd62ac87057cf6118")
CONFIG_KEY = bytes.fromhex("f1593376766ea98d34f31b057a9d5be4")
CONFIG_IV = bytes.fromhex("1fe109a4125283f418de9e051a969e12")
SIGN_KEY = bytes.fromhex("8ebdfa3806ecc5cee79423e6029ed82540bc2218bb7eaef71cb691f7aa8aa2f5")
SEED = (320).to_bytes(8, "little")
ENV_FLAGS = ('{"cmr":16777216,"cmr2":16777216,"un_h":1879194040,"vpn":0,'
             '"kd":0,"fkd":3672518972,"pd":-1872573247,"dyn":"","do":0,"tk":true}')


@dataclass(frozen=True)
class _Entropy:
    helios: int
    proto: int
    launch: int
    pid: int
    key_hash: int
    envelope: int


def _new_entropy() -> _Entropy:
    # Per-call values; no global random state or cross-thread clock monkeypatch.
    return _Entropy(secrets.randbits(32), secrets.randbits(32),
                    100 + secrets.randbelow(21), 10001 + secrets.randbelow(2000),
                    secrets.randbits(32), secrets.randbits(32))


def _ror64(value: int, count: int) -> int:
    return ((value >> count) | (value << (64 - count))) & 0xFFFFFFFFFFFFFFFF


def _helios(khronos: int, nonce: int) -> str:
    prefix = nonce.to_bytes(4, "little")
    # The MD5 *hex ASCII* is the 32-byte schedule input, not the 16-byte digest.
    key = hashlib.md5(prefix + APP_ID.encode()).hexdigest().encode()
    words = [int.from_bytes(key[i:i + 8], "little") for i in range(0, 32, 8)]
    schedule = [words[0]]
    left, right = words[:2]
    pending = words[2:]
    for index in range(34):
        mixed = ((_ror64(right, 8) + left) & 0xFFFFFFFFFFFFFFFF) ^ index
        pending.append(mixed)
        left = mixed ^ _ror64(left, 61)
        schedule.append(left)
        right = pending.pop(0)
    raw = f"{khronos}-{LICENSE_ID}-{APP_ID}".encode()
    padding = 16 - len(raw) % 16
    raw += bytes([padding]) * padding
    output = bytearray(prefix)
    for offset in range(0, len(raw), 16):
        left = int.from_bytes(raw[offset:offset + 8], "little")
        right = int.from_bytes(raw[offset + 8:offset + 16], "little")
        for round_key in schedule[:34]:
            right = (round_key ^ (left + _ror64(right, 8))) & 0xFFFFFFFFFFFFFFFF
            left = right ^ _ror64(left, 61)
        output.extend(left.to_bytes(8, "little") + right.to_bytes(8, "little"))
    return base64.b64encode(output).decode("ascii")


def _varint(value: int) -> bytes:
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _proto(fields) -> bytes:
    """Only the three wire types used here: zigzag integers, bytes and float32.

    Preserve the observed positive nonce encoding even above 2**31: do not cast
    it to a signed 32-bit integer before zigzag. Zero/default fields are omitted.
    """
    output = bytearray()
    for field, value in fields:
        if value in (None, "", b"", 0, 0.0):
            continue
        if isinstance(value, int):
            output.extend(_varint(field << 3))
            output.extend(_varint(value << 1 if value >= 0 else ~(value << 1)))
        elif isinstance(value, float):
            output.extend(_varint((field << 3) | 5))
            output.extend(struct.pack("<f", value))
        else:
            raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
            output.extend(_varint((field << 3) | 2) + _varint(len(raw)) + raw)
    return bytes(output)


def _environment(query: dict[str, str], khronos: int, entropy: _Entropy) -> bytes:
    """Keep the verified v3 environment template; it is NOT a macOS fingerprint.

    Historical sample times/battery/storage fields are protocol fixture values.
    The identity and App profile come from the final URL, never a new random ID.
    """
    model, brand = query.get("device_type", ""), query.get("device_brand", "")
    sample_time = 1728388016635
    device = _proto([
        (1, 1), (2, 2), (3, APP_ID), (4, query["device_id"]), (6, "!noperm!"),
        (7, -888888), (8, -888888), (9, 3), (10, -888888), (11, "!notset!"),
        (12, "Asia/Shanghai,8"), (13, "zh_CN"), (14, 4),
        (16, 255.24993896484375), (17, 35.58599090576172),
        (18, 3.467449188232422), (19, 3.467449188232422),
        (20, 255.1754913330078), (21, 42.17544174194336),
        (22, query.get("os_version", "")), (23, 41), (24, 36),
        (25, sample_time), (26, sample_time), (27, sample_time), (28, sample_time + 2),
        (29, -1), (30, model), (31, brand), (32, model), (33, model),
        (34, brand), (35, brand), (36, brand), (38, 31),
    ])
    return _proto([
        (1, entropy.launch), (2, 146331399), (3, 146331396), (5, 7),
        (6, "v04.06.04.03-bugfix"), (7, entropy.pid), (12, device),
        (13, _proto([(1, khronos), (2, -2), (4, 200)])),
        (14, query["version_name"]),
    ])


def _payload(raw_query: str, query: dict[str, str], body: bytes | None,
             khronos: int, entropy: _Entropy) -> tuple[bytes, bytes, bytes]:
    # Hash the untouched encoded query and the exact bytes sent on the wire.
    query_hash = SM3(raw_query).digest()
    body_md5 = hashlib.md5(body).digest() if body else bytes(16)
    binding = hash_f13(query_hash, body_md5, khronos.to_bytes(4, "little"), khronos)
    payload = _proto([
        (1, MAGIC), (2, 3), (3, entropy.proto), (4, APP_ID),
        (5, query["device_id"]), (6, LICENSE_ID), (7, query["version_name"]),
        (8, "v04.06.04-ml-android"), (9, 67503104), (10, SEED),
        (12, khronos), (13, binding), (14, query_hash[:6]),
        (15, _proto([(1, 111), (2, 10), (3, 694367), (5, 586952199)])),
        (17, khronos), (19, SM3(raw_query.encode() + body_md5 + b"none").digest()),
        (20, "none"), (21, 312), (23, _environment(query, khronos, entropy)),
        (24, ENV_FLAGS),
    ])
    return payload, query_hash, binding


def _mix_payload(data: bytes, key: bytes) -> bytearray:
    mixed = bytearray(len(data))
    for index, value in enumerate(data):
        offset = (index * 4) & 28
        first, second = key[offset:offset + 2]
        value = (rl8(value, 4) + first) ^ second
        value = rl8((~value) & 255, 3)
        value = ((value + second) & 255) ^ first
        mixed[-index - 1] = (~value) & 255
    flag, initial = mixed[-1] ^ mixed[-2], mixed[0]
    mixed[0] = (~flag + mixed[0]) & 255
    mixed[1] = ((mixed[0] ^ mixed[-1] ^ 254) + mixed[1]) & 255
    mixed[2] = (mixed[2] + ((flag - initial) ^ rl8(mixed[1], 3) ^ 2)) & 255
    for index in range(len(mixed) - 4):
        mask = rl8(mixed[index + 2], 3) ^ mixed[index + 1] ^ (index + 3)
        mixed[index + 3] = (~mask + mixed[index + 3]) & 255
    mixed[-1] ^= mixed[-2]
    mixed[0] = ((mixed[0] ^ mixed[1]) + sum(mixed[1:])) & 255
    return mixed


def _medusa(raw_query: str, query: dict[str, str], body: bytes | None,
            khronos: int, entropy: _Entropy) -> str:
    payload, query_hash, binding = _payload(raw_query, query, body, khronos, entropy)
    key, seed = get_key_hash(SIGN_KEY, entropy.key_hash)
    mixed = (SEED + _mix_payload(payload, key))[::-1]
    mixed = bytes(value ^ seed[~index & 3] for index, value in enumerate(mixed))
    nonce = entropy.key_hash.to_bytes(4, "little")
    check = ((query_hash[0] & 63) << 14) | 0x18000001 | ((binding[0] & 63) << 8)
    inner = (b"\x35" + entropy.envelope.to_bytes(4, "little")
             + check.to_bytes(4, "little") + mixed + nonce[2:])
    # This embeds custom cipher bits; it is not standard AES-CBC/CTR.
    encrypted = AES_V3(CONFIG_KEY, khronos).encrypt(inner, CONFIG_IV)
    version = (3).to_bytes(4, "little") + MAGIC
    envelope = b"".join((int.from_bytes(version[i:i + 4], "little") ^ khronos)
                        .to_bytes(4, "little") for i in range(0, 20, 4))
    return base64.b64encode(envelope + nonce[:2] + b"\x00\x01" + encrypted).decode("ascii")


def generate_headers(url: str, body: bytes | None, khronos: int) -> dict[str, str]:
    """Return only x-helios/x-medusa. Inputs are final, already serialized values.

    A fresh pair is generated for every request; no saved signatures are reused.
    This module supports the verified aid=8662 profile only. It does not infer or
    repair missing identity fields, or claim the device has been registered.
    """
    if type(khronos) is not int or not 0 < khronos < 2**32:
        raise ValueError("x-khronos must be a positive uint32 Unix timestamp")
    if body is not None and not isinstance(body, bytes):
        raise TypeError("body must be the final bytes, not a JSON object or string")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.fragment:
        raise ValueError("signing requires a final HTTPS URL without a fragment")
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query = dict(pairs)
    if len(query) != len(pairs):
        raise ValueError("duplicate query parameters are ambiguous for Medusa")
    if query.get("aid") != APP_ID:
        raise ValueError("local Helios/Medusa supports only aid=8662")
    if not query.get("device_id") or not query.get("version_name"):
        raise ValueError("final URL must include device_id and version_name")
    entropy = _new_entropy()
    return {"x-helios": _helios(khronos, entropy.helios),
            "x-medusa": _medusa(parsed.query, query, body, khronos, entropy)}


def model_headers(url: str, body: bytes | None, headers: dict[str, str]) -> dict[str, str]:
    """Bind our two replacement headers to the JAR's timestamp and body stub.

    Invalid/missing inputs fail before sending, never silently revert to the
    known failing JAR pair. The caller keeps all other normalized headers intact.
    """
    timestamp = headers.get("x-khronos", "")
    if not isinstance(timestamp, str) or not timestamp.isascii() or not timestamp.isdigit():
        raise ValueError("JAR response has no valid x-khronos")
    if body is not None and headers.get("x-ss-stub", "").lower() != hashlib.md5(body).hexdigest():
        raise ValueError("x-ss-stub does not match the final request body")
    return generate_headers(url, body, int(timestamp))
