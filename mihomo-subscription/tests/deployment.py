#!/usr/bin/env python3
"""Bundle HTTP contract and publish/rollback tests; no real FTP or nodes are contacted."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deploy', ROOT / 'bin/deploy.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class FakeFTP:
    def __init__(self, files):
        self.files = files
        self.renames = 0
        self.fail_rename = 0
        self.interrupt_rename = 0
        self.bad_upload = False

    def nlst(self):
        return list(self.files)

    def retrbinary(self, command, callback):
        callback(self.files[command[5:]])

    def storbinary(self, command, file, blocksize):
        self.files[command[5:]] = file.read() + (b'corrupt' if self.bad_upload else b'')

    def sendcmd(self, command):
        return '200'

    def rename(self, source, target):
        self.renames += 1
        if self.fail_rename == self.renames:
            raise OSError('simulated rename timeout')
        self.files[target] = self.files.pop(source)
        if self.interrupt_rename == self.renames:
            raise KeyboardInterrupt()

    def delete(self, name):
        self.files.pop(name, None)

    def close(self):
        pass

    def quit(self):
        pass


class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='mihomo-bundle-tests-')
        cls.directory = Path(cls.temp.name)
        cls.password = 'test-only-subscription-password'
        script = '''require $argv[1] . '/src/bundle.php';
$s = require $argv[1] . '/config.example.php';
$s['access_password'] = 'test-only-subscription-password';
$s['custom'] = ['direct_domains' => ['custom.example'], 'hosts' => ['nas.home.arpa' => '192.168.31.100']];
$p = [];
foreach (communityRuleSources() as $name => $source) {
    $p[$name] = $source['behavior'] === 'domain' ? ['exact.example', '+.suffix.example'] : ['10.0.0.0/8', 'fc00::/7'];
}
echo json_encode(writeDeploymentBundle($s, ['updated_at'=>time(), 'payloads'=>$p], $argv[2]));'''
        result = subprocess.run(['php', '-r', script, str(ROOT), str(cls.directory)], capture_output=True, check=True)
        cls.manifest = json.loads(result.stdout)
        cls.meta, cls.bodies = deploy.read_bundle(cls.directory / 'config.php')
        cls.original = (cls.directory / 'config.php').read_bytes()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.endpoint = f'http://127.0.0.1:{port}/index.php'
        cls.server = subprocess.Popen(['php', '-d', 'memory_limit=16M', '-d', 'opcache.enable_cli=1',
                                      '-S', f'127.0.0.1:{port}', '-t', str(cls.directory)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1):
                    break
            except OSError:
                time.sleep(.02)

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=5)
        cls.temp.cleanup()

    def setUp(self):
        (self.directory / 'config.php').write_bytes(self.original)

    def test_authenticated_output_and_custom_merge(self):
        deploy.verify_endpoint(self.endpoint, self.password, self.meta)
        status, headers, body = deploy.http_response(self.endpoint + '?format=json&password=' + self.password)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'private, no-store')
        data = json.loads(body)
        self.assertEqual(data['hosts']['nas.home.arpa'], '192.168.31.100')
        self.assertIn('DOMAIN-SUFFIX,custom.example,DIRECT', data['rules'])
        self.assertEqual(len(data['rule-providers']), 8)
        self.assertNotIn(self.password.encode(), body)

    def test_auth_methods_and_format(self):
        cases = [('?password[]=x', None, 'GET', 401),
                 ('?password=' + self.password, 'wrong', 'GET', 401),
                 ('?format[]=json', self.password, 'GET', 400),
                 ('?format=xml', self.password, 'GET', 400),
                 ('', self.password, 'POST', 405)]
        for suffix, password, method, expected in cases:
            with self.subTest(suffix=suffix, method=method):
                self.assertEqual(deploy.http_response(self.endpoint + suffix, password, method)[0], expected)
        status, headers, body = deploy.http_response(self.endpoint, self.password, 'HEAD')
        self.assertEqual(status, 200)
        self.assertEqual(body, b'')
        self.assertEqual(int(headers['Content-Length']), len(self.bodies['yaml']))

    def test_staged_config_is_not_public(self):
        path = self.directory / '.config-staged.php'
        path.write_bytes(self.original)
        try:
            status, _, body = deploy.http_response(self.endpoint.replace('index.php', path.name))
            self.assertEqual((status, body), (404, b''))
        finally:
            path.unlink()

    def test_custom_html_404_page_is_allowed(self):
        original = deploy.http_response
        def response(url, *args, **kwargs):
            if url.endswith('/config.php'):
                return 404, {'Content-Type':'text/html'}, b'<html><body>Not Found</body></html>'
            return original(url, *args, **kwargs)
        with patch.object(deploy, 'http_response', side_effect=response):
            deploy.verify_endpoint(self.endpoint, self.password, self.meta)

    def test_config_source_with_404_is_still_rejected(self):
        original = deploy.http_response
        def response(url, *args, **kwargs):
            if url.endswith('/config.php'):
                return 404, {'Content-Type':'text/plain'}, self.original
            return original(url, *args, **kwargs)
        with patch.object(deploy, 'http_response', side_effect=response):
            with self.assertRaises(deploy.DeploymentError):
                deploy.verify_endpoint(self.endpoint, self.password, self.meta)

    def test_corruption_truncation_and_missing_bundle(self):
        path = self.directory / 'config.php'
        for content in (self.original[:-1], self.original[:-1] + b'X', b'not a bundle'):
            path.write_bytes(content)
            self.assertEqual(deploy.http_response(self.endpoint, self.password)[0], 503)
        path.unlink()
        self.assertEqual(deploy.http_response(self.endpoint, self.password)[0], 503)

    def test_replacement_is_visible_without_opcache_reset(self):
        path = self.directory / 'config.php'
        changed = self.original.replace(deploy.sha256(self.password.encode()).encode(),
                                        deploy.sha256(b'new-test-password').encode(), 1)
        temp = self.directory / '.next.php'
        temp.write_bytes(changed)
        temp.replace(path)
        self.assertEqual(deploy.http_response(self.endpoint, self.password)[0], 401)
        self.assertEqual(deploy.http_response(self.endpoint, 'new-test-password')[0], 200)

    def publish(self, ftp, verifier=lambda *_: None):
        settings = {'host':'example.test', 'username':'test', 'password':'test',
                    'remote_dir':'/miwifi', 'endpoint':'https://example.test/miwifi/index.php'}
        with patch.object(deploy.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            deploy.deploy(settings, self.directory, self.manifest, self.password, self.meta,
                          connector=lambda _: ftp, verifier=verifier, backup_root=self.directory / 'backups')

    def test_publish_changes_only_two_files(self):
        files = {'unrelated.php':b'keep'}
        self.publish(FakeFTP(files))
        self.assertEqual(set(files), {'index.php','config.php','unrelated.php'})
        self.assertEqual(files['unrelated.php'], b'keep')
        self.assertEqual(files['config.php'], self.original)

    def test_decline_and_noninteractive_never_confirm(self):
        with patch.object(sys.stdin, 'isatty', return_value=True):
            for answer in ('', 'n', 'no', 'anything'):
                with patch('builtins.input', return_value=answer):
                    self.assertFalse(deploy.confirm_publish())
            with patch('builtins.input', return_value='y'):
                self.assertTrue(deploy.confirm_publish())
        with patch.object(sys.stdin, 'isatty', return_value=False), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(deploy.confirm_publish())

    def test_verification_failure_rolls_back_both_files(self):
        previous = {'index.php':b'old index', 'config.php':b'old config', 'keep':b'unrelated'}
        files = dict(previous)
        def fail(*_):
            raise OSError('simulated HTTP failure')
        with self.assertRaisesRegex(deploy.DeploymentError, '已恢复'):
            self.publish(FakeFTP(files), fail)
        self.assertEqual(files, previous)

    def test_rollback_reports_the_specific_verification_failure(self):
        files = {'index.php':b'old index', 'config.php':b'old config'}
        def fail(*_):
            raise deploy.DeploymentError('JSON 订阅校验失败（HTTP 500）。')
        with self.assertRaisesRegex(deploy.DeploymentError, 'JSON.*500.*已恢复'):
            self.publish(FakeFTP(files), fail)

    def test_second_rename_failure_and_interruption_roll_back(self):
        previous = {'index.php':b'old index', 'config.php':b'old config'}
        for mode in ('fail_rename', 'interrupt_rename'):
            files = dict(previous)
            ftp = FakeFTP(files)
            setattr(ftp, mode, 2)
            with self.assertRaisesRegex(deploy.DeploymentError, '已恢复'):
                self.publish(ftp)
            self.assertEqual(files, previous)

    def test_failed_first_publish_restores_empty_directory(self):
        files = {'keep':b'unrelated'}
        ftp = FakeFTP(files)
        ftp.fail_rename = 2
        with self.assertRaisesRegex(deploy.DeploymentError, '已恢复'):
            self.publish(ftp)
        self.assertEqual(files, {'keep':b'unrelated'})

    def test_corrupt_upload_never_replaces_current_files(self):
        files = {'index.php':b'old index', 'config.php':b'old config'}
        ftp = FakeFTP(files)
        ftp.bad_upload = True
        with self.assertRaisesRegex(deploy.DeploymentError, '正式文件未替换'):
            self.publish(ftp)
        self.assertEqual(files, {'index.php':b'old index', 'config.php':b'old config'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
