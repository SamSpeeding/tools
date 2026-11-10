"""Isolated diagnostic harness. Never writes application config or downloads media."""
from copy import deepcopy
from datetime import datetime
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import time
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIVATE = HERE/'private'
PRIVATE.mkdir(mode=0o700, exist_ok=True)
os.environ['HG_DATA_DIR'] = str(PRIVATE)
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'.runtime/site-packages')]
import requests
from hongguo_api import HongguoAPI, MODEL_PATH, SINGLE_MODEL_PATH
from hongguo_signer import LocalSigner

SCRIPT = Path('/Users/tt/Downloads/红果短剧.py')
spec = importlib.util.spec_from_file_location('studied_script', SCRIPT)
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
plugin._HG_CACHE_DIR = str(PRIVATE/'unused-media-cache')
VID = '7689903116275174462'
HOSTS = {'api5-normal-sinfonlineb.fqnovel.com', 'api5-normal-sinfonlinec.fqnovel.com'}
BIZ = {'detail_page_version': 0, 'device_level': 3, 'disable_digg_stat': False,
       'disable_video_relate_book': False, 'need_all_video_definition': True,
       'need_mp4_align': False, 'use_os_player': False, 'use_server_dns': False,
       'video_platform': 1024}
ORIGINAL = json.loads((ROOT/'config/devices.json').read_text(encoding='utf-8-sig'))[0]

def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()

def write_private(name, value):
    path = PRIVATE/name
    with os.fdopen(os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600), 'w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)

def identity(label, digits=18):
    path = PRIVATE/'identities.json'
    ids = json.loads(path.read_text()) if path.exists() else {}
    if label not in ids:
        ids[label] = {k: str(10**(digits-1) + secrets.randbelow(9*10**(digits-1)))
                      for k in ('device_id', 'install_id')}
        write_private('identities.json', ids)
    return deepcopy(ids[label])

def protected_hashes():
    paths = list((ROOT/'backend').glob('*.py')) + list((ROOT/'src').glob('*'))
    paths += [ROOT/'config/config.json', ROOT/'config/devices.json', SCRIPT]
    paths += list((ROOT/'vendor/decrypt').glob('*.py'))
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}

def model_summary(response):
    data = response.get('data') or {}
    entry = data.get(VID, data) if isinstance(data, dict) else {}
    model = entry.get('video_model') if isinstance(entry, dict) else None
    if isinstance(model, str):
        try: model = json.loads(model)
        except ValueError: model = None
    tracks = model.get('video_list', {}) if isinstance(model, dict) else {}
    tracks = list(tracks.values()) if isinstance(tracks, dict) else tracks
    usable = []
    for track in tracks or []:
        if not isinstance(track, dict): continue
        url = track.get('main_url') or ''
        if not url.startswith(('http://', 'https://')):
            try: url = base64.b64decode(url).decode()
            except Exception: url = ''
        if url.startswith(('http://', 'https://')):
            usable.append(track.get('definition') or (track.get('video_meta') or {}).get('definition'))
    return {'usable': bool(usable), 'definitions': usable,
            'code': response.get('code', response.get('Code')),
            'message': response.get('message', response.get('Message', response.get('msg')))}

