"""Offline decoders for locally captured experimental signatures. No networking."""
from __future__ import annotations
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys

APP = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(APP / '.runtime/site-packages'))
SCRIPT = Path('/Users/tt/Downloads/红果短剧.py')
spec = importlib.util.spec_from_file_location('offline_studied_script', SCRIPT)
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
# The supplied script ships decryption helpers but never initializes this inverse
# lookup (normal signing calls encryption only). Populate a separate imported module.
for quadrant in range(4):
    for index, value in enumerate(plugin.s_box[quadrant * 256:(quadrant + 1) * 256]):
        plugin.inv_s_box[quadrant * 256 + value] = index

MASK64 = (1 << 64) - 1
CONFIG_KEY = b'\xf1Y3vvn\xa9\x8d4\xf3\x1b\x05z\x9d[\xe4'
CONFIG_IV = b'\x1f\xe1\t\xa4\x12R\x83\xf4\x18\xde\x9e\x05\x1a\x96\x9e\x12'
SIGN_KEY = b'\x8e\xbd\xfa8\x06\xec\xc5\xce\xe7\x94#\xe6\x02\x9e\xd8%@\xbc"\x18\xbb~\xae\xf7\x1c\xb6\x91\xf7\xaa\x8a\xa2\xf5'

def _rol64(x, n):
    return ((x << n) | (x >> (64 - n))) & MASK64

def helios_schedule(random_bytes, app_id='8662'):
    keys = hashlib.md5(random_bytes + app_id.encode()).hexdigest().encode()
    words = [int.from_bytes(keys[i:i + 8], 'little') for i in range(0, 32, 8)]
    table = [words[0]]
    first, second = words[:2]
    words = words[2:]
    for index in range(34):
        value = ((plugin._ror64(second, 8) + first) & MASK64) ^ index
        words.append(value)
        value ^= plugin._ror64(first, 61)
        table.append(value)
        first, second = value, words.pop(0)
    return table

def encode_helios(raw, random_bytes, app_id='8662'):
    table = helios_schedule(random_bytes, app_id)
    pad = 16 - len(raw) % 16
    raw += bytes([pad]) * pad
    output = bytearray(random_bytes)
    for offset in range(0, len(raw), 16):
        left = int.from_bytes(raw[offset:offset + 8], 'little')
        right = int.from_bytes(raw[offset + 8:offset + 16], 'little')
        for index in range(34):
            right = (table[index] ^ (left + plugin._ror64(right, 8))) & MASK64
            left = right ^ plugin._ror64(left, 61)
        output += left.to_bytes(8, 'little') + right.to_bytes(8, 'little')
    return base64.b64encode(output).decode()

def decode_helios(header, app_id='8662'):
    wire = base64.b64decode(header, validate=True)
    random_bytes, ciphertext = wire[:4], wire[4:]
    assert len(ciphertext) % 16 == 0
    table = helios_schedule(random_bytes, app_id)
    raw = bytearray()
    for offset in range(0, len(ciphertext), 16):
        left = int.from_bytes(ciphertext[offset:offset + 8], 'little')
        right = int.from_bytes(ciphertext[offset + 8:offset + 16], 'little')
        for index in range(33, -1, -1):
            left = plugin._ror64(left ^ right, 3)
            right = _rol64(((right ^ table[index]) - left) & MASK64, 8)
        raw += left.to_bytes(8, 'little') + right.to_bytes(8, 'little')
    pad = raw[-1]
    assert 1 <= pad <= 16 and raw[-pad:] == bytes([pad]) * pad
    plaintext = bytes(raw[:-pad])
    assert encode_helios(plaintext, random_bytes, app_id) == header
    fields = plaintext.decode().split('-')
    return {'plaintext': plaintext.decode(), 'khronos': int(fields[0]),
            'license_id': fields[1], 'app_id': fields[2],
            'random': int.from_bytes(random_bytes, 'little'), 'roundtrip': True}

def inverse_xmxor(encoded, key):
    value = bytearray(encoded)
    # Reverse the final checksum and chained mutation in exact reverse order.
    value[0] = ((value[0] - sum(value[1:])) & 255) ^ value[1]
    value[-1] ^= value[-2]
    for index in range(len(value) - 5, -1, -1):
        temp = plugin.rl8(value[index + 2], 3) ^ value[index + 1] ^ (index + 3)
        value[index + 3] = (value[index + 3] - ~temp) & 255
    last_flag = value[-1] ^ value[-2]
    data0 = (value[0] - ~last_flag) & 255
    value[2] = (value[2] - ((last_flag - data0) ^ plugin.rl8(value[1], 3) ^ 2)) & 255
    value[1] = (value[1] - (value[0] ^ value[-1] ^ 254)) & 255
    value[0] = data0
    result = bytearray(len(value))
    for index in range(len(value)):
        pos = (index * 4) & 28
        d0, d1 = key[pos], key[pos + 1]
        step = (((~value[-index - 1]) & 255) ^ d0) - d1
        step = (~plugin.rl8(step & 255, 5)) & 255
        step = ((step ^ d1) - d0) & 255
        result[index] = plugin.rl8(step, 4)
    assert plugin._xmxor(result, key) == encoded
    return bytes(result)

