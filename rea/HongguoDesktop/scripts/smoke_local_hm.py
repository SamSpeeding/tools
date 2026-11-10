"""Exercise the newly built .app's own worker/runtime, with fresh test state."""
import argparse
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)  # No cached model/file success.
DATA = args.output.resolve()
BUNDLE = ROOT/'release/HongguoDesktop.app/Contents/Resources'
sys.path[:0] = [str(BUNDLE/'backend'), str(BUNDLE/'runtime/site-packages')]
import requests
from hongguo_download import media_executable

messages, events, report = queue.Queue(), [], {'bundle': str(BUNDLE), 'checks': {}}
log = (DATA/'worker.log').open('w')
worker = subprocess.Popen([str(BUNDLE/'runtime/python/bin/python3.11'), '-B',
    str(BUNDLE/'backend/worker.py'),str(DATA/'state')], cwd=DATA,
    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True)
threading.Thread(target=lambda: [messages.put(json.loads(line)) for line in worker.stdout], daemon=True).start()
sequence = 0


def record(name, value):
    report['checks'][name] = value
    print(name, json.dumps(value,ensure_ascii=False),flush=True)
    (DATA/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


def request(method, params=None):
    global sequence
    sequence += 1
    worker.stdin.write(json.dumps({'id':sequence,'method':method,'params':params or {}})+'\n')
    worker.stdin.flush()
    deadline = time.monotonic()+120
    while time.monotonic()<deadline:
        msg = messages.get(timeout=30)
        if msg.get('event'):
            events.append(msg)
            continue
        assert msg.get('id') == sequence
        if msg.get('error'):
            raise RuntimeError(msg['error'])
        return msg['result']
    raise TimeoutError(method)


try:
    results = request('search',{'query':'重生'})
    assert results['items']
    record('search',{'items':len(results['items'])})
    detail = request('detail',{'series_id':'7689863296106646590'})
    assert detail['complete']
    record('detail',{'episodes':len(detail['episodes'])})
    initial = request('playback_open',{'series_id':detail['series_id'],'index':2,
                                      'quality':'1080p','request_id':'hm-bundle-smoke'})
    deadline = time.monotonic()+90
    state = None
    while time.monotonic()<deadline:
        for event in reversed(events):
            candidate = event.get('playback') or {}
            if candidate.get('id') == initial['id'] and candidate.get('status') in {'ready','failed'}:
                state = candidate
                break
        if state:
            break
        events.append(messages.get(timeout=30))
    assert state and state['status']=='ready', state
    assert state['model_api']=='multi_video_model' and not state['model_fallback']
    assert state['initial_bytes']<state['total']
    record('playback', {k:state[k] for k in ['model_api','model_fallback','initial_bytes','total']})
    first = requests.get(state['url'],headers={'Range':'bytes=0-65535'},timeout=30)
    middle = requests.get(state['url'],headers={'Range':'bytes=1048593-1114101'},timeout=30)
    full = requests.get(state['url'],timeout=60)
    assert first.status_code==middle.status_code==206 and full.status_code==200
    assert first.content==full.content[:65536] and middle.content==full.content[1048593:1114102]
    media = DATA/'streamed.mp4'
    media.write_bytes(full.content)
    decoded = subprocess.run([media_executable('ffmpeg'),'-v','error','-xerror','-i',str(media),
        '-map','0:v:0','-map','0:a?','-f','null','-'],capture_output=True,text=True,timeout=90)
    assert decoded.returncode==0, decoded.stderr
    record('stream',{'range_matches':True,'full_decode_validated':True,
                     'bytes':len(full.content),'sha256':hashlib.sha256(full.content).hexdigest()})
    request('playback_close',{'id':state['id']})
    assert requests.get(state['url'],timeout=5).status_code==404
    request('settings',{'directory':str(DATA/'downloads')})
    job = request('enqueue',{'series_id':detail['series_id'],'index':2,'quality':'1080p'})
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        current = next(j for j in request('state')['jobs'] if j['id']==job['id'])
        if current['status'] in {'completed','failed','cancelled'}:
            break
        time.sleep(.5)
    assert current['status']=='completed', current
    assert current['model_api']=='multi_video_model' and not current['model_fallback']
    validation=json.loads(Path(current['file']).with_suffix('.json').read_text())
    assert validation['full_decode_validated']
    record('download',{'model_api':current['model_api'],'full_decode_validated':True,
                       'bytes':validation['bytes'],'sha256':validation['sha256']})
    record('result','passed')
finally:
    if worker.poll() is None:
        worker.stdin.write('{"method":"shutdown"}\n')
        worker.stdin.flush()
        try:
            worker.wait(timeout=35)
        except subprocess.TimeoutExpired:
            worker.kill(); worker.wait()
    log.close()
