#!/usr/bin/env python3
"""Local build, explicit terminal confirmation, and two-file FTPS deployment."""
import argparse
import contextlib
import fcntl
import ftplib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
FILES = ('config.php', 'index.php')


class DeploymentError(Exception):
    pass


def failure_reason(error):
    """Expose useful controlled diagnostics, never arbitrary server/credential text."""
    if isinstance(error, DeploymentError):
        return str(error)
    if isinstance(error, (ftplib.error_perm, ftplib.error_temp)):
        code = str(error)[:3]
        return 'FTP 返回 ' + code if code.isdigit() else 'FTP 请求失败'
    if isinstance(error, (TimeoutError, socket.timeout)):
        return '网络请求超时'
    if isinstance(error, KeyboardInterrupt):
        return '用户中断发布'
    return type(error).__name__


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def run_checked(args, **kwargs):
    result = subprocess.run(args, capture_output=True, **kwargs)
    if result.returncode:
        # PHP errors and core diagnostics may contain configuration values.
        raise DeploymentError(f'{Path(args[0]).name} 执行失败；请检查配置及运行环境。')
    return result.stdout


def read_bundle(path):
    with path.open('rb') as file:
        if file.readline(256) != b'<?php http_response_code(404); exit; __halt_compiler();\n':
            raise DeploymentError('构建文件保护头不正确。')
        meta = json.loads(file.readline(16384))
        bodies = {}
        for kind in ('json', 'yaml'):
            part = meta['formats'][kind]
            bodies[kind] = file.read(part['bytes'])
            if sha256(bodies[kind]) != part['sha256']:
                raise DeploymentError('构建产物校验失败。')
        if file.read(1):
            raise DeploymentError('构建产物包含多余数据。')
    return meta, bodies


def subscription_password():
    return run_checked(['php', '-r',
        "$s = require $argv[1]; echo $s['access_password'];", str(ROOT / 'config.php')]).decode()


def http_response(url, password=None, method='GET'):
    request = urllib.request.Request(url, method=method)
    if password is not None:
        request.add_header('Authorization', 'Bearer ' + password)
    opener = urllib.request.build_opener(NoRedirect())
    try:
        response = opener.open(request, timeout=45)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read(32 * 1024 * 1024 + 1)


def verify_endpoint(endpoint, password, meta):
    for kind in ('json', 'yaml'):
        url = endpoint + '?' + urllib.parse.urlencode({'format': kind})
        status, headers, body = http_response(url, password)
        if status != 200:
            raise DeploymentError(f'{kind.upper()} 订阅校验失败（HTTP {status}）。')
        if sha256(body) != meta['formats'][kind]['sha256']:
            raise DeploymentError(f'{kind.upper()} 订阅内容与本次构建不一致（HTTP 200）。')
        if headers.get('X-Bundle-Revision') != meta['revision']:
            raise DeploymentError('线上配置版本与本次构建不一致。')
    status = http_response(endpoint)[0]
    if status != 401:
        raise DeploymentError(f'未授权请求未被正确拒绝（HTTP {status}）。')
    config_url = urllib.parse.urljoin(endpoint, 'config.php')
    status, _, body = http_response(config_url)
    # Nginx error_page / fastcgi_intercept_errors may replace an empty PHP 404 with
    # an HTML error page. A response body alone is not evidence of data disclosure.
    exposes_bundle = any(marker in body for marker in
                         (b'__halt_compiler', b'"auth_sha256"', b'"proxies"', b'"rule-providers"'))
    if status != 404 or exposes_bundle:
        raise DeploymentError(f'配置文件的直接访问保护校验失败（HTTP {status}）。')


