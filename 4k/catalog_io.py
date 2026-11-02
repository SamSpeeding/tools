"""Small, standard-library-only I/O helpers for the local catalog."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit


class FetchError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, interval=0.2, timeout=35, retries=3):
        self.interval, self.timeout, self.retries = interval, timeout, retries
        self._lock, self._next = threading.Lock(), 0.0
        self.requests = 0

    def get(self, url, max_bytes=32 * 1024 * 1024):
        if urlsplit(url).scheme not in ('http', 'https'):
            raise FetchError('仅支持 HTTP/HTTPS')
        last = None
        for attempt in range(self.retries):
            with self._lock:
                wait = self._next - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self._next = time.monotonic() + self.interval
                self.requests += 1
            with tempfile.TemporaryDirectory(prefix='4k-http-') as tmp:
                headers_path = Path(tmp) / 'headers'
                command = [
                    '/usr/bin/curl', '--silent', '--show-error', '--location',
                    '--proto', '=http,https', '--proto-redir', '=http,https',
                    '--connect-timeout', '10', '--max-time', str(self.timeout),
                    '--max-filesize', str(max_bytes), '--compressed',
                    '--user-agent', '4k-personal-catalog/1.0',
                    '--header', 'Accept: */*', '--referer', 'https://4kbt.org/',
                    '--dump-header', str(headers_path), '--write-out', '\n%{http_code}', url,
                ]
                process = subprocess.run(command, capture_output=True, timeout=self.timeout + 10)
                body, _, code = process.stdout.rpartition(b'\n')
                status = int(code) if code.isdigit() else 0
                headers = {}
                if headers_path.exists():
                    for line in headers_path.read_text(errors='replace').splitlines():
                        if line.startswith('HTTP/'):
                            headers = {}
                        elif ':' in line:
                            k, v = line.split(':', 1)
                            headers[k.lower()] = v.strip()
                if not process.returncode and 200 <= status < 300:
                    if len(body) > max_bytes:
                        raise FetchError('响应超出大小限制', status)
                    return body, headers
                detail = process.stderr.decode(errors='replace').strip()[:200]
                last = FetchError(f'HTTP {status or "连接失败"}: {detail}', status)
                if status in (400, 401, 403, 404, 410):
                    raise last
                if attempt + 1 < self.retries:
                    retry_after = headers.get('retry-after', '')
                    time.sleep(min(30, int(retry_after)) if retry_after.isdigit() else 2 ** attempt)
        raise last

    def json(self, url):
        body, headers = self.get(url)
        try:
            return json.loads(body), headers
        except (ValueError, UnicodeError) as exc:
            raise FetchError('响应不是有效 JSON') from exc


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f'{path.name} 不是有效 JSON；为保护已有数据，本次停止。') from exc


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


@contextlib.contextmanager
def archive_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    state = root / '.state'
    state.mkdir(exist_ok=True)
    with (state / 'archive.lock').open('a+') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('已有采集或封面下载任务运行，请等待它结束。') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def image_format(data):
    """Reject HTML/error bodies and obvious truncation before marking a cover complete."""
    if len(data) < 16:
        return None
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp' if int.from_bytes(data[4:8], 'little') + 8 == len(data) else None
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png' if data.endswith(b'IEND\xaeB`\x82') else None
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg' if data.rstrip().endswith(b'\xff\xd9') else None
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif' if data.rstrip().endswith(b';') else None
    if data[4:8] == b'ftyp' and b'avif' in data[8:40]:
        offset = 0
        while offset + 8 <= len(data):
            size = int.from_bytes(data[offset:offset + 4], 'big')
            if size == 0:
                return 'avif'
            if size < 8 or offset + size > len(data):
                return None
            offset += size
        return 'avif' if offset == len(data) else None
    return None


def safe_image_path(root, relative):
    if not isinstance(relative, str):
        raise ValueError('封面路径无效')
    path = (root / relative).resolve()
    if not path.is_relative_to((root / 'img').resolve()):
        raise ValueError('封面路径必须位于 img 目录')
    return path
