"""Extract only app code/assets, verifying installer SHA-256 values; never run target."""
import hashlib
import json
import lzma
from pathlib import Path
import innoextract as i

root = Path(__file__).resolve().parents[2]
b = (root / 'HongguoDownloader-Setup.exe').read_bytes()
h, d = i.find_offsets(b)
b1, p = i.decompress_block(b, h + 117)
b2, _ = i.decompress_block(b, p)
files = i.parse_file_entries(b1, i.find_file_entries_start(b1))
entries = i.parse_data_entries(b2)
selected = []
manifest = []
for f in files:
    if not f.destination.startswith('{app}\\') or f.location >= len(entries):
        continue
    path = Path(i.resolve_path(f.destination))
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Unsafe archive path')
    e = entries[f.location]
    record = {'path': str(path), 'location': f.location, 'size': e.file_size,
              'sha256': b2[f.location*89+40:f.location*89+72].hex()}
    manifest.append(record)
    if f.location <= 26 or 39 <= f.location <= 41:
        selected.append((path, e, record))
cache = {}
for offset in {e.chunk_offset for _,e,_ in selected}:
    end = max(e.file_offset + e.file_size for _,e,_ in selected if e.chunk_offset == offset)
    pos = d + offset
    assert b[pos:pos+4] == i.ZLB_MAGIC
    prop = b[pos+4]
    assert prop <= 40
    size = 0xffffffff if prop == 40 else (2 | (prop & 1)) << (prop // 2 + 11)
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{'id': lzma.FILTER_LZMA2, 'dict_size':size}])
    cache[offset] = dec.decompress(b[pos+5:], max_length=end)
for path,e,record in selected:
    out = cache[e.chunk_offset][e.file_offset:e.file_offset+e.file_size]
    assert len(out) == e.file_size
    if e.call_instruction_filter:
        out = i.undo_call_instruction_filter(out)
    assert hashlib.sha256(out).hexdigest() == record['sha256'], (path, 'digest mismatch')
    target = root/'analysis/extracted'/path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(out)
    print(path, len(out), out[:4].hex())
(root/'analysis/evidence/installer-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
