"""One local playback session: signed model lookup, bounded CDN reads, clear MP4."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import secrets
import socket
import threading
from urllib.parse import urlsplit

import requests

from hongguo_download import QUALITIES, choose_track, load_decrypt_modules, preflight
from mp4_stream import MP4Stream, MediaFormatError


class PlaybackClosed(RuntimeError):
    pass


class RangeReader:
    """A small LRU of encrypted blocks; never silently accept a full-file response."""
    def __init__(self, urls, total, check, block_size=256 * 1024, cache_blocks=8):
        self.urls = list(dict.fromkeys(u for u in urls if u and urlsplit(u).scheme in ('http', 'https')))
        if not self.urls or total <= 0:
            raise RuntimeError('视频模型缺少地址或大小')
        self.total, self.check = total, check
        self.block_size, self.cache_blocks = block_size, cache_blocks
        self.cache = OrderedDict()
        self.lock = threading.RLock()
        self.session = requests.Session()
        self.closed = False
        self.received = 0

    def _block(self, start):
        with self.lock:
            self.check()
            if self.closed:
                raise PlaybackClosed('播放已停止')
            if start in self.cache:
                self.cache.move_to_end(start)
                return self.cache[start]
            end = min(self.total - 1, start + self.block_size - 1)
            expected = end - start + 1
            message = '视频分段读取失败，请重新播放'
            for url in self.urls:
                self.check()
                try:
                    with self.session.get(url, headers={'Range': f'bytes={start}-{end}',
                            'Accept-Encoding': 'identity'}, stream=True, timeout=(10, 15)) as response:
                        if response.status_code in (401, 403, 410):
                            message = '视频地址已失效，请重新播放'
                            continue
                        # CDN endpoints that ignore Range would force a full download.
                        if response.status_code != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{self.total}':
                            message = '视频源没有返回正确的字节范围'
                            continue
                        if response.headers.get('Content-Encoding', 'identity') not in ('', 'identity'):
                            message = '视频源返回了压缩的字节范围'
                            continue
                        chunks, size = [], 0
                        for chunk in response.iter_content(64 * 1024):
                            self.check()
                            size += len(chunk)
                            if size > expected:
                                raise MediaFormatError('视频分段长度超过请求范围')
                            chunks.append(chunk)
                        if size != expected:
                            message = '视频分段不完整，请重新播放'
                            continue
                        data = b''.join(chunks)
                        self.received += size
                        self.cache[start] = data
                        while len(self.cache) > self.cache_blocks:
                            self.cache.popitem(last=False)
                        return data
                except requests.RequestException:
                    message = '视频连接失败或超时，请重新播放'
            raise RuntimeError(message)

    def read(self, start, end):
        if not 0 <= start <= end < self.total:
            raise MediaFormatError('视频读取范围无效')
        pieces = []
        cursor = start
        while cursor <= end:
            base = cursor // self.block_size * self.block_size
            block = self._block(base)
            stop = min(end + 1, base + len(block))
            pieces.append(block[cursor - base:stop - base])
            cursor = stop
        return b''.join(pieces)

    def close(self):
        # Cancellation is set first by the owner; an in-flight bounded read then
        # unwinds before its requests.Session is closed from the cleanup thread.
        with self.lock:
            self.closed = True
            self.cache.clear()
            self.session.close()


def parse_range(header, total):
    if not header:
        return 0, total - 1, False
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', header.strip())
    if not match or not any(match.groups()):
        raise ValueError('invalid range')
    left, right = match.groups()
    if not left:
        size = int(right)
        if size <= 0:
            raise ValueError('invalid suffix')
        return max(0, total - size), total - 1, True
    start, end = int(left), min(int(right), total - 1) if right else total - 1
    if start >= total or start > end:
        raise ValueError('unsatisfiable range')
    return start, end, True


class _Session:
    def __init__(self, detail, index, quality):
        self.id = secrets.token_urlsafe(24)
        self.stopped = threading.Event()
        self.reader = None
        self.stream = None
        self.future = None
        self.lock = threading.RLock()
        self.state = {'id': self.id, 'series_id': detail['series_id'], 'index': index,
                      'title': detail['meta']['title'], 'quality': quality,
                      'status': 'preparing', 'phase': '获取视频', 'revision': 0, 'error': ''}

    def check(self):
        if self.stopped.is_set():
            raise PlaybackClosed('播放已停止')


class PlaybackManager:
    def __init__(self, api_factory, vendor, emit):
        self.api_factory, self.vendor, self.emit = api_factory, vendor, emit
        self.lock = threading.RLock()
        self.current = None
        self.server = None
        self.closing = False
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='playback')

    def _update(self, session, **changes):
        with self.lock:
            session.check()
            if self.current is not session or self.closing:
                raise PlaybackClosed('播放已切换')
            with session.lock:
                session.state.update(changes)
                session.state['revision'] += 1
                state = dict(session.state)
            self.emit({'event': 'playback', 'playback': state})
            return state

    def snapshot(self):
        with self.lock:
            if self.current is None:
                return None
            with self.current.lock:
                return dict(self.current.state)

    def start(self, detail, index, quality, request_id=''):
        if not detail.get('complete'):
            raise ValueError('请重新加载完整的分集信息')
        if quality not in QUALITIES:
            raise ValueError('无效的清晰度')
        episode = next((e for e in detail['episodes'] if e.get('index') == index), None)
        if not episode or not episode.get('vid'):
            raise ValueError('没有找到这一集')
        with self.lock:
            if self.closing:
                raise PlaybackClosed('应用正在退出')
            self.close()
            if self.server is None:
                manager = self

                class Handler(_Handler):
                    owner = manager

                self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
                self.server.daemon_threads = True
                threading.Thread(target=self.server.serve_forever, daemon=True, name='playback-http').start()
            session = _Session(detail, index, quality)
            session.state['request_id'] = request_id
            self.current = session
            initial = dict(session.state)
            session.future = self.pool.submit(self._prepare, session, episode['vid'])
            return initial

    def _prepare(self, session, vid):
        api = None
        try:
            session.check()
            preflight(self.vendor)
            api = self.api_factory()
            result = api.models([vid], on_source=lambda source: self._update(session, **source))
            session.check()
            model = result.get('models', {}).get(vid)
            if not model:
                errors = result.get('errors') or []
                reason = errors[-1].get('error') if errors else '平台没有返回视频模型'
                raise RuntimeError(f'视频模型请求失败：{reason}')
            track = choose_track(model, session.state['quality'])
            self._update(session, phase='准备播放', **{k: model.get(k) for k in (
                'model_api', 'model_fallback', 'model_fallback_reason')})
            total = int((track.get('video_meta') or {}).get('size') or track.get('size') or 0)
            reader = RangeReader([track.get('main_url'), track.get('backup_url')], total, session.check)
            session.reader = reader
            info = track.get('encrypt_info') or {}
            keys = [None]
            modules = None
            if info.get('encrypt'):
                if info.get('encryption_method') != 'cenc-aes-ctr' or not info.get('spade_a'):
                    raise MediaFormatError('暂不支持此视频的加密格式')
                modules = load_decrypt_modules(self.vendor)
                keys = []
                for mode in (0, 1):
                    key = modules['unwrap_spade'].spade_to_key(info['spade_a'], mode)
                    if isinstance(key, str) and re.fullmatch('[0-9a-f]{32}', key) and bytes.fromhex(key) not in keys:
                        keys.append(bytes.fromhex(key))
                if not keys:
                    raise MediaFormatError('无法解析此集的解密参数')
            stream = None
            failure = None
            for key in keys:
                session.check()
                try:
                    candidate = MP4Stream(reader.read, total, key)
                    if key is not None:
                        candidate.verify_key(modules['oracle']._nal_ok)
                    stream = candidate
                    break
                except MediaFormatError as exc:
                    failure = exc
            if stream is None:
                raise failure or MediaFormatError('无法准备此集视频')
            session.check()
            session.stream = stream
            self._update(session, status='ready', phase='就绪', total=total,
                         initial_bytes=reader.received,
                         url=f'http://127.0.0.1:{self.server.server_port}/media/{session.id}.mp4')
        except PlaybackClosed:
            pass
        except Exception as exc:
            try:
                self._update(session, status='failed', phase='播放失败', error=str(exc)[:500])
            except PlaybackClosed:
                pass
        finally:
            if api is not None:
                api.close()
            if session.reader and (session.stopped.is_set() or session.stream is None):
                session.reader.close()

    def lookup(self, path):
        with self.lock:
            session = self.current
            if not session or path != f'/media/{session.id}.mp4' or session.stopped.is_set():
                return None
            return session

    def failed(self, session, exc):
        try:
            self._update(session, status='failed', phase='播放失败', error=str(exc)[:500])
        except PlaybackClosed:
            pass

    def close(self, session_id=None):
        with self.lock:
            session = self.current
            if not session or (session_id is not None and session.id != session_id):
                return
            self.current = None
            session.stopped.set()
            if session.future:
                session.future.cancel()
            if session.reader:
                threading.Thread(target=session.reader.close, daemon=True).start()

    def shutdown(self):
        with self.lock:
            self.closing = True
            self.close()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        self.pool.shutdown(wait=False, cancel_futures=True)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, *_):
        pass

    def do_GET(self):
        self._serve(True)

    def do_HEAD(self):
        self._serve(False)

    def _empty(self, status, total=None):
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        if total is not None:
            self.send_header('Content-Range', f'bytes */{total}')
        self.end_headers()

    def _serve(self, body):
        session = self.owner.lookup(urlsplit(self.path).path)
        if session is None:
            self._empty(404)
            return
        stream = session.stream
        if stream is None or session.state['status'] != 'ready':
            self._empty(503)
            return
        try:
            start, end, partial = parse_range(self.headers.get('Range'), stream.total)
        except ValueError:
            self._empty(416, stream.total)
            return
        headers_sent = False
        try:
            session.check()
            # Obtain the first block before committing success headers.
            stop = min(end, start + 256 * 1024 - 1)
            block = stream.read_range(start, stop) if body else None
            self.send_response(206 if partial else 200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{stream.total}')
            self.end_headers()
            headers_sent = True
            while body and start <= end:
                session.check()
                self.wfile.write(block)
                self.wfile.flush()
                start = stop + 1
                if start <= end:
                    stop = min(end, start + 256 * 1024 - 1)
                    block = stream.read_range(start, stop)
        except (BrokenPipeError, ConnectionResetError, socket.timeout, PlaybackClosed):
            self.close_connection = True
        except Exception as exc:
            self.owner.failed(session, exc)
            if not headers_sent:
                self._empty(502)
            self.close_connection = True