def validate_build(directory, manifest, password):
    for name in FILES:
        content = (directory / name).read_bytes()
        if sha256(content) != manifest['files'][name]['sha256']:
            raise DeploymentError('构建文件与清单不一致。')
        run_checked(['php', '-l', str(directory / name)])
    meta, bodies = read_bundle(directory / 'config.php')
    config = json.loads(bodies['json'])
    providers = config.get('rule-providers', {})
    if len(providers) != 8 or any(p.get('type') != 'inline' or not p.get('payload')
                                  or {'url', 'path', 'interval'} & p.keys() for p in providers.values()):
        raise DeploymentError('社区规则必须完整内嵌。')
    core = os.environ.get('MIHOMO_BIN') or shutil.which('mihomo') or str(ROOT / '.cache/mihomo')
    if not Path(core).is_file():
        raise DeploymentError('未找到 mihomo 核心，无法完成发布前校验；请设置 MIHOMO_BIN 或放入 .cache/mihomo。')
    with tempfile.TemporaryDirectory(prefix='mihomo-bundle-check-') as temp:
        temp = Path(temp)
        for kind in ('json', 'yaml'):
            path = temp / ('config.' + kind)
            path.write_bytes(bodies[kind])
            os.chmod(path, 0o600)
            state = temp / (kind + '-state')
            state.mkdir()
            run_checked([core, '-t', '-f', str(path), '-d', str(state)], timeout=45)
        # Check the exact two production files without any source/config/cache dependency.
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        server = subprocess.Popen(['php', '-d', 'memory_limit=16M', '-S', f'127.0.0.1:{port}',
                                   '-t', str(directory)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.1):
                        break
                except OSError:
                    if server.poll() is not None:
                        raise DeploymentError('本地校验服务器未能启动。')
                    time.sleep(.05)
            verify_endpoint(f'http://127.0.0.1:{port}/index.php', password, meta)
        finally:
            server.terminate()
            server.wait(timeout=5)
    return meta


def connect_ftp(settings):
    context = ssl.create_default_context()
    if settings.get('tls_ca_pem'):
        # Explicitly trust the pinned self-signed certificate for both TLS channels.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.load_verify_locations(cadata=settings['tls_ca_pem'])
    ftp = ftplib.FTP_TLS(context=context, timeout=45)
    try:
        ftp.connect(settings['host'], int(settings.get('port', 21)))
        ftp.auth()
        pin = settings.get('tls_cert_sha256')
        if pin and sha256(ftp.sock.getpeercert(binary_form=True)) != pin:
            raise DeploymentError('FTP 证书已变化，请核对服务器证书后更新本地设置。')
        ftp.login(settings['username'], settings['password'])
        ftp.prot_p()
        ftp.cwd(settings['remote_dir'])
        return ftp
    except Exception:
        ftp.close()
        raise


def remote_bytes(ftp, name):
    buffer = io.BytesIO()
    def accept(chunk):
        if buffer.tell() + len(chunk) > 64 * 1024 * 1024:
            raise DeploymentError('远端文件超过预期大小，停止发布。')
        buffer.write(chunk)
    ftp.retrbinary('RETR ' + name, accept)
    return buffer.getvalue()


def upload_verified(ftp, name, body):
    ftp.storbinary('STOR ' + name, io.BytesIO(body), blocksize=65536)
    ftp.sendcmd('SITE CHMOD 644 ' + name)
    if sha256(remote_bytes(ftp, name)) != sha256(body):
        raise DeploymentError('FTP 上传文件校验失败。')


def deploy(settings, directory, manifest, password, meta, connector=connect_ftp,
           verifier=verify_endpoint, backup_root=None):
    parsed = urllib.parse.urlsplit(settings['endpoint'])
    if parsed.scheme != 'https' or parsed.query or parsed.fragment or parsed.username:
        raise DeploymentError('发布检查地址必须是无密码、无查询参数的 HTTPS 入口。')
    for field in ('host', 'username', 'password', 'remote_dir'):
        if not isinstance(settings.get(field), str) or not settings[field] or '\n' in settings[field] or '\r' in settings[field]:
            raise DeploymentError('FTP 本地设置不完整。')
    backup_root = backup_root or ROOT / '.deploy-backups'
    backup = backup_root / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup_root, 0o700)
    previous = {}
    changed = []
    staged = []
    ftp = connector(settings)
    try:
        names = {Path(name).name for name in ftp.nlst()}
        for name in FILES:
            previous[name] = remote_bytes(ftp, name) if name in names else None
            if previous[name] is not None:
                (backup / name).write_bytes(previous[name])
                os.chmod(backup / name, 0o600)
        (backup / 'state.json').write_text(json.dumps({name: previous[name] is not None for name in FILES}))
        for name in FILES:
            body = (directory / name).read_bytes()
            if sha256(body) != manifest['files'][name]['sha256']:
                raise DeploymentError('确认发布后本地产物发生变化，已停止。')
            temporary = '.' + name[:-4] + '-' + uuid.uuid4().hex + '.php'
            staged.append(temporary)
            print('上传并校验：' + name, flush=True)
            upload_verified(ftp, temporary, body)
        for name, temporary in zip(FILES, staged):
            # Record uncertain rename outcomes too: a timeout may occur after the server applied it.
            changed.append(name)
            ftp.rename(temporary, name)
        for attempt in range(3):
            try:
                verifier(settings['endpoint'], password, meta)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2)
        print('发布成功，线上 JSON / YAML、鉴权和文件保护均已验证。', flush=True)
        print('入口：' + settings['endpoint'] + '（订阅密码不变）', flush=True)
    except (Exception, KeyboardInterrupt) as cause:
        if changed:
            with contextlib.suppress(Exception):
                ftp.close()
            rollback = None
            try:
                rollback = connector(settings)
                for name in reversed(changed):
                    if previous[name] is None:
                        if name in {Path(item).name for item in rollback.nlst()}:
                            rollback.delete(name)
                    else:
                        temporary = '.rollback-' + uuid.uuid4().hex + '.php'
                        upload_verified(rollback, temporary, previous[name])
                        rollback.rename(temporary, name)
            except (Exception, KeyboardInterrupt) as rollback_error:
                raise DeploymentError(f'发布失败：{failure_reason(cause)} 自动恢复也未完成（{failure_reason(rollback_error)}）；旧文件已备份在 .deploy-backups。') from rollback_error
            finally:
                if rollback:
                    with contextlib.suppress(Exception):
                        for temporary in staged:
                            with contextlib.suppress(Exception):
                                rollback.delete(temporary)
                        rollback.quit()
            raise DeploymentError(f'发布失败：{failure_reason(cause)} 已恢复发布前的两个文件。') from cause
        raise DeploymentError(f'上传未完成：{failure_reason(cause)} 正式文件未替换。') from cause
    finally:
        for temporary in staged:
            with contextlib.suppress(Exception):
                ftp.delete(temporary)
        with contextlib.suppress(Exception):
            ftp.quit()