class Lab:
    def __init__(self, phase):
        self.phase = phase
        self.results = []
        self.label = None
        self.count = 0
        self.before = protected_hashes()
        self.path = HERE/(phase+'.json')
        if self.path.exists(): raise RuntimeError('Choose a new phase: '+phase)

    def save(self):
        after = protected_hashes()
        assert self.before == after, 'Production/source files changed during experiment'
        self.path.write_text(json.dumps({'phase': self.phase, 'updated_at': now(), 'vid': VID,
            'scope': 'Only model requests, no media fetch, registration or production writes',
            'production_and_script_unchanged': True, 'source_hashes': self.before,
            'results': self.results}, ensure_ascii=False, indent=2)+'\n')

    def send(self, method, url, headers, data, transport='requests', session=None, **unused):
        parts = urlsplit(url)
        assert method.upper() == 'POST' and parts.scheme == 'https'
        assert parts.hostname in HOSTS and parts.path in {MODEL_PATH, SINGLE_MODEL_PATH}
        assert self.label and self.count < 40
        self.count += 1
        data = data if isinstance(data, bytes) else data.encode()
        query = dict(parse_qsl(parts.query))
        headers = {k.lower(): str(v) for k,v in headers.items()}
        expected = hashlib.md5(data).hexdigest().upper()
        assert headers.get('x-ss-stub', '').upper() == expected, 'Body stub mismatch'
        started = time.monotonic()
        client = session or requests
        response = client.request(method, url, headers=headers, data=data, timeout=25, allow_redirects=False)
        raw = response.json()
        row = {'label': self.label, 'time': now(), 'host': parts.hostname, 'path': parts.path,
               'transport': transport, 'http_status': response.status_code,
               'version': query.get('version_name'),
               'device_sha256': hashlib.sha256(query.get('device_id', '').encode()).hexdigest(),
               'iid_sha256': hashlib.sha256(query.get('iid', '').encode()).hexdigest(),
               'body_md5': expected, 'sign_headers': {k:len(v) for k,v in headers.items() if k in
                   {'x-gorgon','x-argus','x-ladon','x-khronos','x-helios','x-medusa','x-neptune','x-soter'}},
               'seconds': round(time.monotonic()-started, 3), **model_summary(raw)}
        wire_headers = dict(response.request.headers) if getattr(response, 'request', None) else headers
        write_private(self.phase+'-'+self.label+'.json', {'request': {'method': method, 'url': url,
            'headers': headers, 'wire_headers': wire_headers, 'body': data.decode()},
            'response_headers': dict(response.headers), 'response': raw})
        self.results.append(row)
        self.save()
        print(json.dumps(row, ensure_ascii=False), flush=True)
        return response

    def case(self, label, fn):
        self.label = label
        time.sleep(2.5)
        try:
            fn()
        except Exception as exc:
            if not self.results or self.results[-1]['label'] != label:
                self.results.append({'label': label, 'time': now(), 'error': type(exc).__name__+': '+str(exc)[:300]})
            else:
                self.results[-1]['parse_error'] = type(exc).__name__+': '+str(exc)[:300]
            self.save()
        finally:
            self.label = None

    def plugin_native(self, ids):
        original = plugin.requests
        plugin.requests = SimpleNamespace(post=lambda url, **kw: self.send('POST', url, **kw))
        try:
            return plugin._video_model(VID, ids)
        finally:
            plugin.requests = original

    def api(self, signer):
        lab = self
        class ProbeAPI(HongguoAPI):
            def _json_request(self, stage, method, url, headers, data, request_body=None):
                if stage == 'signer':
                    return super()._json_request(stage, method, url, headers, data, request_body)
                return lab.send(method, url, headers, data, 'curl_chrome', self.api_session).json()
        return ProbeAPI(ROOT/'config/config.json', signer.url, signer.token, device=deepcopy(ORIGINAL), timeout=25)

    def template(self, profile, ids, api):
        """Reuse the original builders, then compare signing over exact same bytes."""
        if profile == 'script':
            captured = {}
            class Captured(Exception): pass
            original = plugin._core_sixgod
            def capture(url, params, devices, data, header):
                captured.update(url=url, params=params, devices=devices, body=data, headers=header)
                raise Captured()
            plugin._core_sixgod = capture
            try:
                plugin._video_model(VID, ids)
            except Captured:
                pass
            finally:
                plugin._core_sixgod = original
            url, query = plugin._get_params_encrypturl(captured['url'], captured['params'], captured['devices'])
            headers = {k.lower():v for k,v in captured['headers'].items()}
            headers['x-tt-dt'] = captured['devices']['x_tt_dt']
            body = json.dumps(captured['body'], ensure_ascii=False, separators=(',', ':')).encode()
            return {'url': url, 'query': query, 'headers': headers, 'body': body,
                    'devices': captured['devices']}
        assert profile == 'ours'
        api.device = deepcopy(ORIGINAL)
        api.device['query'].update(device_id=ids['device_id'], iid=ids['install_id'])
        url = api.build_url(MODEL_PATH)
        query = dict(parse_qsl(urlsplit(url).query))
        body = json.dumps({'biz_param': BIZ, 'mixed_video_id_map': {'1': [VID]}},
                          ensure_ascii=False, separators=(',', ':')).encode()
        headers = api._req_headers(body)
        devices = {'device_id': query['device_id'], 'install_id': query['iid'], 'iid': query['iid'],
                   'version_name': query['version_name'], 'device_brand': query['device_brand'],
                   'device_model': query['device_type'], 'device_type': query['device_type'],
                   'device_manufacturer': query['device_brand'], 'os_version': query['os_version'],
                   'ua': headers['user-agent']}
        return {'url': url, 'query': query, 'headers': headers, 'body': body, 'devices': devices}

    def signed_headers(self, template, family, api):
        url, body = template['url'], template['body']
        headers = dict(template['headers'])
        headers['x-ss-stub'] = hashlib.md5(body).hexdigest().upper()
        if family == 'jar':
            payload = {'url': url, 'headers': headers}
            signed = api._json_request('signer', 'POST', api.signer_url+'/sign',
                {'content-type': 'application/json', 'X-Sign-Token': api.signer_token},
                json.dumps(payload, ensure_ascii=False).encode(), payload)
            assert 'error' not in signed
            headers.update({k.lower():str(v) for k,v in signed.items()})
        else:
            assert family == 'python'
            original = plugin._get_params_encrypturl
            plugin._get_params_encrypturl = lambda *_: (url, template['query'])
            try:
                signed, signed_url = plugin._core_sixgod(url, template['query'],
                    template['devices'], body, headers)
                assert signed_url == url
            finally:
                plugin._get_params_encrypturl = original
            names = {'x-gorgon','x-argus','x-ladon','x-khronos','x-helios','x-medusa','x-ss-stub'}
            headers.update({k:v for k,v in signed.items() if k in names})
        headers.pop('accept-encoding', None)
        return headers

    def sign_and_send(self, template, family, api, transport='requests'):
        headers = self.signed_headers(template, family, api)
        session = api.api_session if transport == 'curl_chrome' else None
        return self.send('POST', template['url'], headers, template['body'], transport, session)

    def hybrid_send(self, template, base, replacements, api, drop=()):
        for _ in range(4):
            jar = self.signed_headers(template, 'jar', api)
            python = self.signed_headers(template, 'python', api)
            if jar['x-khronos'] == python['x-khronos']:
                break
        else:
            raise RuntimeError('Could not align signature timestamps; request not sent')
        sources = {'jar': jar, 'python': python}
        headers = dict(sources[base])
        other = sources['python' if base == 'jar' else 'jar']
        for key in replacements:
            headers[key] = other[key]
        assert {k for k in headers if headers[k] != sources[base].get(k)} <= set(replacements)
        for key in drop:
            headers.pop(key, None)
        write_private(self.phase+'-'+self.label+'-signature-parts.json', sources)
        return self.send('POST', template['url'], headers, template['body'])

