"""Statically extract app payloads from the user-supplied Inno installer.

No installer or extracted target code is executed. Reuse the previously audited
Inno parser, verify each selected member against its embedded SHA-256, and keep
all derived data in this new investigation directory.
"""
import hashlib
import json
import lzma
import sys
from pathlib import Path

ROOT = Path('/Users/tt/Desktop/rea')
OUT = Path(__file__).resolve().parent
SOURCE = Path('/Users/tt/Downloads/HongguoDownloader-Setup (3).exe')
sys.path.insert(0, str(ROOT / 'analysis/tools'))
import innoextract as i


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    blob = SOURCE.read_bytes()
    h, d = i.find_offsets(blob)
    assert blob[h:h + 10] == b'Inno Setup'
    b1, p = i.decompress_block(blob, h + 117)
    b2, _ = i.decompress_block(blob, p)
    assert len(b2) % 89 == 0
    files = i.parse_file_entries(b1, i.find_file_entries_start(b1))
    entries = i.parse_data_entries(b2)
    manifest, selected, unresolved = [], [], []
    paths = set()
    for f in files:
        if not f.destination.startswith('{app}\\'):
            continue
        if not 0 <= f.location < len(entries):
            unresolved.append(dict(destination=f.destination, location=f.location,
                reason='Reused parser did not map this entry to a payload; excluded from comparison.'))
            continue
        path = Path(i.resolve_path(f.destination))
        assert not path.is_absolute() and '..' not in path.parts
        assert str(path) not in paths
        paths.add(str(path))
        e = entries[f.location]
        rec = dict(path=str(path), location=f.location, size=e.file_size,
                   sha256=b2[f.location * 89 + 40:f.location * 89 + 72].hex())
        manifest.append(rec)
        if (path.parts[0] == 'app' and path.parts[1] != 'tools') or len(path.parts) == 1:
            selected.append((path, e, rec))
    cache = {}
    for offset in {e.chunk_offset for _, e, _ in selected}:
        end = max(e.file_offset + e.file_size for _, e, _ in selected if e.chunk_offset == offset)
        pos = d + offset
        assert blob[pos:pos + 4] == i.ZLB_MAGIC
        prop = blob[pos + 4]
        assert prop <= 40
        size = 0xffffffff if prop == 40 else (2 | (prop & 1)) << (prop // 2 + 11)
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW,
            filters=[{'id': lzma.FILTER_LZMA2, 'dict_size': size}])
        cache[offset] = dec.decompress(blob[pos + 5:], max_length=end)
    verified = []
    for path, e, rec in selected:
        content = cache[e.chunk_offset][e.file_offset:e.file_offset + e.file_size]
        assert len(content) == e.file_size
        if e.call_instruction_filter:
            content = i.undo_call_instruction_filter(content)
        assert sha(content) == rec['sha256'], (path, 'digest mismatch')
        dest = OUT / 'extracted' / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        assert not dest.exists(), dest
        dest.write_bytes(content)
        verified.append(str(path))
    old = {x['path']: x for x in json.loads((ROOT / 'research/latest-installer-20261016/evidence/installer-manifest.json').read_text())}
    new = {x['path']: x for x in manifest}
    added = sorted(new.keys() - old.keys())
    removed = sorted(old.keys() - new.keys())
    changed = [dict(path=k, old=old[k], new=new[k]) for k in sorted(old.keys() & new.keys()) if old[k]['sha256'] != new[k]['sha256']]
    unchanged = sorted(k for k in old.keys() & new.keys() if old[k]['sha256'] == new[k]['sha256'])
    report = dict(source=str(SOURCE), source_sha256=sha(blob), source_size=len(blob),
                  old_source_sha256=sha((Path('/Users/tt/Downloads/HongguoDownloader-Setup (2).exe')).read_bytes()),
                  inno_header=blob[h:h + 64].split(b'\x00')[0].decode(errors='replace'),
                  parsed_files=len(files), manifest_files=len(manifest), data_entries=len(entries),
                  selected_verified=verified, unresolved_entries=unresolved, added=added, removed=removed, changed=changed,
                  unchanged=unchanged,
                  limits=['All manifest members compared by embedded SHA-256; only selected app payloads decompressed and independently hash-verified.',
                          'The reused parser is specific to the observed Inno 6.7 layout; no installer execution or live platform request.'])
    (OUT / 'evidence').mkdir(exist_ok=True)
    (OUT / 'evidence/installer-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    (OUT / 'evidence/installer-diff.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in ('unchanged','selected_verified','changed')}, ensure_ascii=False, indent=2))
    print('Changed entries:', len(changed))
    print('Changed app members:', [x['path'] for x in changed if not x['path'].startswith('python/')])
    print('Verified selected payloads:', len(verified), 'Unchanged entries:', len(unchanged))
    print('New app version:', (OUT / 'extracted/app/version.txt').read_text())


if __name__ == '__main__':
    main()
