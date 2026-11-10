"""Live test of the Tauri worker's playback commands and local media endpoint."""
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'.runtime/site-packages'))
sys.path.insert(0, str(ROOT/'backend'))
import requests
from hongguo_download import media_executable

DATA = ROOT/'docs/evidence/playback-smoke-runtime'
DATA.mkdir(parents=True, exist_ok=True)
messages = queue.Queue()
log = (DATA/'worker.log').open('w')
worker = subprocess.Popen([str(ROOT/'.runtime/python/bin/python3.11'), '-B',
    str(ROOT/'backend/worker.py'), str(DATA)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    stderr=log, text=True)
threading.Thread(target=lambda:[messages.put(json.loads(line)) for line in worker.stdout], daemon=True).start()
sequence, events, report = 0, [], {}


def record(name, value):
    report[name] = value
    (ROOT/'docs/evidence/playback-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(name, json.dumps(value, ensure_ascii=False), flush=True)


def request(method, params=None):
    global sequence
    sequence += 1
    worker.stdin.write(json.dumps({'id':sequence,'method':method,'params':params or {}})+'\n')
    worker.stdin.flush()
    while True:
        msg = messages.get(timeout=90)
        if msg.get('event'):
            events.append(msg)
            continue
        assert msg.get('id') == sequence, msg
        if msg.get('error'):
            raise RuntimeError(msg['error'])
        return msg['result']


def ready(session_id):
    deadline = time.monotonic()+90
    while time.monotonic()<deadline:
        for event in reversed(events):
            state = event.get('playback') or {}
            if state.get('id') == session_id and state.get('status') in ('ready','failed'):
                assert state['status'] == 'ready', state
                return state
        events.append(messages.get(timeout=90))
    raise RuntimeError('playback timeout')


try:
    detail = request('detail', {'series_id':'7689863296106646590'})
    assert detail['complete']
    before = time.monotonic()
    initial = request('playback_open', {'series_id':detail['series_id'],'index':2,'quality':'1080p','request_id':'smoke'})
    state = ready(initial['id'])
    record('ready', {k:v for k,v in state.items() if k not in ('url','id')})
    record('startup_seconds', round(time.monotonic()-before, 3))
    assert state['initial_bytes'] < state['total'], 'playback downloaded entire file before ready'
    head = requests.head(state['url'], timeout=30)
    assert head.status_code == 200
    first = requests.get(state['url'], headers={'Range':'bytes=0-65535'}, timeout=30)
    middle = requests.get(state['url'], headers={'Range':'bytes=1048593-1114101'}, timeout=30)
    assert first.status_code == middle.status_code == 206
    full = requests.get(state['url'], timeout=60)
    assert full.status_code == 200 and len(full.content) == state['total']
    assert first.content == full.content[:65536] and middle.content == full.content[1048593:1114102]
    path = DATA/'streamed.mp4'
    path.write_bytes(full.content)
    process = subprocess.run([media_executable('ffmpeg'),'-v','error','-xerror','-i',str(path),
        '-map','0:v:0','-map','0:a?','-f','null','-'], capture_output=True,text=True,timeout=90)
    assert process.returncode == 0, process.stderr
    record('media', {'full_decode_validated':True,'bytes':len(full.content),
                    'sha256':hashlib.sha256(full.content).hexdigest(),'seek_matches':True})
    request('playback_close', {'id':state['id']})
    assert requests.get(state['url'],timeout=5).status_code == 404
    record('close', 'old playback URL no longer served')
    record('download_jobs_created',len(request('state')['jobs']))
    assert not request('state')['jobs']
    record('result','passed')
except Exception as exc:
    record('result',{'error':str(exc)[:1500]})
    raise
finally:
    worker.stdin.write('{"method":"shutdown"}\n')
    worker.stdin.flush()
    try:
        worker.wait(timeout=35)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait()
    log.close()
