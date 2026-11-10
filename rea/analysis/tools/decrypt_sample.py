"""Replay the audited installer modules on one selected local sample (Python 3.11)."""
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'analysis/extracted/app/frida'
TARGET = ROOT / 'outputs/decrypted-sample'
SOURCE = ROOT / 'outputs/坠崖捡个参娃娃_7689863296106646590.json'
STEM = '坠崖捡个参娃娃_第01集_1080p'


def main():
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError('Use .venv-decrypt/bin/python (CPython 3.11)')
    manifest = json.loads((ROOT/'analysis/evidence/installer-manifest.json').read_text())
    hashes = {row['path']: row['sha256'] for row in manifest}
    module_hashes = {}
    for name in ('unwrap_spade', 'oracle', 'extract_keybox_pairs', 'decutil'):
        path = MODULE_DIR / (name + '.pyc')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != hashes['app/frida/' + name + '.pyc']:
            raise RuntimeError('Installer module digest mismatch: ' + name)
        module_hashes[name] = digest
    data = json.loads(SOURCE.read_text())
    ep = next(e for e in data['episodes'] if e['index'] == 1)
    track = next(t for t in ep['tracks'] if t['definition'] == '1080p')
    encrypted = TARGET / (STEM + '.enc.mp4')
    raw = TARGET / (STEM + '.raw.mp4')
    output = TARGET / (STEM + '.mp4')
    if raw.exists() or output.exists():
        raise RuntimeError('Output already exists; refusing to overwrite')
    if hashlib.md5(encrypted.read_bytes()).hexdigest() != track['raw']['video_meta']['file_hash']:
        raise RuntimeError('Encrypted file does not match selected video model')
    sys.path.insert(0, str(MODULE_DIR))
    unwrap = importlib.import_module('unwrap_spade')
    oracle = importlib.import_module('oracle')
    dec = importlib.import_module('decutil')
    spade = track['raw']['encrypt_info']['spade_a']
    key = unwrap.spade_to_key(spade, 0)
    if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{32}', key):
        key = unwrap.spade_to_key(spade, 1)
    if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{32}', key):
        raise RuntimeError('Model content key format is unsupported')
    ivs = dec.senc_iv8(str(encrypted))
    matched_key, matched_iv = oracle.verify_key_iv(str(encrypted), [key], ivs)
    if matched_key is None or matched_iv is None:
        raise RuntimeError('Model key and encrypted samples do not match')
    print('Model/file match verified; decrypting video and audio samples.', flush=True)
    stats = dec.decrypt_av(str(encrypted), matched_key, str(raw))
    video = stats.get('vide')
    if not video or video[0] != video[1] or video[1] <= 0:
        raise RuntimeError('Video sample validation failed')
    if not dec.remux_playable(str(raw), str(output)) or not output.is_file():
        raise RuntimeError('MP4 remux failed')
    report = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'series_id': data['series_id'], 'episode': 1, 'definition': '1080p',
              'method': 'installer spade_to_key / verify_key_iv / decrypt_av / remux_playable',
              'module_sha256': module_hashes, 'model_key_match': True,
              'sample_validation': stats, 'full_decode_validated': False,
              'encrypted_file': str(encrypted.relative_to(ROOT)),
              'output_file': str(output.relative_to(ROOT)),
              'output_bytes': output.stat().st_size,
              'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
    (TARGET/'decryption-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('Decrypted MP4:', output, flush=True)


if __name__ == '__main__':
    main()
