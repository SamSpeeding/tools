import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import hongguo
from hongguo_signer import LocalSigner


class SignerLogTests(unittest.TestCase):
    def test_cli_keeps_logs_for_partial_failure_and_exceptions_only(self):
        for outcome in (0, 2, RuntimeError('request failed'), KeyboardInterrupt()):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                signer = LocalSigner(hongguo.ROOT / 'vendor', java='/unused/java')
                signer.url = 'http://127.0.0.1:1'
                signer.log_path = Path(directory) / 'signer-test.log'
                signer.log = signer.log_path.open('w')
                signer.log.write('diagnostic output\n')
                export = {'side_effect': outcome} if isinstance(outcome, BaseException) else {'return_value': outcome}
                with patch('hongguo.LocalSigner', return_value=signer), \
                     patch.object(LocalSigner, '__enter__', return_value=signer), \
                     patch('hongguo.export_series', **export), \
                     contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    args = ['--series-id', 'test', '--export-only']
                    if isinstance(outcome, BaseException):
                        with self.assertRaises(type(outcome)):
                            hongguo.main(args)
                    else:
                        self.assertEqual(hongguo.main(args), outcome)
                self.assertTrue(signer.log.closed)
                self.assertEqual(signer.log_path.exists(), outcome != 0)


if __name__ == '__main__':
    unittest.main()