def _varint(raw, offset):
    result = shift = 0
    while offset < len(raw):
        current = raw[offset]
        offset += 1
        result |= (current & 127) << shift
        if current < 128:
            return result, offset
        shift += 7
        if shift > 70:
            raise ValueError('invalid varint')
    raise ValueError('truncated varint')

def parse_proto(raw):
    result = []
    offset = 0
    while offset < len(raw):
        start = offset
        tag, offset = _varint(raw, offset)
        number, wire = tag >> 3, tag & 7
        assert number > 0
        if wire == 0:
            value, offset = _varint(raw, offset)
            item = {'number': number, 'wire': wire, 'uint': value,
                    'sint': (value >> 1) ^ -(value & 1)}
        elif wire == 2:
            length, offset = _varint(raw, offset)
            value = raw[offset:offset + length]
            assert len(value) == length
            offset += length
            item = {'number': number, 'wire': wire, 'bytes_hex': value.hex()}
            try:
                item['utf8'] = value.decode('utf-8')
            except UnicodeDecodeError:
                pass
        elif wire in (1, 5):
            length = 8 if wire == 1 else 4
            value = raw[offset:offset + length]
            assert len(value) == length
            offset += length
            item = {'number': number, 'wire': wire, 'bytes_hex': value.hex()}
            if wire == 5:
                item['float'] = struct.unpack('<f', value)[0]
        else:
            raise ValueError(f'unsupported wire {wire} at {start}')
        item['raw_hex'] = raw[start:offset].hex()
        result.append(item)
    assert b''.join(bytes.fromhex(f['raw_hex']) for f in result) == raw
    return result

MEDUSA_SCHEMA = {
    1: ('magic', 'bytes'), 2: ('version', 'sint'), 3: ('rand', 'sint'),
    4: ('ms_app_id', 'string'), 5: ('device_id', 'string'), 6: ('license_id', 'string'),
    7: ('app_version', 'string'), 8: ('sdk_version_str', 'string'), 9: ('sdk_version', 'sint'),
    10: ('xg_seed_bytes', 'bytes'), 12: ('time', 'sint'), 13: ('query_body_ts_hash', 'bytes'),
    14: ('query_sm3', 'bytes'), 15: ('request', 'request'), 16: ('sec_device_token', 'string'),
    17: ('time2', 'sint'), 18: ('lanusk_hash', 'bytes'), 19: ('query_body_hash_sm3', 'bytes'),
    20: ('psk_version', 'string'), 21: ('call_type', 'sint'), 23: ('env', 'env'),
    24: ('unknown24', 'string'), 26: ('original', 'string')}
ENV_SCHEMA = {
    1: ('launch_time','sint'), 2: ('unknown2','sint'), 3: ('unknown3','sint'),
    5: ('unknown5','sint'), 6: ('version','string'), 7: ('pid','sint'),
    12: ('device','device'), 13: ('report','report'), 14: ('app_version','string'),
    **{i:(f'unknown{i}','sint') for i in [15,16,18,19,20,21]}}
DEVICE_FIELDS = '''d1 collect_stat aid device_id sec_device_token app_version battery battery2 battery_health battery_changed network tz lan cpu resolution sdcard sdcard_used memory memory2 data data_used os_version brightness volume ts ts2 ts3 ts4 usb hw_version brand board product_name product_device product_manufacturer hardware'''.split()
DEVICE_STRINGS = {3,4,5,6,11,12,13,15,22,30,31,32,33,34,35,36}
DEVICE_SCHEMA = {i:(name,'string' if i in DEVICE_STRINGS else 'float' if 16 <= i <= 21 else 'sint') for i,name in enumerate(DEVICE_FIELDS,1)}
DEVICE_SCHEMA.update({38:('unknown38','sint'),40:('unknown40','sint')})
SCHEMAS = {'medusa':MEDUSA_SCHEMA,'env':ENV_SCHEMA,'device':DEVICE_SCHEMA,
           'request':{i:(f'field{i}','sint') for i in [1,2,3,5]},
           'report':{1:('time','sint'),2:('state','sint'),4:('code','sint'),5:('times','sint'),6:('unknown6','sint')}}

