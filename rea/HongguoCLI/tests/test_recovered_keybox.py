"""Differential coverage for the recovered local parsers and mocked diagnostics."""
import contextlib
import gzip
import importlib.machinery
import importlib.util
import inspect
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from Crypto.Cipher import AES
from Crypto.Util import Counter


VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "decrypt"


def load_module(name, suffix):
    alias = "comparison_" + suffix + "_" + name
    path = VENDOR / (name + "." + suffix)
    loader_type = (importlib.machinery.SourcelessFileLoader if suffix == "pyc"
                   else importlib.machinery.SourceFileLoader)
    loader = loader_type(alias, str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(alias, loader))
    loader.exec_module(module)
    return module


def load_pair(suffix):
    original_path = sys.path[:]
    try:
        keybox = load_module("extract_keybox_pairs", suffix)
        with patch.dict(sys.modules, {"extract_keybox_pairs": keybox}):
            oracle = load_module("oracle", suffix)
        return oracle, keybox
    finally:
        sys.path[:] = original_path


def box(kind, payload):
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def movie(samples, *, wide=False, fixed=False, handler=b"vide"):
    sizes = list(map(len, samples))
    offsets = []
    pos = 8
    for sample in samples:
        offsets.append(pos)
        pos += len(sample)
    full = b"\0" * 4
    stsz = box(b"stsz", full + struct.pack(">II", sizes[0] if fixed else 0, len(sizes))
               + (b"" if fixed else b"".join(struct.pack(">I", size) for size in sizes)))
    stco = box(b"co64" if wide else b"stco", full + struct.pack(">I", len(offsets))
               + b"".join(struct.pack(">Q" if wide else ">I", off) for off in offsets))
    stsc = box(b"stsc", full + struct.pack(">IIII", 1, 1, 1, 1))
    hdlr = box(b"hdlr", full + b"\0" * 4 + handler)
    track = box(b"trak", box(b"mdia", hdlr + box(b"minf", box(b"stbl", stsz + stco + stsc))))
    return box(b"mdat", b"".join(samples)) + box(b"moov", track)


def dump_fixture():
    kid = bytes(range(14)) + b"\xeb\xeb"
    key = bytes(range(16))
    iv = bytes.fromhex("0102030405060708") + b"\0" * 8
    def entry(value):
        return b"\x01\r\x01\0\0\0\x02\0" + b"\0" * 8 + value
    metadata = ('{"mKid":"' + kid.hex() + '","mSpadea":"YWJjZA\\u003d\\u003d"}').encode()
    return metadata + b"\0" * 16 + entry(iv) + entry(kid) + entry(key) + entry(iv)


class RecoveredKeyboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original, cls.original_keybox = load_pair("pyc")
        cls.recovered, cls.recovered_keybox = load_pair("py")

    def pairs(self):
        return [(self.original, self.original_keybox), (self.recovered, self.recovered_keybox)]

    def captured(self, callback):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = callback()
        return result, out.getvalue()

    def test_all_signatures_and_constants(self):
        for first, second in [(self.original, self.recovered),
                              (self.original_keybox, self.recovered_keybox)]:
            functions = {name: value for name, value in vars(first).items()
                         if inspect.isfunction(value) and value.__module__ == first.__name__}
            self.assertEqual(set(functions), {name for name, value in vars(second).items()
                             if inspect.isfunction(value) and value.__module__ == second.__name__})
            for name, function in functions.items():
                self.assertEqual(inspect.signature(function), inspect.signature(getattr(second, name)), name)
        for name in ("ADB", "DEV", "EXCL"):
            self.assertEqual(getattr(self.original, name), getattr(self.recovered, name))
        for name in ("ENTRY_PREFIX", "ZERO8"):
            self.assertEqual(getattr(self.original_keybox, name), getattr(self.recovered_keybox, name))

    def test_keybox_classification_and_metadata(self):
        a, b = self.original_keybox, self.recovered_keybox
        for value in [b"", b"\0" * 16, bytes(range(16)), b"a" * 16,
                      b"\0" * 14 + b"\xeb\xeb", bytes(range(8)) + b"\0" * 8]:
            self.assertEqual(a.classify_value(value), b.classify_value(value))
        for value in ["a\\/b\\u003d", "YWJjZA==", "invalid!", ""]:
            self.assertEqual(a.clean_json_escape(value), b.clean_json_escape(value))
            self.assertEqual(a.decoded_spade_hex(value), b.decoded_spade_hex(value))
        data = dump_fixture()
        self.assertEqual(a.extract_mkid_spade(data), b.extract_mkid_spade(data))
        self.assertEqual(a.extract_mkid_spade(data, 4), b.extract_mkid_spade(data, 4))
        entries = list(a.iter_keybox_entries(data))
        self.assertEqual(entries, list(b.iter_keybox_entries(data)))
        for lookahead in (0, 31, 32, 256):
            for window in (0, 32, 512):
                self.assertEqual(a.extract_key_votes(entries, lookahead, window),
                                 b.extract_key_votes(entries, lookahead, window))

    def test_dump_report_candidates_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dump.bin"
            path.write_bytes(dump_fixture())
            results = []
            for oracle, keybox in self.pairs():
                with patch.dict(sys.modules, {"extract_keybox_pairs": keybox}):
                    report = keybox.build_report(path, 256, 512)
                    results.append((report, oracle.all_key_candidates(path),
                                    oracle.collect_keys_ivs(report, path),
                                    self.captured(lambda: oracle.report(path))))
            self.assertEqual(results[0], results[1])
            output = Path(directory) / "report.json"
            runs = []
            for _, keybox in self.pairs():
                with patch.object(sys, "argv", ["keybox", str(path), "-o", str(output)]):
                    result = self.captured(keybox.main)
                    runs.append((result, output.read_text()))
            self.assertEqual(runs[0], runs[1])

    def test_mp4_boxes_samples_and_nal_validation(self):
        a, b = self.original, self.recovered
        samples = [struct.pack(">I", 16) + bytes(range(16))] * 3
        for wide in (False, True):
            for fixed in (False, True):
                data = movie(samples, wide=wide, fixed=fixed)
                for handler in (b"vide", b"soun"):
                    self.assertEqual(a.parse_track_samples(data, handler), b.parse_track_samples(data, handler))
                self.assertEqual(list(a._ib(data, 0, len(data))), list(b._ib(data, 0, len(data))))
                for types in ([b"moov"], [b"moov", b"trak", b"mdia"], [b"free"]):
                    self.assertEqual(a._find(data, types), b._find(data, types))
        extended = struct.pack(">I4sQ", 1, b"free", 20) + b"1234"
        zero = struct.pack(">I4s", 0, b"free") + b"payload"
        for data in (extended, zero):
            self.assertEqual(list(a._ib(data, 0, len(data))), list(b._ib(data, 0, len(data))))
        for value in (b"", b"\0" * 4, samples[0], samples[0][:-1], samples[0] + b"x"):
            self.assertEqual(a._nal_ok(value, len(value)), b._nal_ok(value, len(value)))

    def test_verify_key_iv(self):
        key = bytes(range(16))
        iv = 0x0102030405060708
        plain = struct.pack(">I", 16) + bytes(range(16))
        encrypted = [AES.new(key, AES.MODE_CTR, counter=Counter.new(128, initial_value=(iv + i) << 64))
                     .decrypt(plain) for i in range(2)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "encrypted.mp4"
            path.write_bytes(movie(encrypted))
            self.assertEqual(self.original.parse_video_samples(path), self.recovered.parse_video_samples(path))
            for keys, ivs in [([key.hex()], [f"{iv:016x}"]), (["00" * 16], [f"{iv:016x}"]),
                              (["00", key.hex()], ["0000000000000001", f"{iv:016x}"])]:
                self.assertEqual(self.captured(lambda: self.original.verify_key_iv(path, keys, ivs)),
                                 self.captured(lambda: self.recovered.verify_key_iv(path, keys, ivs)))

    def test_adb_helpers_are_only_mocked(self):
        smaps = ("1000-3000 rw-p 00000000 00:00 0 [anon:heap]\nRss: 8 kB\n"
                 "3000-4000 rw-p 00000000 00:00 0 /dev/ashmem\nRss: 4 kB\n"
                 "4000-5000 r--p 00000000 00:00 0 /file\nRss: 4 kB\n")
        self.assertEqual(self.original.build_dumplist(smaps), self.recovered.build_dumplist(smaps))
        outputs = []
        for oracle, _ in self.pairs():
            with patch.object(oracle.subprocess, "run") as run:
                run.return_value.stdout = b"123 456\n"
                oracle.adb("version", capture=False, timeout=2)
                oracle.adb_su("true", timeout=3)
                pid = oracle.get_pid()
                outputs.append((pid, run.call_args_list))
        self.assertEqual(outputs[0], outputs[1])

    def test_do_dump_with_fake_device(self):
        outputs = []
        with tempfile.TemporaryDirectory() as directory:
            with contextlib.chdir(directory):
                for oracle, _ in self.pairs():
                    def fake_adb(*args, **kwargs):
                        if args[0] == "pull":
                            Path(args[2]).write_bytes(gzip.compress(b"local fixture", mtime=0))
                    with patch.object(oracle, "adb", side_effect=fake_adb) as adb_mock, \
                         patch.object(oracle, "adb_su") as su_mock, \
                         patch.object(oracle.time, "time", side_effect=[10, 12]):
                        su_mock.return_value.stdout = b"1000-2000 rw-p 0 00:00 0\nRss: 4 kB\n"
                        result = self.captured(lambda: oracle.do_dump("123"))
                        outputs.append((result, adb_mock.call_args_list, su_mock.call_args_list,
                                        Path("capture/dumplist_live.txt").read_bytes(),
                                        Path("capture/oracle_dump.bin").read_bytes()))
        self.assertEqual(outputs[0], outputs[1])

    def test_oracle_main_paths_without_device(self):
        for argv, pid, matched in [(["oracle", "--reuse", "fixture", "--verify", "video"], "123", True),
                                   (["oracle", "--reuse", "fixture", "--verify", "video"], "123", False),
                                   (["oracle"], "123", False), (["oracle"], None, False)]:
            results = []
            for oracle, _ in self.pairs():
                with patch.object(sys, "argv", argv), \
                     patch.object(oracle.subprocess, "run") as run, \
                     patch.object(oracle, "get_pid", return_value=pid), \
                     patch.object(oracle, "do_dump", return_value="fixture") as dump, \
                     patch.object(oracle, "report", return_value={}) as report, \
                     patch.object(oracle, "collect_keys_ivs", return_value=(["key"], ["iv"])), \
                     patch.object(oracle, "verify_key_iv", return_value=("key", "iv") if matched else (None, None)):
                    def invoke():
                        try:
                            return oracle.main()
                        except SystemExit as exc:
                            return ("exit", exc.code)
                    results.append((self.captured(invoke), run.call_args_list,
                                    dump.call_args_list, report.call_args_list))
            self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
