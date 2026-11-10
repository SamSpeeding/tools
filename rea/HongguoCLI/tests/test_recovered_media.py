"""Exercise real HEVC/AAC through source and retained-bytecode implementations."""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hongguo_download as download
from media_fixture import KEY, SPADE, create_fixture, decoded_hashes


def worker(mode, vendor, encrypted, output):
    vendor, encrypted, output = map(Path, (vendor, encrypted, output))
    output.mkdir()
    if mode == 'original':
        for name in download.DECRYPT_MODULES:
            loader = importlib.machinery.SourcelessFileLoader(name, str(vendor / 'decrypt' / f'{name}.pyc'))
            module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
            sys.modules[name] = module
            loader.exec_module(module)
        modules = {name: sys.modules[name] for name in download.DECRYPT_MODULES}
    else:
        download.preflight(vendor)
        modules = download.load_decrypt_modules(vendor)
    unwrap, oracle, decutil = (modules[name] for name in ('unwrap_spade', 'oracle', 'decutil'))
    key = unwrap.spade_to_key(SPADE)
    assert key == KEY.hex()
    candidate, iv = oracle.verify_key_iv(str(encrypted), [key], decutil.senc_iv8(str(encrypted)))
    assert candidate == key and iv
    raw = output / 'raw.mp4'
    stripped = output / 'stripped.mp4'
    stats = decutil.decrypt_av(str(encrypted), key, str(raw))
    assert decutil.strip_cenc(str(raw), str(stripped))
    report = {'stats': stats, 'raw_sha256': hashlib.sha256(raw.read_bytes()).hexdigest(),
              'stripped_sha256': hashlib.sha256(stripped.read_bytes()).hexdigest(),
              'modules': {name: module.__file__ for name, module in modules.items()}}
    if mode == 'source':
        track = {'encrypt_info': {'encrypt': True, 'encryption_method': 'cenc-aes-ctr', 'spade_a': SPADE},
                 'video_meta': {'codec_type': 'hevc'}}
        report['playable'] = download.playable_file(encrypted, track, output / 'playable.mp4', vendor)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))


class SourceDeploymentTests(unittest.TestCase):
    def test_source_is_required_even_while_original_bytecode_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            vendor = Path(folder)
            shutil.copytree(ROOT / 'vendor' / 'decrypt', vendor / 'decrypt')
            shutil.copy(ROOT / 'vendor' / 'manifest.json', vendor / 'manifest.json')
            (vendor / 'decrypt' / 'decutil.py').unlink()
            with patch.dict(sys.modules, {name: None for name in download.DECRYPT_MODULES}):
                with self.assertRaisesRegex(RuntimeError, '缺少解密源码'):
                    download.load_decrypt_modules(vendor)

    def test_modified_source_fails_integrity_check(self):
        with tempfile.TemporaryDirectory() as folder:
            vendor = Path(folder)
            shutil.copytree(ROOT / 'vendor' / 'decrypt', vendor / 'decrypt')
            shutil.copy(ROOT / 'vendor' / 'manifest.json', vendor / 'manifest.json')
            with (vendor / 'decrypt' / 'decutil.py').open('a') as handle:
                handle.write('\n# modified\n')
            with patch.object(download, 'media_executable', return_value='/unused'):
                with self.assertRaisesRegex(RuntimeError, '解密源码校验失败'):
                    download.preflight(vendor)


class RecoveredMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg = download.media_executable('ffmpeg')
            cls.ffprobe = download.media_executable('ffprobe')
        except RuntimeError as exc:
            raise unittest.SkipTest(str(exc))
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name).resolve()
        cls.clear, cls.encrypted, cls.counts = create_fixture(cls.directory, cls.ffmpeg, cls.ffprobe)
        cls.vendor = cls.directory / 'source-only-vendor'
        (cls.vendor / 'decrypt').mkdir(parents=True)
        for name in download.DECRYPT_MODULES:
            shutil.copy(ROOT / 'vendor' / 'decrypt' / f'{name}.py', cls.vendor / 'decrypt')
        shutil.copy(ROOT / 'vendor' / 'manifest.json', cls.vendor / 'manifest.json')
        cls.source_report = cls.run_worker('source', cls.vendor)

    @classmethod
    def run_worker(cls, mode, vendor):
        destination = cls.directory / mode
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--worker',
                                 mode, str(vendor), str(cls.encrypted), str(destination)],
                                capture_output=True, text=True, timeout=90,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return json.loads((destination / 'report.json').read_text())

    def test_source_only_pipeline_decodes_identical_video_and_audio(self):
        self.assertTrue(self.source_report['playable']['full_decode_validated'])
        self.assertFalse(list(self.vendor.rglob('*.pyc')))
        for path in self.source_report['modules'].values():
            self.assertEqual(Path(path).suffix, '.py')
            self.assertEqual(Path(path).parent, self.vendor / 'decrypt')
        self.assertEqual(decoded_hashes(self.clear, self.ffmpeg),
                         decoded_hashes(self.directory / 'source' / 'playable.mp4', self.ffmpeg))
        self.assertEqual(self.source_report['stats']['vide'], [self.counts['vide'], self.counts['vide']])
        # The original module validates NAL structure only for video.  Audio
        # correctness is established above by full decoded-content hashes.
        self.assertEqual(self.source_report['stats']['soun'], [None, self.counts['soun']])

    @unittest.skipUnless(sys.version_info[:2] == (3, 11), 'Original reference bytecode requires CPython 3.11')
    def test_original_and_source_produce_identical_decrypted_mp4(self):
        original = self.run_worker('original', ROOT / 'vendor')
        for key in ('stats', 'raw_sha256', 'stripped_sha256'):
            self.assertEqual(original[key], self.source_report[key], key)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        worker(*sys.argv[2:])
    else:
        unittest.main()
