"""Serial, persistent downloads. Media is published only after full validation."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid

import requests
from hongguo_download import (QUALITIES, safe_name, atomic_json, preflight, choose_track,
                             integrity, playable_file, digest_file, completed_file)

ACTIVE = {'queued', 'preparing', 'downloading', 'decrypting', 'verifying', 'cancelling'}


class Cancelled(Exception):
    pass


def publish_file(candidate, final):
    """Atomically publish a validated file, refusing an existing destination."""
    if sys.platform == 'darwin':
        # Same-directory staging guarantees the same volume. RENAME_EXCL keeps
        # the no-overwrite guarantee without a hard-link operation, which was
        # observed hanging in link(2) when publishing to this Mac's Downloads.
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(os.fsencode(candidate), os.fsencode(final), 0x00000004) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(final))
    elif os.name == 'nt':
        # Windows rename refuses an existing destination.
        os.rename(candidate, final)
    else:
        os.link(candidate, final)
        candidate.unlink()


def download(job, api_factory, vendor, update, check):
    preflight(vendor)
    folder = Path(job['directory']) / f"{safe_name(job['title'])}_{job['series_id']}"
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / f"第{job['index']:03d}集_{job['quality']}.mp4"
    check()
    if completed_file(final, job['vid'], job['quality']):
        update(model_api='local', model_api_state='cached', model_fallback=False, model_fallback_reason='')
        return str(final)
    if final.exists():
        raise RuntimeError('目标文件已存在，但校验记录不匹配。请先改名或移走该文件。')
    api = api_factory()
    try:
        with tempfile.TemporaryDirectory(prefix='.episode-', dir=folder) as temp, requests.Session() as session:
            source = Path(temp) / 'source.enc.mp4'
            error = '没有可用的视频地址'
            for attempt in range(2):
                check()
                update(status='preparing', progress=0)
                result = api.models([job['vid']], on_source=lambda source: update(**source))
                model = result.get('models', {}).get(job['vid'])
                if not model:
                    errors = result.get('errors') or []
                    message = errors[0].get('error') if errors else '未取得视频模型'
                    if attempt == 0:
                        check()
                        continue
                    raise RuntimeError(f'视频模型请求失败：{message}。请稍后重试。')
                try:
                    track = choose_track(model, job['quality'])
                except RuntimeError:
                    raise RuntimeError(f"此集没有 {job['quality']}，请在详情页选择其他清晰度。") from None
                size, expected, algorithm = integrity(track)
                fetched = False
                for url in dict.fromkeys([track.get('main_url'), track.get('backup_url')]):
                    check()
                    if not url or not url.startswith(('https://', 'http://')):
                        continue
                    try:
                        with session.get(url, stream=True, timeout=(15, 20)) as response:
                            response.raise_for_status()
                            count, last = 0, 0.0
                            digest = hashlib.new(algorithm)
                            with source.open('wb') as handle:
                                for chunk in response.iter_content(128 * 1024):
                                    check()
                                    count += len(chunk)
                                    if count > size:
                                        raise RuntimeError('下载大小超过平台声明值')
                                    handle.write(chunk)
                                    digest.update(chunk)
                                    if time.monotonic() - last > 0.2 or count == size:
                                        update(status='downloading', progress=round(count * 100 / size, 1), received=count, total=size)
                                        last = time.monotonic()
                            if count != size or digest.hexdigest() != expected:
                                raise RuntimeError('下载文件大小或哈希不匹配')
                            fetched = True
                            break
                    except requests.RequestException:
                        error = '视频下载连接失败或超时'
                    except RuntimeError as exc:
                        error = str(exc)
                if fetched:
                    break
            else:
                raise RuntimeError(error)
            check()
            candidate = Path(temp) / 'playable.mp4'
            verification = playable_file(source, track, candidate, vendor, check,
                                          lambda stage: update(status=stage, progress=100))
            check()
            verification.update(vid=job['vid'], index=job['index'], quality=job['quality'],
                                series_id=job['series_id'], bytes=candidate.stat().st_size,
                                sha256=digest_file(candidate), model_api=model.get('model_api', ''),
                                model_fallback=model.get('model_fallback', False),
                                model_fallback_reason=model.get('model_fallback_reason', ''))
            publish_file(candidate, final)
            atomic_json(final.with_suffix('.json'), verification)
            return str(final)
    finally:
        api.close()


class JobQueue:
    def __init__(self, data_dir, api_factory, vendor, emit, runner=download):
        self.path = Path(data_dir) / 'tasks.json'
        self.api_factory, self.vendor, self.emit, self.runner = api_factory, vendor, emit, runner
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.cancel = threading.Event()
        self.stopping = False
        self.current = None
        self.jobs = []
        if self.path.exists():
            self.jobs = json.loads(self.path.read_text())
        for job in self.jobs:
            if job['status'] in ACTIVE:
                job.update(status='interrupted', error='上次退出时未完成，点击重试从头下载。')
        self.save()
        self.thread = threading.Thread(target=self.run, daemon=True, name='download-queue')
        self.thread.start()

    def save(self):
        atomic_json(self.path, self.jobs)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.jobs))

    def notify(self, job):
        job['revision'] = job.get('revision', 0) + 1
        self.save()
        self.emit({'event': 'job', 'job': dict(job)})

    def enqueue(self, detail, index, quality, directory):
        if quality not in QUALITIES:
            raise ValueError('不支持的清晰度')
        if not detail['complete']:
            raise ValueError('平台返回的分集信息不完整，暂不能下载。请重新加载详情。')
        episode = next((e for e in detail['episodes'] if e['index'] == index), None)
        if not episode or not episode['vid']:
            raise ValueError('没有找到这一集')
        with self.lock:
            if self.stopping:
                raise ValueError('应用正在退出')
            for job in self.jobs:
                if (job['series_id'], job['vid'], job['quality']) == (detail['series_id'], episode['vid'], quality):
                    if job['status'] == 'completed' and not completed_file(Path(job['file']), job['vid'], quality):
                        job.update(status='failed', error='已下载文件已被移动或更改，请处理后重试。')
                        self.notify(job)
                    return dict(job)
            job = {'id': uuid.uuid4().hex, 'series_id': detail['series_id'], 'title': detail['meta']['title'],
                   'vid': episode['vid'], 'index': index, 'quality': quality, 'directory': directory,
                   'status': 'queued', 'progress': 0, 'created_at': time.time(), 'error': '', 'file': ''}
            self.jobs.append(job)
            self.notify(job)
            self.wake.set()
            return dict(job)

    def action(self, job_id, action):
        with self.lock:
            job = next((j for j in self.jobs if j['id'] == job_id), None)
            if not job:
                raise ValueError('任务不存在')
            if action == 'cancel' and job['status'] in ACTIVE:
                if self.current == job_id:
                    self.cancel.set()
                    job['status'] = 'cancelling'
                else:
                    job['status'] = 'cancelled'
                self.notify(job)
            elif action == 'retry' and job['status'] in {'failed', 'cancelled', 'interrupted'}:
                job.update(status='queued', error='', progress=0, model_api='', model_api_state='',
                           model_fallback=False, model_fallback_reason='')
                self.notify(job)
                self.wake.set()
            elif action == 'folder':
                if job['status'] != 'completed' or not completed_file(Path(job['file']), job['vid'], job['quality']):
                    raise ValueError('成品文件不存在或校验记录不匹配')
                return {'path': str(Path(job['file']).parent)}
            return dict(job)

    def run(self):
        while True:
            self.wake.wait()
            with self.lock:
                if self.stopping:
                    return
                job = next((j for j in self.jobs if j['status'] == 'queued'), None)
                if not job:
                    self.wake.clear()
                    continue
                self.current = job['id']
                self.cancel.clear()
                job['status'] = 'preparing'
                self.notify(job)

            def check():
                if self.cancel.is_set() or self.stopping:
                    raise Cancelled()

            def update(**fields):
                check()
                with self.lock:
                    job.update(fields)
                    self.notify(job)

            try:
                result = self.runner(dict(job), self.api_factory, self.vendor, update, check)
                with self.lock:
                    job.update(status='completed', progress=100, file=result, error='')
            except Cancelled:
                with self.lock:
                    job.update(status='interrupted' if self.stopping else 'cancelled', error='')
            except Exception as exc:
                with self.lock:
                    job.update(status='interrupted' if self.stopping else 'cancelled' if self.cancel.is_set() else 'failed', error=str(exc))
            finally:
                with self.lock:
                    self.current = None
                    self.notify(job)

    def close(self):
        with self.lock:
            self.stopping = True
            self.cancel.set()
            for job in self.jobs:
                if job['status'] in ACTIVE:
                    job['status'] = 'interrupted'
            self.save()
            self.wake.set()
        self.thread.join(timeout=25)
