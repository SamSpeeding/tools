"""Generate a tiny local HEVC/AAC sample; no platform requests or real keys."""
import json
from pathlib import Path
import struct
import subprocess

from Crypto.Cipher import AES


# First known-answer vector embedded in the original unwrap module.
SPADE = 'k7wd8lO6G/dhixnESLgG9k2BCvxFtxX+Xrkl8my/EvVBugmCgg=='
KEY = bytes.fromhex('287216bfa89e662a0f748120c305e199')


def run(args):
    result = subprocess.run(args, capture_output=True, check=True, timeout=60)
    return result.stdout


def box(kind, payload):
    return struct.pack('>I4s', len(payload) + 8, kind) + payload


def boxes(data):
    offset = 0
    while offset < len(data):
        size, kind = struct.unpack_from('>I4s', data, offset)
        if size < 8 or offset + size > len(data):
            raise ValueError('Unexpected fixture MP4 layout')
        yield kind, data[offset + 8:offset + size]
        offset += size


def handler_of(track):
    for kind, payload in boxes(track):
        if kind == b'mdia':
            for child, body in boxes(payload):
                if child == b'hdlr':
                    return body[8:12]
    raise ValueError('Missing fixture track handler')


def encrypted_description(data):
    """Mark HEVC/AAC sample entries and add CENC metadata for strip_cenc."""
    result = []
    for kind, payload in boxes(data):
        if kind in (b'mdia', b'minf', b'stbl'):
            payload = encrypted_description(payload)
        elif kind == b'stsd':
            entries = []
            for sample_type, body in boxes(payload[8:]):
                if sample_type in (b'hvc1', b'hev1', b'mp4a'):
                    sinf = box(b'sinf', box(b'frma', sample_type)
                               + box(b'schm', b'\0' * 4 + b'cenc' + struct.pack('>I', 0x10000))
                               + box(b'schi', box(b'tenc', b'\0' * 6 + b'\1\10' + bytes(range(16)))))
                    body += sinf
                    sample_type = b'enca' if sample_type == b'mp4a' else b'encv'
                entries.append(box(sample_type, body))
            payload = payload[:8] + b''.join(entries)
        result.append(box(kind, payload))
    return b''.join(result)


def create_fixture(directory, ffmpeg, ffprobe):
    directory = Path(directory)
    clear = directory / 'clear.mp4'
    encrypted = directory / 'encrypted.mp4'
    run([ffmpeg, '-hide_banner', '-v', 'error', '-nostdin', '-y',
         '-f', 'lavfi', '-i', 'testsrc2=size=128x72:rate=6:duration=1',
         '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
         '-c:v', 'libx265', '-preset', 'ultrafast',
         '-x265-params', 'pools=1:frame-threads=1:log-level=error',
         '-c:a', 'aac', '-tag:v', 'hvc1', '-shortest', str(clear)])
    probe = json.loads(run([ffprobe, '-v', 'error', '-show_packets',
                           '-show_entries', 'stream=index,codec_type:packet=stream_index,pos,size',
                           '-of', 'json', str(clear)]))
    handlers = {stream['index']: b'vide' if stream['codec_type'] == 'video' else b'soun'
                for stream in probe['streams']}
    packets = {b'vide': [], b'soun': []}
    for packet in probe['packets']:
        packets[handlers[packet['stream_index']]].append((int(packet['pos']), int(packet['size'])))
    bases = {b'vide': 0x0102030405060708, b'soun': 0x1112131415161718}
    data = bytearray(clear.read_bytes())
    # Packet locations come from ffprobe, independently of the recovered parser.
    for handler, samples in packets.items():
        for index, (position, size) in enumerate(samples):
            cipher = AES.new(KEY, AES.MODE_CTR,
                             nonce=(bases[handler] + index).to_bytes(8, 'big'), initial_value=0)
            data[position:position + size] = cipher.encrypt(data[position:position + size])
    top = list(boxes(bytes(data)))
    if [kind for kind, _ in top][-1] != b'moov':
        raise ValueError('Fixture requires moov after mdat so packet offsets stay valid')
    result = []
    for kind, payload in top:
        if kind == b'moov':
            children = []
            for child, body in boxes(payload):
                if child == b'trak':
                    handler = handler_of(body)
                    count = len(packets[handler])
                    ivs = b''.join((bases[handler] + n).to_bytes(8, 'big') for n in range(count))
                    body = encrypted_description(body) + box(b'senc', b'\0' * 4 + struct.pack('>I', count) + ivs)
                children.append(box(child, body))
            payload = b''.join(children)
        result.append(box(kind, payload))
    encrypted.write_bytes(b''.join(result))
    return clear, encrypted, {k.decode(): len(v) for k, v in packets.items()}


def decoded_hashes(path, ffmpeg):
    return run([ffmpeg, '-hide_banner', '-v', 'error', '-nostdin', '-i', str(path),
                '-map', '0:v:0', '-map', '0:a:0', '-f', 'streamhash', '-hash', 'sha256', '-'])