def named_proto(raw, schema='medusa'):
    values = {}
    for field in parse_proto(raw):
        name, kind = SCHEMAS[schema].get(field['number'], (f"unknown_field_{field['number']}", 'unknown'))
        if kind == 'string':
            value = bytes.fromhex(field['bytes_hex']).decode()
        elif kind in {'sint','float'}:
            value = field[kind]
        elif kind in SCHEMAS:
            value = named_proto(bytes.fromhex(field['bytes_hex']), kind)
        else:
            value = field.get('bytes_hex', field)
        assert name not in values
        values[name] = value
    return values

def medusa_envelope(header, khronos):
    wire = base64.b64decode(header, validate=True)
    version = b''.join((int.from_bytes(wire[i:i + 4], 'little') ^ khronos).to_bytes(4, 'little') for i in range(0, 20, 4))
    return {'version':int.from_bytes(version[:4],'little'), 'magic_hex':version[4:].hex(),
            'envelope_flag':int.from_bytes(wire[22:24],'little'), 'wire_length':len(wire)}

def decode_medusa(header, khronos):
    wire = base64.b64decode(header, validate=True)
    version = b''.join((int.from_bytes(wire[i:i + 4], 'little') ^ khronos).to_bytes(4, 'little') for i in range(0, 20, 4))
    if int.from_bytes(version[:4], 'little') != 3:
        raise NotImplementedError('Only Medusa v3 inner decoding is verified')
    aes = plugin.AES_V3(CONFIG_KEY, khronos)
    encrypted_mix = wire[25:]
    encrypted_key = bytearray(aes.sum_data(encrypted_mix))
    encrypted_key[-1] = wire[24]
    mixed = bytes(aes.decrypt(encrypted_key, CONFIG_IV, encrypted_mix))
    assert aes.encrypt(mixed, CONFIG_IV) == wire[24:]
    hash_bytes = wire[20:22] + mixed[-2:]
    hash_rand = int.from_bytes(hash_bytes, 'little')
    key, seed = plugin.get_key_hash(SIGN_KEY, hash_rand)
    inner = bytearray(mixed[9:-2])
    for index in range(len(inner)):
        inner[index] ^= seed[~index & 3]
    inner.reverse()
    xg_seed = inner[:8]
    proto = inverse_xmxor(inner[8:], key)
    fields = parse_proto(proto)
    # Complete round trip from recovered protobuf to the original wire signature.
    remixed = bytearray((xg_seed + plugin._xmxor(proto, key))[::-1])
    for index in range(len(remixed)):
        remixed[index] ^= seed[~index & 3]
    remixed = mixed[:9] + remixed + hash_bytes[2:]
    rebuilt = wire[:24] + aes.encrypt(remixed, CONFIG_IV)
    assert base64.b64encode(rebuilt).decode() == header
    return {'version_hex': version.hex(), 'envelope_flag': int.from_bytes(wire[22:24], 'little'),
            'mix_tag': mixed[0], 'xm_random': int.from_bytes(mixed[1:5], 'little'),
            'check_bit': int.from_bytes(mixed[5:9], 'little'), 'hash_random': hash_rand,
            'xg_seed_hex': xg_seed.hex(), 'proto_hex': proto.hex(), 'fields': fields,
            'roundtrip': True, 'wire_length': len(wire), 'protobuf_length': len(proto),
            'values':named_proto(proto)}

def write_private(path, data):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    source = Path(sys.argv[1])
    parts = json.loads(source.read_text())
    decoded = {}
    for family, headers in parts.items():
        envelope = medusa_envelope(headers['x-medusa'], int(headers['x-khronos']))
        medusa = decode_medusa(headers['x-medusa'], int(headers['x-khronos'])) if envelope['version'] == 3 else {'envelope':envelope, 'decoded':False, 'reason':'Only v3 inner decoding verified'}
        decoded[family] = {'helios': decode_helios(headers['x-helios']), 'medusa':medusa}
    target = Path(__file__).parent / 'private' / (source.stem + '-decoded.json')
    write_private(target, decoded)
    print(json.dumps({family: {'helios': data['helios'], 'medusa': {key: data['medusa'].get(key) for key in ('roundtrip','wire_length','protobuf_length','version_hex','envelope_flag','mix_tag','envelope','reason')}} for family, data in decoded.items()}, ensure_ascii=False, indent=2))
