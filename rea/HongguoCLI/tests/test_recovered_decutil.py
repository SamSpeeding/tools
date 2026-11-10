"""Differential checks against the retained, unmodified CPython 3.11 artifact.

Only this test oracle loads the old bytecode. Runtime source never loads it.
All external process calls are mocked, and no network or ADB calls are made.
"""

import contextlib
import importlib.util
import inspect
import io
from pathlib import Path
import random
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from Crypto.Cipher import AES


VENDOR = Path(__file__).resolve().parents[1] / 'vendor' / 'decrypt'


def load_artifact(suffix, name):
    spec = importlib.util.spec_from_file_location(name, VENDOR / ('decutil.' + suffix))
    module = importlib.util.module_from_spec(spec)
    old_path = sys.path[:]
    try:
        with patch.dict(sys.modules, {'oracle': types.ModuleType('oracle')}):
            spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
    return module


def box(kind, payload=b'', size_mode='normal'):
    if size_mode == 'wide':
        return struct.pack('>I4sQ', 1, kind, len(payload) + 16) + payload
    if size_mode == 'rest':
        return struct.pack('>I4s', 0, kind) + payload
    return struct.pack('>I4s', len(payload) + 8, kind) + payload


@unittest.skipUnless(sys.version_info[:2] == (3, 11), 'original artifact requires CPython 3.11')
class RecoveredDecutilTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = load_artifact('pyc', '_decutil_original_test')
        cls.recovered = load_artifact('py', '_decutil_recovered_test')

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.source = self.directory / 'input.mp4'
        self.target = self.directory / 'output.mp4'

    def capture(self, module, name, *args):
        self.target.unlink(missing_ok=True)
        stream = io.StringIO()
        try:
            with contextlib.redirect_stdout(stream):
                value = getattr(module, name)(*args)
            result = ('return', value)
        except Exception as exc:
            result = ('raise', type(exc), str(exc))
        return result, stream.getvalue(), self.target.read_bytes() if self.target.exists() else None

    def assert_equivalent(self, name, *args):
        expected = self.capture(self.original, name, *args)
        actual = self.capture(self.recovered, name, *args)
        self.assertEqual(actual, expected)
        return actual

    def test_all_original_signatures_are_preserved(self):
        functions = {
            name: value for name, value in vars(self.original).items()
            if inspect.isfunction(value) and value.__module__ == self.original.__name__
        }
        self.assertEqual(len(functions), 9)
        for name, value in functions.items():
            with self.subTest(name=name):
                self.assertEqual(inspect.signature(getattr(self.recovered, name)), inspect.signature(value))

    def test_iv_and_key_id_scanners_match_truncation_and_duplicates(self):
        iv = bytes.fromhex('0011223344556677')
        entry = b'senc' + bytes(8) + iv
        blobs = [b'', b'senc', entry, entry + entry, entry + b'senc' + bytes(8) + bytes(8),
                 b'tenc' + bytes(8) + bytes(range(16)), b'prefix' + entry]
        for blob in blobs:
            for length in range(len(blob) + 1):
                self.source.write_bytes(blob[:length])
                for name in ('senc_iv8', 'tenc_kid'):
                    with self.subTest(name=name, length=length, blob=blob):
                        self.assert_equivalent(name, str(self.source))
        self.source.write_bytes(entry + entry)
        self.assertEqual(self.recovered.senc_iv8(str(self.source)), [iv.hex()])
        for lo, hi in ((0, len(entry)), (1, len(entry)), (0, 0), (len(entry), len(entry) * 2)):
            self.assertEqual(self.recovered._trak_senc_iv8(entry * 2, lo, hi),
                             self.original._trak_senc_iv8(entry * 2, lo, hi))

    def test_aes_ctr_and_per_sample_iv_increment(self):
        rng = random.Random(413)
        key = bytes(range(16))
        iv = '000000000000003a'
        plaintext = [rng.randbytes(size) for size in (0, 1, 15, 16, 17, 33, 129)]
        data = bytearray(b'prefix')
        offsets = []
        expected = bytearray(data)
        for idx, sample in enumerate(plaintext):
            offsets.append(len(data))
            cipher = AES.new(key, AES.MODE_CTR, nonce=b'', initial_value=(int(iv, 16) + idx) << 64)
            data.extend(cipher.encrypt(sample) + b'gap')
            expected.extend(sample + b'gap')
        sizes = [len(sample) for sample in plaintext]
        for module in (self.original, self.recovered):
            buf = bytearray(data)
            self.assertIsNone(module._decrypt_track(buf, key, iv, sizes, offsets))
            self.assertEqual(buf, expected)
        for bad_key, bad_iv in ((b'bad', iv), (key, 'invalid'), (key, 'ffffffffffffffff')):
            outcomes = []
            for module in (self.original, self.recovered):
                try:
                    module._decrypt_track(bytearray(data), bad_key, bad_iv, sizes, offsets)
                except Exception as exc:
                    outcomes.append((type(exc), str(exc)))
            self.assertEqual(len(outcomes), 2)
            self.assertEqual(outcomes[0], outcomes[1])

    def test_decrypt_full_output_stats_and_diagnostics(self):
        key = bytes(range(16))
        iv = '0000000000000010'
        samples = [b'video sample one', b'video sample number two']
        encrypted = b''.join(AES.new(key, AES.MODE_CTR, nonce=b'',
                                   initial_value=(int(iv, 16) + idx) << 64).encrypt(sample)
                             for idx, sample in enumerate(samples))
        sizes = list(map(len, samples))
        offsets = [0, sizes[0]]
        for module in (self.original, self.recovered):
            module.oracle.parse_video_samples = lambda path: (encrypted, sizes, offsets)
            module.oracle._nal_ok = lambda data, size: data.startswith(b'video') and len(data) == size
        result = self.assert_equivalent('decrypt_full', str(self.source), key.hex(), iv, str(self.target))
        self.assertEqual(result[0], ('return', (2, 2)))
        self.assertEqual(result[2], b''.join(samples))

    def test_decrypt_av_no_moov_and_empty_tracks(self):
        self.source.write_bytes(b'local file')
        for module in (self.original, self.recovered):
            module.oracle._find = lambda *args: None
        self.assert_equivalent('decrypt_av', str(self.source), bytes(16).hex(), str(self.target))
        for module in (self.original, self.recovered):
            module.oracle._find = lambda *args: (0, 10)
            module.oracle._ib = lambda *args: iter([(b'free', 0, 10, 8)])
        result = self.assert_equivalent('decrypt_av', str(self.source), bytes(16).hex(), str(self.target))
        self.assertEqual(result[0], ('return', {}))
        self.assertEqual(result[2], b'local file')

    def test_strip_cenc_nested_entries_and_box_boundaries(self):
        video = box(b'encv', bytes(78) + box(b'sinf', box(b'tenc', bytes(24))))
        audio = box(b'enca', bytes(28) + box(b'sinf', b'audio data'))
        stsd = box(b'stsd', bytes(4) + struct.pack('>I', 2) + video + audio)
        nested = box(b'trak', box(b'mdia', box(b'minf', box(b'stbl', stsd + box(b'senc', bytes(12))))))
        fixtures = [
            b'', b'garbage', box(b'free'), box(b'moov'), box(b'moov', box(b'free')),
            box(b'moov', nested + box(b'saiz') + box(b'saio')),
            box(b'moov', box(b'senc', bytes(12), 'wide')),
            box(b'moov', box(b'senc', bytes(12), 'rest')),
            box(b'moov', box(b'encv', b'bad child' + b'sinf' + b'tail')),
            box(b'moov', box(b'senc', bytes(12)), 'wide'),
            box(b'moov', struct.pack('>I4s', 7, b'senc')),
            box(b'free', bytes(8), 'wide') + box(b'moov', box(b'senc')),
            struct.pack('>I4s', 1, b'moov'),
        ]
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                self.source.write_bytes(fixture)
                self.assert_equivalent('strip_cenc', str(self.source), str(self.target))
        self.source.write_bytes(fixtures[5])
        self.recovered.strip_cenc(str(self.source), str(self.target))
        output = self.target.read_bytes()
        self.assertEqual(len(output), len(fixtures[5]))
        for marker in (b'encv', b'enca', b'sinf', b'senc', b'saiz', b'saio'):
            self.assertNotIn(marker, output)
        self.assertIn(b'hvc1', output)
        self.assertIn(b'mp4a', output)

    def test_ffmpeg_discovery_checks_same_paths_in_same_order(self):
        outcomes = []
        for module in (self.original, self.recovered):
            with patch.object(module, '__file__', '/a/b/c/d/decutil.py'), \
                 patch.object(module.os.path, 'isfile', return_value=False) as isfile, \
                 patch.object(module.shutil, 'which', return_value='/bin/ffmpeg') as which:
                result = module._ff_exe('ffmpeg')
                outcomes.append((result, isfile.call_args_list, which.call_args_list))
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(len(outcomes[0][1]), 8)

    def test_remux_uses_identical_arguments_on_mac_and_windows(self):
        for platform in ('darwin', 'win32'):
            outcomes = []
            for module in (self.original, self.recovered):
                with patch.object(module, '_ff_exe', return_value='/tools/ffmpeg'), \
                     patch.object(module.sys, 'platform', platform), \
                     patch.object(module.os.path, 'exists', return_value=True), \
                     patch.object(module.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)) as run:
                    result = module.remux_playable('input.mp4', 'output.mp4')
                    outcomes.append((result, run.call_args))
            self.assertEqual(outcomes[0], outcomes[1])
            self.assertEqual(outcomes[0][1].kwargs,
                             {'capture_output': True, 'text': True,
                              'creationflags': 134217728 if platform == 'win32' else 0})

    def test_remux_fallback_success_and_error_diagnostics(self):
        self.source.write_bytes(box(b'moov', box(b'senc')))
        outcomes = []
        for module in (self.original, self.recovered):
            with patch.object(module, '_ff_exe', return_value='/tools/ffmpeg'), \
                 patch.object(module.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1, stderr='x' * 200)):
                outcomes.append(self.capture(module, 'remux_playable', str(self.source), str(self.target)))
        self.assertEqual(outcomes[0], outcomes[1])
        for module in (self.original, self.recovered):
            with patch.object(module, '_ff_exe', return_value=None), \
                 patch.object(module, 'strip_cenc', side_effect=ValueError('bad MP4')):
                outcomes.append(self.capture(module, 'remux_playable', str(self.source), str(self.target)))
        self.assertEqual(outcomes[2], outcomes[3])


if __name__ == '__main__':
    unittest.main()
