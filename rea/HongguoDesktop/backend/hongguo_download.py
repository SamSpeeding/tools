"""Selected-episode downloads with integrity checks and local media decryption."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parent
QUALITIES = ('1080p', '720p', '540p', '480p', '360p')
DECRYPT_MODULES = ('extract_keybox_pairs', 'oracle', 'decutil', 'unwrap_spade')


def parse_episodes(text, available):
    available = set(available)
    text = text.strip().lower().replace('，', ',').replace(' ', '')
    if not text:
        return []
    if text in ('all', '全部', '*'):
        return sorted(available)
    selected = set()
    for part in text.split(','):
        match = re.fullmatch(r'([0-9]+)(?:-([0-9]+))?', part)
        if not match:
            raise ValueError('集号格式：1、1,3,5、2-6 或 all')
        start, end = int(match[1]), int(match[2] or match[1])
        if start < 1 or end < start or not available or end > max(available):
            raise ValueError(f'无效集号范围：{part}')
        numbers = set(range(start, end + 1))
        missing = numbers - available
        if missing:
            raise ValueError('详情中没有这些集：' + ','.join(map(str, sorted(missing))))
        selected.update(numbers)
    return sorted(selected)


def safe_name(value):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(value)).strip(' .')[:60] or 'drama'


def atomic_json(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(path)


def digest_file(path, algorithm='sha256'):
    digest = hashlib.new(algorithm)
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def media_executable(name):
    path = shutil.which(name)
    if path:
        return path
    for directory in ('/opt/homebrew/bin', '/usr/local/bin'):
        path = Path(directory) / name
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise RuntimeError(f'缺少 {name}，请安装 FFmpeg。')


def preflight(vendor):
    vendor = Path(vendor)
    try:
        from Crypto.Cipher import AES  # noqa: F401
    except ImportError:
        raise RuntimeError('缺少 PyCryptodome，请安装 requirements.txt 中的依赖。') from None
    media_executable('ffmpeg')
    media_executable('ffprobe')
    manifest = {item['path']: item['sha256']
                for item in json.loads((vendor / 'manifest.json').read_text())}
    for name in DECRYPT_MODULES:
        relative = f'decrypt/{name}.py'
        source = vendor / relative
        if not source.is_file():
            raise RuntimeError('缺少解密源码：' + relative)
        if relative not in manifest or digest_file(source) != manifest[relative]:
            raise RuntimeError('解密源码校验失败：' + relative)


def load_decrypt_modules(vendor):
    """Load recovered source only; retained original .pyc files are references."""
    directory = (Path(vendor) / 'decrypt').resolve()
    for name in DECRYPT_MODULES:
        if not (directory / f'{name}.py').is_file():
            raise RuntimeError(f'缺少解密源码：{name}.py；不会回退到原 .pyc。')
        loaded = sys.modules.get(name)
        if loaded is not None and Path(loaded.__file__).resolve() != directory / f'{name}.py':
            raise RuntimeError(f'已加载其他版本的 {name}，请重新启动程序。')
    previous_path = sys.path[:]
    sys.path.insert(0, str(directory))
    try:
        importlib.invalidate_caches()
        modules = {name: importlib.import_module(name) for name in DECRYPT_MODULES}
        for name, module in modules.items():
            if Path(module.__file__).resolve() != directory / f'{name}.py':
                raise RuntimeError(f'解密模块未从指定源码加载：{name}')
        return modules
    finally:
        # Recovered modules may also insert this path during their own imports.
        sys.path[:] = previous_path


def choose_track(model, quality):
    tracks = [t for t in model.get('tracks', []) if t.get('main_url') or t.get('backup_url')]
    for t in tracks:
        if (t.get('video_meta') or {}).get('definition', t.get('definition')) == quality:
            return t
    raise RuntimeError(f'此集没有 {quality} 地址，请用 --quality 选择其他清晰度。')


def integrity(track):
    meta = track.get('video_meta') or {}
    size = int(meta.get('size') or track.get('size') or 0)
    digest = str(meta.get('file_hash') or '').lower()
    if size <= 0 or not re.fullmatch(r'(?:[0-9a-f]{32}|[0-9a-f]{64})', digest):
        raise RuntimeError('视频模型缺少有效的文件大小或校验值，不能确认下载完整性。')
    return size, digest, 'md5' if len(digest) == 32 else 'sha256'


def fetch_track(session, track, destination, timeout):
    size, expected, algorithm = integrity(track)
    urls = list(dict.fromkeys(u for u in (track.get('main_url'), track.get('backup_url')) if u))
    error = '视频没有可用地址'
    for url in urls:
        if urlsplit(url).scheme not in ('https', 'http'):
            continue
        try:
            with session.get(url, stream=True, timeout=(min(timeout, 20), timeout)) as response:
                if response.status_code != 200:
                    error = f'CDN 返回 HTTP {response.status_code}'
                    continue
                received, last_percent = 0, -1
                digest = hashlib.new(algorithm)
                with destination.open('wb') as output:
                    for chunk in response.iter_content(256 * 1024):
                        received += len(chunk)
                        if received > size:
                            raise RuntimeError('下载大小超过模型值')
                        digest.update(chunk)
                        output.write(chunk)
                        percent = received * 100 // size
                        if percent >= last_percent + 10 or percent == 100:
                            print(f'\r  下载 {percent:3d}%  {received/1048576:.1f}/{size/1048576:.1f} MiB', end='', flush=True)
                            last_percent = percent
                print()
                if received != size or digest.hexdigest() != expected:
                    error = '下载文件大小或哈希校验失败'
                    continue
                return
        except requests.RequestException:
            error = '视频下载连接失败或超时'
        except RuntimeError as exc:
            error = str(exc)
    raise RuntimeError(error)


def command(args, timeout=600, check_cancel=lambda: None):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + timeout
        while True:
            check_cancel()
            if time.monotonic() > deadline:
                raise RuntimeError('媒体处理超时')
            try:
                stdout, stderr = process.communicate(timeout=0.3)
                break
            except subprocess.TimeoutExpired:
                pass
    except BaseException:
        process.kill()
        process.communicate()
        raise
    if process.returncode:
        raise RuntimeError(f'{Path(args[0]).name} 处理失败：{stderr[-700:].strip()}')
    return stdout


def playable_file(source, track, target, vendor, check_cancel=lambda: None, stage=lambda value: None):
    check_cancel()
    stage('decrypting')
    encrypted = (track.get('encrypt_info') or {}).get('encrypt')
    stats = None
    if encrypted:
        info = track['encrypt_info']
        if info.get('encryption_method') != 'cenc-aes-ctr' or not info.get('spade_a'):
            raise RuntimeError('该视频的加密格式尚不支持。')
        modules = load_decrypt_modules(vendor)
        unwrap, oracle, decutil = (modules[name] for name in ('unwrap_spade', 'oracle', 'decutil'))
        key = unwrap.spade_to_key(info['spade_a'], 0)
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{32}', key):
            key = unwrap.spade_to_key(info['spade_a'], 1)
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{32}', key):
            raise RuntimeError('无法解析此集的解密参数。')
        matched_key, iv = oracle.verify_key_iv(str(source), [key], decutil.senc_iv8(str(source)))
        if not matched_key or not iv:
            raise RuntimeError('视频文件与解密参数不匹配。')
        raw = source.parent / 'decrypted.raw.mp4'
        stats = decutil.decrypt_av(str(source), matched_key, str(raw))
        check_cancel()
        video = stats.get('vide')
        if not video or video[0] != video[1] or video[1] <= 0:
            raise RuntimeError('视频样本解密校验失败。')
        # Strip encryption boxes before remux; the audited fallback is codec-
        # specific, so keep other codecs out of this route.
        codec = (track.get('video_meta') or {}).get('codec_type')
        if codec not in ('bytevc1', 'hevc', 'h265'):
            raise RuntimeError(f'当前解密封装仅验证了 HEVC，此集编码为 {codec}。')
        stripped = source.parent / 'decrypted.clear.mp4'
        if not decutil.strip_cenc(str(raw), str(stripped)):
            raise RuntimeError('清理 MP4 加密标记失败。')
        command([media_executable('ffmpeg'), '-hide_banner', '-nostdin', '-v', 'error', '-n',
                 '-i', str(stripped), '-c', 'copy', '-tag:v', 'hvc1', '-movflags', '+faststart', str(target)], check_cancel=check_cancel)
    else:
        shutil.copyfile(source, target)
    print('  校验整集音视频…', flush=True)
    check_cancel()
    stage('verifying')
    probe = json.loads(command([media_executable('ffprobe'), '-v', 'error', '-show_entries',
        'stream=codec_type,codec_name,width,height,nb_frames:format=duration,size', '-of', 'json', str(target)], check_cancel=check_cancel))
    streams = probe.get('streams', [])
    if not any(s.get('codec_type') == 'video' for s in streams):
        raise RuntimeError('成品中没有有效视频轨。')
    if float(probe.get('format', {}).get('duration', 0)) <= 0:
        raise RuntimeError('成品时长无效。')
    command([media_executable('ffmpeg'), '-hide_banner', '-nostdin', '-v', 'error', '-xerror',
             '-i', str(target), '-map', '0:v:0', '-map', '0:a?', '-f', 'null', '-'], check_cancel=check_cancel)
    return {'encrypted_source': bool(encrypted), 'sample_validation': stats,
            'full_decode_validated': True, 'media': probe}


def completed_file(path, vid, quality):
    report_path = path.with_suffix('.json')
    if not path.exists():
        return False
    try:
        report = json.loads(report_path.read_text())
        return (report.get('vid') == vid and report.get('quality') == quality
                and report.get('full_decode_validated') is True
                and report.get('sha256') == digest_file(path))
    except (OSError, ValueError):
        return False


def download_selected(api, detail, selected, directory, quality='1080p', timeout=60, vendor=None):
    vendor = Path(vendor or ROOT/'vendor').resolve()
    preflight(vendor)
    sid = str(detail['series_id'])
    title = detail['meta'].get('title') or sid
    folder = Path(directory).resolve() / f'{safe_name(title)}_{safe_name(sid)}'
    folder.mkdir(parents=True, exist_ok=True)
    by_index = {e['index']: e for e in detail['episodes'] if e.get('index') is not None}
    report = {'series_id': sid, 'title': title, 'selected': selected, 'quality': quality,
              'episodes': [], 'status': 'in_progress'}
    report_path = folder / '下载记录.json'
    # Retain prior records when another run selects different episodes.
    if report_path.exists():
        previous = json.loads(report_path.read_text())
        report['episodes'] = [r for r in previous.get('episodes', [])
                              if r.get('index') not in selected or r.get('quality') != quality]
    failures = 0
    with requests.Session() as session:
        try:
            for number, index in enumerate(selected, 1):
                episode = by_index[index]
                vid = str(episode['vid'])
                result = {'index': index, 'vid': vid, 'quality': quality, 'status': 'downloading'}
                report['episodes'].append(result)
                atomic_json(report_path, report)
                final = folder / f'第{index:03d}集_{quality}.mp4'
                print(f'\n[{number}/{len(selected)}] {title} 第{index}集 · {quality}', flush=True)
                try:
                    if completed_file(final, vid, quality):
                        result.update(status='complete', file=str(final), skipped=True)
                        print('  已存在且校验通过，跳过下载。')
                        continue
                    if final.exists():
                        raise RuntimeError('目标文件已存在但缺少匹配校验记录；请先改名或移走，避免覆盖。')
                    with tempfile.TemporaryDirectory(prefix=f'.episode-{index}-', dir=folder) as temp:
                        source = Path(temp)/'source.enc.mp4'
                        # A retry always obtains a new model, keeping URL, hash
                        # and encryption information from the same response.
                        for attempt in range(2):
                            models = api.models([vid])
                            model = models.get('models', {}).get(vid)
                            if not model:
                                raise RuntimeError('没有取得此集视频模型，请检查网络或签名器。')
                            track = choose_track(model, quality)
                            try:
                                fetch_track(session, track, source, timeout)
                                break
                            except RuntimeError:
                                if attempt:
                                    raise
                                print('  下载失败，刷新本集地址后重试一次…', flush=True)
                                time.sleep(0.5)
                        candidate = Path(temp)/'playable.mp4'
                        print('  解密并整理 MP4 封装…', flush=True)
                        verification = playable_file(source, track, candidate, vendor)
                        verification.update(vid=vid, index=index, quality=quality, series_id=sid,
                                            bytes=candidate.stat().st_size, sha256=digest_file(candidate))
                        # Atomic publication without overwriting any existing file.
                        os.link(candidate, final)
                        atomic_json(final.with_suffix('.json'), verification)
                    result.update(status='complete', file=str(final))
                    print('  完成：' + str(final), flush=True)
                except Exception as exc:
                    failures += 1
                    result.update(status='failed', error=str(exc))
                    print('  失败：' + str(exc), file=sys.stderr, flush=True)
                finally:
                    atomic_json(report_path, report)
        except KeyboardInterrupt:
            if report['episodes'] and report['episodes'][-1]['status'] == 'downloading':
                report['episodes'][-1]['status'] = 'interrupted'
            report['status'] = 'interrupted'
            atomic_json(report_path, report)
            raise
    report['status'] = 'partial' if failures else 'complete'
    atomic_json(report_path, report)
    print(f'\n本次 {len(selected)-failures}/{len(selected)} 集完成；目录：{folder}')
    return 2 if failures else 0
