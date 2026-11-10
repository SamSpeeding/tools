"""Differential checks against the retained, independently loaded bytecode."""

import base64
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import random
import subprocess
import sys
import unittest


DECRYPT = Path(__file__).resolve().parents[1] / "vendor" / "decrypt"


def load_module(name, suffix):
    path = DECRYPT / f"unwrap_spade.{suffix}"
    loader_class = (importlib.machinery.SourcelessFileLoader if suffix == "pyc"
                    else importlib.machinery.SourceFileLoader)
    loader = loader_class(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def outcome(function, *args):
    try:
        return "return", function(*args)
    except Exception as exc:
        return "raise", type(exc), str(exc)


class RecoveredUnwrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.version_info[:2] != (3, 11):
            raise unittest.SkipTest("The comparison bytecode requires CPython 3.11")
        cls.original = load_module("original_unwrap_spade", "pyc")
        cls.recovered = load_module("recovered_unwrap_spade", "py")

    def assert_same(self, name, *args):
        self.assertEqual(outcome(getattr(self.original, name), *args),
                         outcome(getattr(self.recovered, name), *args))

    def test_known_answers_and_all_input_forms(self):
        self.assertEqual(self.original._TRUTH, self.recovered._TRUTH)
        for payload_hex, expected in self.original._TRUTH:
            payload = bytes.fromhex(payload_hex)
            self.assertEqual(self.recovered.unwrap_v1(payload_hex), expected)
            for flag in (0, 1, -1, 2, False, True, None):
                for value in (payload, bytearray(payload), memoryview(payload),
                              list(payload), payload_hex, payload_hex.upper(),
                              " ".join(payload_hex[i:i + 2]
                                       for i in range(0, len(payload_hex), 2))):
                    with self.subTest(payload=payload_hex, flag=flag, type=type(value)):
                        self.assert_same("unwrap_v1", value, flag)
                encoded = base64.b64encode(payload)
                for value in (encoded, encoded.decode(), bytearray(encoded),
                              memoryview(encoded), b"\n" + encoded + b"\n"):
                    self.assert_same("spade_to_key", value, flag)

    def test_integer_helpers(self):
        values = list(range(-513, 514)) + [-(1 << 80), 1 << 32, (1 << 80) + 255]
        for value in values:
            self.assert_same("_popcount", value)
            self.assert_same("_s8", value)

    def test_nul_terminated_compare(self):
        values = (b"", b"a", b"a\0x", b"a\0y", b"b", b"app_v2", b"web_v2")
        for a in values:
            for b in values:
                for length in (-1, 0, 1, 2, 6, 9):
                    self.assert_same("_strncmp0", a, b, length)
        self.assertTrue(self.recovered._strncmp0(b"a\0x", b"a\0y", 3))

    def test_random_payloads_and_mutations(self):
        # Reproducible malformed payloads cover bounds, suffix and header paths;
        # mutations of valid vectors keep the transform loop reachable.
        rng = random.Random(0x5350414445)
        payloads = [rng.randbytes(rng.randrange(0, 130)) for _ in range(1600)]
        for payload_hex, _ in self.original._TRUTH:
            payload = bytes.fromhex(payload_hex)
            payloads.extend(payload[:length] for length in range(len(payload)))
            for index in range(len(payload)):
                for value in (0, 1, 48, 97, 127, 255):
                    changed = bytearray(payload)
                    changed[index] = value
                    payloads.append(bytes(changed))
        for payload in payloads:
            for flag in (0, 1):
                self.assert_same("unwrap_v1", payload, flag)

    def test_unsupported_v2_suffixes(self):
        # For suffix length six, length >= eight keeps both XOR seeds valid.
        # These are constructed envelope headers, not copied media payloads.
        for suffix in (b"app_v2", b"web_v2", b"app_v2\0", b"web_v2\0"):
            payload = bytearray(b"\0" * 20)
            payload[0] = 48 + len(suffix)
            payload[-len(suffix):] = suffix
            for flag in (0, 1):
                self.assert_same("unwrap_v1", bytes(payload), flag)
                self.assertIsNone(self.recovered.unwrap_v1(payload, flag))

    def test_invalid_input_exceptions(self):
        for value in (None, 3, [], [1, 2], [999, -2, 500], "z", "0", "0x00"):
            self.assert_same("unwrap_v1", value)
        for value in (None, 3, "é", "a", "%%%%", "", "AA", b"AA=", b"AA=="):
            self.assert_same("spade_to_key", value)

    def test_selftest_output_and_return(self):
        outputs = []
        for module in (self.original, self.recovered):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                result = module._selftest()
            outputs.append((result, buffer.getvalue()))
        self.assertEqual(outputs[0], outputs[1])
        self.assertTrue(outputs[1][0])
        self.assertTrue(outputs[1][1].endswith("5/5 passed\n"))

    def test_selftest_failure_output_and_return(self):
        outputs = []
        for module in (self.original, self.recovered):
            original_truth = module._TRUTH
            buffer = io.StringIO()
            try:
                module._TRUTH = [(original_truth[0][0], "deliberately-wrong")]
                with contextlib.redirect_stdout(buffer):
                    result = module._selftest()
            finally:
                module._TRUTH = original_truth
            outputs.append((result, buffer.getvalue()))
        self.assertEqual(outputs[0], outputs[1])
        self.assertFalse(outputs[1][0])
        self.assertTrue(outputs[1][1].startswith("FAIL "))
        self.assertTrue(outputs[1][1].endswith("0/1 passed\n"))

    def test_cli(self):
        payload_hex = self.original._TRUTH[0][0]
        payload_b64 = base64.b64encode(bytes.fromhex(payload_hex)).decode()
        cases = [[], [payload_hex], [payload_b64], [payload_hex, "1"],
                 [payload_b64, "1"], [""], ["00"], ["00 "], ["not-valid"],
                 [payload_hex, "not-an-integer"]]
        for args in cases:
            results = []
            for suffix in ("pyc", "py"):
                proc = subprocess.run(
                    [sys.executable, str(DECRYPT / f"unwrap_spade.{suffix}"), *args],
                    capture_output=True, text=True, check=False,
                )
                # Traceback paths/line numbers intentionally differ.  Compare
                # the error type/message and all ordinary CLI output instead.
                last_error = proc.stderr.splitlines()[-1:] if proc.stderr else []
                results.append((proc.returncode, proc.stdout, last_error))
            with self.subTest(args=args):
                self.assertEqual(*results)


if __name__ == "__main__":
    unittest.main()
