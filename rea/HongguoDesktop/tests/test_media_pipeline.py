"""Independent encrypted HEVC/AAC fixture exercises the actual download job."""
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'.runtime/site-packages')]
from hongguo_download import media_executable, completed_file, DECRYPT_MODULES
from jobs import download
from media_fixture import SPADE, create_fixture, decoded_hashes


class MediaTests(unittest.TestCase):
    def test_source_only_download_decrypt_verify_publish_and_skip(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            ffmpeg, ffprobe = media_executable('ffmpeg'), media_executable('ffprobe')
            clear, encrypted, _ = create_fixture(temp, ffmpeg, ffprobe)
            vendor = temp/'vendor'
            (vendor/'decrypt').mkdir(parents=True)
            for name in DECRYPT_MODULES:
                shutil.copy(ROOT/'vendor/decrypt'/f'{name}.py', vendor/'decrypt')
            shutil.copy(ROOT/'vendor/manifest.json', vendor)
            handler = functools.partial(SimpleHTTPRequestHandler, directory=str(temp))
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            track = {'main_url': f'http://127.0.0.1:{server.server_port}/encrypted.mp4',
                     'video_meta': {'definition': '1080p', 'codec_type': 'hevc', 'size': encrypted.stat().st_size,
                                    'file_hash': hashlib.md5(encrypted.read_bytes()).hexdigest()},
                     'encrypt_info': {'encrypt': True, 'encryption_method': 'cenc-aes-ctr', 'spade_a': SPADE}}
            class API:
                def models(self, vids, *, on_source=None):
                    source = {'model_api': 'video_model', 'model_fallback': True,
                              'model_fallback_reason': 'fixture batch unavailable'}
                    if on_source:
                        on_source({**source, 'model_api_state': 'selected'})
                    return {'models': {vids[0]: {'tracks': [track], **source}}}
                def close(self):
                    pass
            job = {'directory': str(temp/'downloads'), 'title': '媒体流程测试', 'series_id': '1234567890123',
                   'vid': 'test', 'quality': '1080p', 'index': 1}
            events = []
            try:
                result = download(job, API, vendor, lambda **data: events.append(data), lambda: None)
                self.assertTrue(completed_file(Path(result), 'test', '1080p'))
                self.assertEqual(decoded_hashes(clear, ffmpeg), decoded_hashes(result, ffmpeg))
                self.assertTrue({'downloading', 'decrypting', 'verifying'}.issubset(e.get('status') for e in events))
                self.assertTrue(any(e.get('model_api') == 'video_model' and e.get('model_fallback') for e in events))
                saved = json.loads(Path(result).with_suffix('.json').read_text())
                self.assertEqual(saved['model_api'], 'video_model')
                self.assertTrue(saved['model_fallback'])
                self.assertFalse(list(vendor.rglob('*.pyc')))
                self.assertTrue(all(Path(sys.modules[n].__file__).suffix == '.py' for n in DECRYPT_MODULES))
                self.assertEqual(download(job, lambda: self.fail('completed download must not call API'), vendor,
                                          lambda **kw: events.append(kw), lambda: None), result)
                self.assertEqual(events[-1]['model_api'], 'local')
                Path(result).write_bytes(b'tampered')
                with self.assertRaisesRegex(RuntimeError, '目标文件已存在'):
                    download(job, API, vendor, lambda **kw: None, lambda: None)
            finally:
                server.shutdown(); server.server_close()
                for name in DECRYPT_MODULES:
                    sys.modules.pop(name, None)


if __name__ == '__main__':
    unittest.main()
