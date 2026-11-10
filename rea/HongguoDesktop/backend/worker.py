"""Fixed JSONL command protocol; stdout is reserved for protocol responses."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ('runtime' if (ROOT / 'runtime').exists() else '.runtime')
sys.path.insert(0, str(RUNTIME / 'site-packages'))
sys.dont_write_bytecode = True
PROTOCOL = sys.stdout
sys.stdout = sys.stderr

import concurrent.futures
import json
import re
import threading
import traceback
from app_api import AppAPI, cover_url, text
from hongguo_signer import LocalSigner
from hongguo_download import atomic_json
from jobs import JobQueue
from playback import PlaybackManager


class Worker:
    def __init__(self, data_dir, emit):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        os.environ['HG_DATA_DIR'] = str(self.data_dir)
        self.emit = emit
        self.lock = threading.RLock()
        self.sign_lock = threading.Lock()
        self.signer = None
        self.closing = False
        self.details = {}
        self.settings_path = self.data_dir / 'settings.json'
        self.settings = {'directory': str(Path.home() / 'Downloads/HongguoDesktop')}
        if self.settings_path.exists():
            self.settings.update(json.loads(self.settings_path.read_text()))
        self.device = json.loads((ROOT / 'config/devices.json').read_text(encoding='utf-8-sig'))[0]
        self.queue = JobQueue(self.data_dir, self.api, ROOT / 'vendor', emit)
        self.playback = PlaybackManager(self.api, ROOT / 'vendor', emit)

    def api(self):
        with self.sign_lock:
            if self.closing:
                raise RuntimeError('应用正在退出')
            if self.signer is None:
                signer = LocalSigner(ROOT / 'vendor')
                signer.__enter__()
                self.signer = signer
        return AppAPI(ROOT / 'config/config.json', self.signer.url, self.signer.token,
                      device=self.device, timeout=35)

    def call(self, method, p):
        if method == 'state':
            return {'settings': dict(self.settings), 'jobs': self.queue.snapshot()}
        if method == 'settings':
            directory = Path(p['directory']).expanduser()
            if not directory.is_absolute():
                raise ValueError('请选择完整的保存路径')
            directory.mkdir(parents=True, exist_ok=True)
            if not os.access(directory, os.W_OK):
                raise ValueError('所选文件夹不可写')
            with self.lock:
                self.settings['directory'] = str(directory.resolve())
                atomic_json(self.settings_path, self.settings)
                return dict(self.settings)
        if method in ('cancel', 'retry', 'folder'):
            return self.queue.action(p['id'], method)
        if method == 'playback_close':
            self.playback.close(str(p['id']))
            return {'closed': True}
        if method in ('enqueue', 'playback_open'):
            with self.lock:
                detail = self.details.get(p['series_id'])
            if not detail:
                raise ValueError('请先重新打开剧详情')
            if method == 'playback_open':
                return self.playback.start(detail, int(p['index']), p['quality'],
                                           request_id=str(p.get('request_id', ''))[:80])
            return self.queue.enqueue(detail, int(p['index']), p['quality'], self.settings['directory'])
        api = self.api()
        try:
            if method == 'search':
                query = str(p.get('query', '')).strip()
                if not query or len(query) > 100:
                    raise ValueError('请输入 1 至 100 字的搜索内容')
                return api.search_page(query, p.get('cursor'))
            if method == 'rank':
                return api.rank_page(p.get('category', 'all'), p.get('board', 'hot'), p.get('cursor'))
            if method in ('category', 'latest', 'filters'):
                return api.category(p.get('genre', 'short_play'), p.get('selections'), p.get('cursor'),
                                    panel=method == 'filters', latest=method == 'latest')
            if method == 'detail':
                sid = str(p.get('series_id', ''))
                if not re.fullmatch(r'\d{10,24}', sid):
                    raise ValueError('无效的剧目 ID')
                result = api.detail(sid)
                with self.lock:
                    self.details[sid] = result
                m = result['meta']
                return {'series_id': sid,
                        'meta': {'title': text(m['title']), 'intro': text(m['intro']),
                                 'cover': cover_url(m['cover']), 'status': m['status'],
                                 'episode_cnt': m['episode_cnt'], 'score': text(m['score']),
                                 'play_cnt': str(m['play_cnt'])},
                        'complete': result['complete'], 'issues': result['issues'],
                        'episodes': [{'index': e['index'], 'vid': e['vid'], 'title': text(e['title'])}
                                     for e in result['episodes']]}
            raise ValueError('不支持的操作')
        finally:
            api.close()

    def close(self):
        self.closing = True
        self.playback.shutdown()
        self.queue.close()
        with self.sign_lock:
            if self.signer:
                self.signer.mark_success()
                self.signer.__exit__(None, None, None)


def main():
    output_lock = threading.Lock()

    def emit(data):
        with output_lock:
            try:
                PROTOCOL.write(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')
                PROTOCOL.flush()
            except BrokenPipeError:
                # Parent may be force-closed. State persistence must still finish.
                pass

    worker = Worker(sys.argv[1], emit)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    def handle(request):
        try:
            value = worker.call(request['method'], request.get('params') or {})
            emit({'id': request['id'], 'result': value})
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            emit({'id': request['id'], 'error': str(exc)[:600]})

    emit({'event': 'ready'})
    try:
        for line in sys.stdin:
            request = json.loads(line)
            if request.get('method') == 'shutdown':
                break
            # Preserve ordering for task/settings mutations and subsequent state
            # reads. Network discovery stays concurrent and cannot block browsing.
            if request.get('method') in {'search', 'rank', 'category', 'latest', 'filters', 'detail'}:
                pool.submit(handle, request)
            else:
                handle(request)
    finally:
        worker.close()
        pool.shutdown(wait=True, cancel_futures=True)


if __name__ == '__main__':
    main()
