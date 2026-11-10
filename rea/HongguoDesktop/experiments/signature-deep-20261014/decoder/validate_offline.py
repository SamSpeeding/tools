"""Deterministic round trips for the independent inverse operations."""
import hashlib
import json
from pathlib import Path
import decode as d

checks = {}
for selector in range(4):
    aes = d.plugin.AES_V3(d.CONFIG_KEY, selector)
    block = hashlib.sha256(f'block-{selector}'.encode()).digest()[:16]
    checks[f'aes_block_selector_{selector}'] = aes.decrypt_block(aes.encrypt_block(block)) == block
    raw = b''.join(hashlib.sha256(f'data-{selector}-{i}'.encode()).digest() for i in range(12))
    encrypted = aes.encrypt(raw, d.CONFIG_IV)
    key = bytearray(aes.sum_data(encrypted[1:]))
    key[-1] = encrypted[0]
    recovered = aes.decrypt(key, d.CONFIG_IV, encrypted[1:])
    checks[f'aes_embedded_bits_selector_{selector}'] = recovered == raw

for size in [32,255,512,661]:
    value = bytes((i * 37 + 19) & 255 for i in range(size))
    key = hashlib.sha256(str(size).encode()).digest()
    checks[f'xmxor_{size}'] = d.inverse_xmxor(d.plugin._xmxor(value,key),key) == value

for aid,license in [('8662','1588093228'),('3019','1611921764')]:
    plaintext = f'1791944712-{license}-{aid}'.encode()
    encoded = d.encode_helios(plaintext,bytes.fromhex('12345678'))
    checks[f'helios_{aid}'] = d.decode_helios(encoded)['plaintext'].encode() == plaintext

report = {'scope':'Pure local arithmetic; no request or signer process.', 'checks':checks,
          'passed':sum(checks.values()),'total':len(checks)}
assert all(checks.values())
Path(__file__).with_name('offline-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
