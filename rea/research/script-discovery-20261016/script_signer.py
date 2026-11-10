"""Research-only pure Python equivalent of the verified standalone PHP policy.

H/M use our existing audited Python module. Gorgon follows hg_gorgon in
HongguoPHP/video.php, including its nonstandard overwrite-only RC4 variant.
Argus/Ladon here are the reference combination's timestamp encodings, NOT
complete implementations of the original JAR algorithms. No Neptune/Soter.
No subprocess, network, device generation, JAR, or original native signer libs.
"""
import base64
import hashlib
import secrets
import struct
import time
from urllib.parse import urlsplit

from hongguo_hm import generate_headers


def gorgon(query: str, body: bytes | None, ts: int, nonce: int) -> str:
    raw = (hashlib.md5(query.encode()).digest()[:4]
           + (hashlib.md5(body).digest()[:4] if body else bytes(4))
           + bytes(4) + struct.pack('<I', 67503104) + struct.pack('>I', ts))
    key = [0x4a, 0x40, 0x16, (nonce >> 8) & 255, 0x47, 0x6c, 1, nonce & 255]
    table = list(range(256))
    j = 0
    for i in range(256):
        j = (j + table[i] + key[i % 8]) & 255
        table[i] = table[j]  # overwrite; intentionally NOT an RC4 swap
    i = j = 0
    result = []
    for v in raw:
        i = (i + 1) & 255
        j = (j + table[i]) & 255
        y = table[j]
        table[i] = y
        result.append(v ^ table[(y + y) & 255])
    for i, v in enumerate(result):
        swapped = ((v >> 4) | (v << 4)) & 255
        following = result[i + 1] if i + 1 < len(result) else result[0]
        x = following ^ swapped
        reverse = sum(((x >> b) & 1) << (7-b) for b in range(8))
        result[i] = (~(reverse ^ 20)) & 255
    return (b'\x84\x04' + struct.pack('<HH', nonce, 320) + bytes(result)).hex()


def sign(url: str, body: bytes | None) -> dict[str, str]:
    ts = int(time.time())
    return {
        **generate_headers(url, body, ts),
        'x-khronos': str(ts),
        'x-gorgon': gorgon(urlsplit(url).query, body, ts, secrets.randbelow(65536)),
        'x-argus': base64.b64encode(struct.pack('<I', ts)).decode(),
        'x-ladon': base64.b64encode(struct.pack('>I', ts)).decode(),
    }
