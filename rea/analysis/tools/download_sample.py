"""Download one explicitly selected exported episode, preserving its encrypted MP4."""
import hashlib
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'outputs/坠崖捡个参娃娃_7689863296106646590.json'
TARGET = ROOT / 'outputs/decrypted-sample'


def main():
    data = json.loads(SOURCE.read_text())
    episode = next(e for e in data['episodes'] if e['index'] == 1)
    track = next(t for t in episode['tracks'] if t['definition'] == '1080p')
    expected_size = int(track['size'])
    expected_md5 = track['raw']['video_meta']['file_hash']
    TARGET.mkdir(parents=True, exist_ok=True)
    destination = TARGET / '坠崖捡个参娃娃_第01集_1080p.enc.mp4'
    temporary = destination.with_suffix('.mp4.part')
    if destination.exists():
        digest = hashlib.md5(destination.read_bytes()).hexdigest()
        if destination.stat().st_size == expected_size and digest == expected_md5:
            print('Existing encrypted file verified:', destination)
            return
        raise RuntimeError('Existing file does not match the selected track; refusing to overwrite')
    received = 0
    digest = hashlib.md5()
    with requests.get(track['url'], timeout=(20, 90), stream=True) as response:
        if response.status_code != 200:
            raise RuntimeError(f'CDN returned HTTP {response.status_code}; URL may need refresh')
        with temporary.open('xb') as output:
            for chunk in response.iter_content(256 * 1024):
                received += len(chunk)
                if received > expected_size:
                    raise RuntimeError('Response exceeded model file size')
                digest.update(chunk)
                output.write(chunk)
    if received != expected_size or digest.hexdigest() != expected_md5:
        raise RuntimeError('Download size/hash differs from video model')
    temporary.rename(destination)
    report = {'export_file': str(SOURCE.relative_to(ROOT)), 'episode': 1,
              'definition': '1080p', 'encrypted_file': str(destination.relative_to(ROOT)),
              'bytes': received, 'md5': digest.hexdigest(), 'model_hash_matches': True}
    (TARGET / 'download-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('Downloaded and verified:', received, 'bytes;', destination)


if __name__ == '__main__':
    main()
