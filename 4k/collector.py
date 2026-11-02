#!/usr/bin/env python3
"""Append-only movie/series catalog. Existing IDs are never remotely refreshed."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import logging
import os
import re
from pathlib import Path
import sys
from urllib.parse import urlencode, urlsplit, urlunsplit

from catalog_io import Client, FetchError, archive_lock, atomic_write, image_format, read_json, safe_image_path, write_json
from catalog_parser import SITE, cover_filename, parse_post, parse_resources

BUCKETS = {'movie': ('movies.json', 1), 'series': ('series.json', 3)}
LOG = logging.getLogger('4k')


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def api_url(**params):
    return SITE + '/wp-json/wp/v2/posts?' + urlencode(params)


def load_catalogs(root):
    catalogs = {}
    for kind, (filename, _) in BUCKETS.items():
        rows = read_json(root / filename, [])
        if not isinstance(rows, list):
            raise ValueError(f'{filename} 顶层必须是数组；未修改原文件。')
        ids = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('id'), int) or isinstance(row['id'], bool):
                raise ValueError(f'{filename} 包含无效站内 ID；未修改原文件。')
            if row['id'] in ids:
                raise ValueError(f'{filename} 存在重复 ID {row["id"]}；未修改原文件。')
            ids.add(row['id'])
        catalogs[kind] = {row['id']: row for row in rows}
    return catalogs


def sort_key(row):
    return row.get('source_modified_at') or row.get('published_at') or '', row['id']


def save_catalog(root, kind, catalog):
    write_json(root / BUCKETS[kind][0], sorted(catalog.values(), key=sort_key, reverse=True))


def inventory(client, workers=3):
    # Only ID/category pairs are scanned. No existing record's body, timestamp or detail page is requested.
    params = dict(categories='1,3', per_page=100, orderby='id', order='desc', _fields='id,categories')
    first, headers = client.json(api_url(**params, page=1))
    if not isinstance(first, list):
        raise FetchError('目录接口返回格式异常')
    total_pages = int(headers.get('x-wp-totalpages', '1'))
    expected = int(headers.get('x-wp-total', str(len(first))))
    records = {p['id']: p.get('categories', []) for p in first}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(client.json, api_url(**params, page=p)): p for p in range(2, total_pages + 1)}
        completed = 1
        for future in as_completed(futures):
            rows, _ = future.result()
            if not isinstance(rows, list):
                raise FetchError('目录分页格式异常')
            records.update((p['id'], p.get('categories', [])) for p in rows)
            completed += 1
            if completed % 5 == 0 or completed == total_pages:
                LOG.info('ID 目录 %d/%d 页，已发现 %d 个条目', completed, total_pages, len(records))
    if len(records) != expected:
        raise FetchError(f'目录分页期间数量发生变化（预期 {expected}，得到 {len(records)}）；请重跑，已有文件未改变。')
    return records


def new_targets(catalogs, remote):
    targets = {}
    for ident, categories in remote.items():
        kinds = [kind for kind, (_, cat) in BUCKETS.items() if cat in categories and ident not in catalogs[kind]]
        if kinds:
            targets[ident] = kinds
    return targets


def collect_one(client, post, kinds):
    page, _ = client.get(post['link'])
    resources, extras = parse_resources(page.decode('utf-8', errors='replace'), post['id'])
    body_resources, body_extras = parse_resources('<article class="post-content">' + post.get('content', {}).get('rendered', '') + '</article>')
    identities = {m['identity'] for m in resources}
    for resource in body_resources:
        if resource['identity'] not in identities:
            resources.append(resource)
            identities.add(resource['identity'])
    extra_urls = {item['url'] for item in extras}
    extras.extend(item for item in body_extras if item['url'] not in extra_urls)
    stamp = now()
    rows = []
    for kind in kinds:
        row = parse_post(post, kind)
        row['magnet_links'] = resources
        row['extra_links'] = extras
        row['sync'] = {'status': 'collected', 'first_seen_at': stamp,
                       'last_seen_at': stamp, 'last_fetched_at': stamp, 'remote_missing_since': None}
        if not resources:
            row['source_notes'].append('本次公开详情页未提取到磁力链接；此条目保存后不会自动更新。')
        invalid_count = sum(not m.get('url_valid', True) for m in resources)
        if invalid_count:
            row['source_notes'].append(f'来源网页有 {invalid_count} 条磁力地址格式异常，已按原文保留，并标记 url_valid=false。')
        rows.append(row)
    return rows


def sync(root, client, workers=3, limit=None):
    catalogs = load_catalogs(root)
    remote = inventory(client, workers)
    targets = new_targets(catalogs, remote)
    original_target_count = len(targets)
    ids = sorted(targets, reverse=True)
    if limit is not None:
        ids = ids[:limit]
    LOG.info('本地电影 %d、剧集 %d；远端不同 ID %d；待新增 ID %d，本次处理 %d',
             len(catalogs['movie']), len(catalogs['series']), len(remote), original_target_count, len(ids))
    failures, completed, since_save = [], 0, 0
    added = dict.fromkeys(BUCKETS, 0)
    dirty = set()
    def checkpoint():
        for kind in tuple(dirty):
            save_catalog(root, kind, catalogs[kind])
            dirty.remove(kind)
    try:
        for start in range(0, len(ids), 100):
            batch = ids[start:start + 100]
            try:
                posts, _ = client.json(api_url(include=','.join(map(str, batch)), per_page=100,
                                               orderby='id', order='desc', _embed='wp:featuredmedia,wp:term'))
                if not isinstance(posts, list):
                    raise FetchError('正文 API 返回格式异常')
            except Exception as exc:
                for ident in batch:
                    failures.append({'id': ident, 'stage': 'api', 'error': str(exc)})
                LOG.error('正文批次失败：%s', exc)
                continue
            found = {p['id'] for p in posts}
            for ident in set(batch) - found:
                failures.append({'id': ident, 'stage': 'api', 'error': '目录有此 ID，正文接口未返回'})
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(collect_one, client, p, targets[p['id']]): p['id']
                           for p in posts if p['id'] in targets}
                for future in as_completed(futures):
                    ident = futures[future]
                    try:
                        for row in future.result():
                            kind = row['type']
                            if ident not in catalogs[kind]:
                                catalogs[kind][ident] = row
                                added[kind] += 1
                                dirty.add(kind)
                    except Exception as exc:
                        failures.append({'id': ident, 'stage': 'detail', 'error': str(exc)})
                        LOG.error('条目 %d 失败：%s', ident, exc)
                    completed += 1
                    since_save += 1
                    if since_save >= 10:
                        checkpoint()
                        since_save = 0
                        LOG.info('详情进度 %d/%d；新增电影 %d、剧集 %d；失败 %d',
                                 completed, len(ids), added['movie'], added['series'], len(failures))
    finally:
        checkpoint()
        # These are reports, never a source of records. Deleting a catalog always starts that bucket anew.
        for kind in BUCKETS:
            if not (root / BUCKETS[kind][0]).exists():
                save_catalog(root, kind, catalogs[kind])
        report = {'finished_at': now(), 'mode': 'append_only', 'remote_ids': len(remote),
                  'new_ids_at_start': original_target_count, 'processed_limit': limit,
                  'added': added, 'counts': {k: len(v) for k, v in catalogs.items()},
                  'http_requests': client.requests, 'failures': failures}
        write_json(root / '.state' / 'last-sync.json', report)
    LOG.info('资料保存完成：电影 %d、剧集 %d；本次新增 %d；失败 %d',
             len(catalogs['movie']), len(catalogs['series']), sum(added.values()), len(failures))
    return report


def reusable_image(root, relative):
    if not relative:
        return None
    try:
        path = safe_image_path(root, relative)
        if path.is_file() and image_format(path.read_bytes()):
            return relative
    except (ValueError, OSError):
        pass
    return None


def download_image(client, url):
    parts = urlsplit(url)
    current = url
    if parts.hostname in ('4kbt.net', 'www.4kbt.net'):
        current = urlunsplit(('https', '4kbt.org', parts.path, parts.query, ''))
    candidates = [current]
    current_parts = urlsplit(current)
    if current_parts.hostname == '4kbt.org':
        flat = re.sub(r'^/wp-content/uploads/20\d{2}/\d{2}/', '/wp-content/uploads/', current_parts.path)
        if flat != current_parts.path:
            candidates.append(urlunsplit((current_parts.scheme, current_parts.netloc, flat, current_parts.query, '')))
    last = None
    for candidate in candidates:
        try:
            data, _ = client.get(candidate)
            fmt = image_format(data)
            if not fmt:
                raise FetchError('下载结果不是完整的受支持图片，未保存为封面')
            return data, fmt, candidate
        except FetchError as exc:
            last = exc
    raise last


def covers(root, client, workers=3, limit=None):
    catalogs = load_catalogs(root)
    index_path = root / '.state' / 'images.json'
    image_index = read_json(index_path, {})
    if not isinstance(image_index, dict):
        raise ValueError('图片索引格式异常，未执行下载')
    urls = {}
    for kind, records in catalogs.items():
        for row in records.values():
            cover = row.get('cover', {})
            if cover.get('source_url'):
                urls.setdefault(cover['source_url'], []).append((kind, row))
    downloaded, skipped, dirty, failures = 0, 0, set(), []
    missing = []

    def mark(url, relative, fmt):
        source = safe_image_path(root, relative)
        for kind, row in urls[url]:
            cover = row['cover']
            own_relative = cover_filename(kind, row['id'], row['name'], url, fmt)
            # Reuse a downloaded image under an identifiable name for every catalog entry.
            own_path = safe_image_path(root, own_relative)
            if own_path != source and not reusable_image(root, own_relative):
                own_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(source, own_path)
                except OSError:
                    atomic_write(own_path, source.read_bytes())
            patch = {'local_path': own_relative, 'downloaded': True, 'format': fmt,
                     'download_url': image_index.get(url, {}).get('download_url', url)}
            if any(cover.get(k) != v for k, v in patch.items()):
                cover.update(patch)
                dirty.add(kind)

    def checkpoint():
        write_json(index_path, image_index)
        for kind in tuple(dirty):
            save_catalog(root, kind, catalogs[kind])
            dirty.remove(kind)

    for url, entries in urls.items():
        relative = reusable_image(root, image_index.get(url, {}).get('local_path'))
        if not relative:
            for _, row in entries:
                relative = reusable_image(root, row['cover'].get('local_path'))
                if relative:
                    break
        if not relative:
            # If catalogs were deleted, recover downloaded files by the stable URL hash in their names.
            digest = hashlib.sha256(url.encode()).hexdigest()[:12]
            for candidate in (root / 'img').glob('*_' + digest + '.*'):
                relative = reusable_image(root, str(candidate.relative_to(root)))
                if relative:
                    break
        if relative:
            data = safe_image_path(root, relative).read_bytes()
            fmt = image_format(data)
            resolved = image_index.get(url, {}).get('download_url') or next((r['cover'].get('download_url') for _,r in entries if r['cover'].get('download_url')), url)
            image_index[url] = {'local_path': relative, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'download_url': resolved}
            mark(url, relative, fmt)
            skipped += 1
        else:
            missing.append(url)
    if limit is not None:
        missing = missing[:limit]
    LOG.info('封面不同地址 %d；本地可复用 %d；本次待下载 %d', len(urls), skipped, len(missing))
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # Bound batches so a Ctrl-C doesn't wait for thousands of queued requests.
            for offset in range(0, len(missing), 30):
                futures = {pool.submit(download_image, client, url): url for url in missing[offset:offset + 30]}
                for future in as_completed(futures):
                    url = futures[future]
                    try:
                        data, fmt, resolved = future.result()
                        kind, row = urls[url][0]
                        relative = cover_filename(kind, row['id'], row['name'], url, fmt)
                        path = safe_image_path(root, relative)
                        atomic_write(path, data)
                        image_index[url] = {'local_path': relative, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'download_url': resolved}
                        mark(url, relative, fmt)
                        downloaded += 1
                    except Exception as exc:
                        failures.append({'url': url, 'error': str(exc)})
                        LOG.error('封面失败（条目 %s）：%s', [r['id'] for _, r in urls[url]], exc)
                    if (downloaded + len(failures)) % 20 == 0:
                        checkpoint()
                        LOG.info('封面进度 %d/%d；已下载 %d；失败 %d', downloaded + len(failures), len(missing), downloaded, len(failures))
    finally:
        checkpoint()
        report = {'finished_at': now(), 'unique_urls': len(urls), 'downloaded': downloaded,
                  'skipped': skipped, 'http_requests': client.requests, 'failures': failures}
        write_json(root / '.state' / 'last-covers.json', report)
    LOG.info('封面完成：新下载 %d、跳过 %d、失败 %d', downloaded, skipped, len(failures))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='4KBT 电影/剧集目录：只新增已有 JSON 中不存在的站内 ID。')
    parser.add_argument('action', choices=['sync', 'covers'])
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--workers', type=int, default=3, choices=range(1, 7), metavar='1-6')
    parser.add_argument('--interval', type=float, default=0.2, help='所有请求之间的最小间隔秒数，默认 0.2')
    parser.add_argument('--limit', type=int, help='只处理指定数量的新 ID 或待下载封面，用于验证')
    args = parser.parse_args(argv)
    if args.interval < 0 or (args.limit is not None and args.limit < 0):
        parser.error('interval 和 limit 不能小于 0')
    root = args.output_dir.expanduser().resolve()
    (root / 'logs').mkdir(parents=True, exist_ok=True)
    log_path = root / 'logs' / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + args.action + '.log')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        datefmt='%H:%M:%S', handlers=[logging.StreamHandler(), logging.FileHandler(log_path, encoding='utf-8')])
    LOG.info('输出目录：%s', root)
    try:
        with archive_lock(root):
            client = Client(interval=args.interval)
            report = (sync if args.action == 'sync' else covers)(root, client, args.workers, args.limit)
        return 2 if report['failures'] else 0
    except KeyboardInterrupt:
        LOG.warning('已中断；已写入 JSON 的记录会保留，下次继续补齐缺失 ID。')
        return 130
    except Exception as exc:
        LOG.error('%s', exc)
        return 1
    finally:
        LOG.info('日志：%s', log_path)


if __name__ == '__main__':
    sys.exit(main())