def confirm_publish():
    if not sys.stdin.isatty():
        print('当前没有交互终端，仅保留本地产物；不会发布。')
        return False
    try:
        return input('\n构建成功，是否发布到线上？[y/N] ').strip().lower() in ('y', 'yes')
    except (EOFError, KeyboardInterrupt):
        return False


def main():
    parser = argparse.ArgumentParser(description='本地打包，终端确认后发布两个 PHP 文件。')
    parser.add_argument('--cached', action='store_true', help='明确使用已有本地规则快照，不访问上游')
    parser.add_argument('--build-only', action='store_true', help='只构建和校验，不询问也不发布')
    args = parser.parse_args()
    build = ROOT / '.build'
    build.mkdir(mode=0o700, exist_ok=True)
    with (build / 'deploy.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeploymentError('已有打包或发布任务运行中。')
        print('使用本地规则快照…' if args.cached else '正在获取最新社区规则并打包…', flush=True)
        command = ['php', str(ROOT / 'bin/build.php')]
        if args.cached:
            command.append('--cached')
        manifest = json.loads(run_checked(command, timeout=320))
        print(f"已打包 {manifest['rule_count']:,} 条规则，正在验证 mihomo 和独立 PHP 入口…", flush=True)
        password = subscription_password()
        meta = validate_build(build, manifest, password)
        print('校验通过。产物：' + str(build / 'index.php') + ' 和 config.php', flush=True)
        print('规则更新时间：' + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(meta['rules_updated_at'])), flush=True)
        if args.build_only or not confirm_publish():
            print('本次仅打包，未连接 FTP，也未改动线上文件。')
            return
        settings_path = ROOT / '.deploy.local.json'
        if not settings_path.is_file():
            raise DeploymentError('缺少本地 .deploy.local.json，请按 README 填写 FTP 信息。')
        settings = json.loads(settings_path.read_text())
        deploy(settings, build, manifest, password, meta)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n已取消。', file=sys.stderr)
        sys.exit(1)
    except DeploymentError as error:
        print('失败：' + str(error), file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        # Do not expose FTP credentials, subscription content or authenticated URLs.
        print('失败：' + type(error).__name__ + '；请检查网络与本地部署设置。', file=sys.stderr)
        sys.exit(1)
