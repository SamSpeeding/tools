"""Live integration verification of the same stdio worker used by Tauri."""
from pathlib import Path
import json
import queue
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'docs/evidence/smoke-runtime'
DATA.mkdir(parents=True, exist_ok=True)
results = {}
events = []
messages = queue.Queue()
log = (DATA/'worker.log').open('w')
p = subprocess.Popen([str(ROOT/'.runtime/python/bin/python3.11'), '-B', str(ROOT/'backend/worker.py'), str(DATA)],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
threading.Thread(target=lambda: [messages.put(json.loads(line)) for line in p.stdout], daemon=True).start()
counter = 0

def request(method, params=None):
    global counter
    counter += 1
    p.stdin.write(json.dumps({'id': counter, 'method': method, 'params': params or {}})+'\n')
    p.stdin.flush()
    while True:
        msg = messages.get(timeout=150)
        if msg.get('event'):
            events.append(msg)
            continue
        assert msg.get('id') == counter, msg
        if msg.get('error'):
            raise RuntimeError(msg['error'])
        return msg['result']

def record(name, value):
    results[name] = value
    print(name, json.dumps(value, ensure_ascii=False), flush=True)
    (ROOT/'docs/evidence/worker-smoke.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))

def pages(method, params):
    first = request(method, params)
    assert first['items'], (method, params, first)
    second = request(method, {**params, 'cursor': first['next_cursor']}) if first['has_more'] else {'items': []}
    assert all(isinstance(x['series_id'], str) for x in first['items'])
    return {'first': len(first['items']), 'second': len(second['items']), 'cursor': first['next_cursor'], 'first_id': first['items'][0]['series_id']}

try:
    request('settings', {'directory': str(ROOT/'docs/evidence/downloads')})
    record('search_rebirth', pages('search', {'query': '重生'}))
    for category in ['all', 'human', 'comic', 'ai']:
        for board in ['recommend', 'hot', 'new']:
            r = request('rank', {'category': category, 'board': board})
            assert r['items'], (category, board)
            record(f'rank_{category}_{board}', {'count': len(r['items']), 'more': r['has_more']})
    for genre in ['short_play', 'comic_series', 'ai_series']:
        rows = request('filters', {'genre': genre})['rows']
        record('filters_'+genre, [{'type': r['type'], 'selection_type': r['selection_type'], 'count': len(r['items'])} for r in rows])
        row = next(r for r in rows if r['type'] == 'category_dim_theme' and r['items'])
        record('filtered_'+genre, pages('category', {'genre': genre, 'selections': {row['type']: [row['items'][0]['selector_item_id']]}}))
        record('latest_'+genre, pages('latest', {'genre': genre}))
    detail = request('detail', {'series_id': '7689863296106646590'})
    assert detail['complete'], detail['issues']
    record('detail', {'title': detail['meta']['title'], 'episodes': len(detail['episodes']), 'complete': detail['complete']})
    job = request('enqueue', {'series_id': detail['series_id'], 'index': 2, 'quality': '1080p'})
    duplicate = request('enqueue', {'series_id': detail['series_id'], 'index': 2, 'quality': '1080p'})
    assert duplicate['id'] == job['id']
    if duplicate['status'] in ['failed', 'cancelled', 'interrupted']:
        request('retry', {'id': job['id']})
    record('duplicate', {'single_task': True})
    # Browsing must remain possible while the download proceeds.
    before = time.monotonic()
    concurrent_page = request('rank', {'category': 'human', 'board': 'hot'})
    record('browse_during_download', {'items': len(concurrent_page['items']), 'seconds': round(time.monotonic()-before, 2)})
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        state = request('state')
        current = next(j for j in state['jobs'] if j['id'] == job['id'])
        if current['status'] in ['completed', 'failed', 'cancelled']:
            break
        time.sleep(.4)
    assert current['status'] == 'completed', current
    report = json.loads(Path(current['file']).with_suffix('.json').read_text())
    record('download', {'file': current['file'], 'bytes': report['bytes'], 'sha256': report['sha256'],
                        'full_decode_validated': report['full_decode_validated'], 'media': report['media'],
                        'states': sorted({e['job']['status'] for e in events if 'job' in e})})
    record('result', 'passed')
except Exception as exc:
    record('result', {'status': 'incomplete', 'reason': str(exc)})
    raise
finally:
    p.stdin.write('{"method":"shutdown"}\n'); p.stdin.flush()
    try:
        p.wait(timeout=35)
    except subprocess.TimeoutExpired:
        p.kill(); p.wait()
    log.close()
