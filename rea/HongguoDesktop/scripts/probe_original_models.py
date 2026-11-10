"""Bounded live replay of inspected installer code objects, not module imports.

Only the packaged official host and a newly started loopback signer are allowed.
No licensing, payment, registration, captured-session refresh, or config writes.
"""
from __future__ import annotations

from collections import Counter
import contextlib
from datetime import datetime, timezone
import dis
import hashlib
import importlib.util
import json
import marshal
import os
from pathlib import Path
import platform
import random
import sys
import threading
import time
import types
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT.parent / 'analysis/extracted/app'
OUT = ROOT / 'docs/evidence/original-bytecode-model.json'
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / '.runtime/site-packages')]
os.environ['HG_DATA_DIR'] = str(ROOT / 'docs/evidence/original-bytecode-runtime')
import requests
from curl_cffi import requests as curl_requests
from hongguo_signer import LocalSigner

HOST = 'api5-normal-sinfonlinec.fqnovel.com'
MODEL_PATH = '/novel/player/multi_video_model/v1/'
DETAIL_PATH = '/novel/player/multi_video_detail/v1/'
VID = '7689903116275174462'
SID = '7689863296106646590'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_module(name):
    path = ORIGINAL / (name + '.pyc')
    raw = path.read_bytes()
    assert raw[:4] == importlib.util.MAGIC_NUMBER, 'Requires matching Python 3.11 bytecode runtime'
    code = marshal.loads(raw[16:])
    return code, {'file': str(path), 'sha256': sha(raw)}


def walk(code):
    yield code
    for item in code.co_consts:
        if isinstance(item, types.CodeType):
            yield from walk(item)


def literal_assignments(code, names):
    found = {}
    last = None
    for instruction in dis.get_instructions(code):
        if instruction.opname == 'LOAD_CONST':
            last = instruction.argval
        if instruction.opname == 'STORE_NAME' and instruction.argval in names:
            found[instruction.argval] = last
    return found


def original_defaults(module, function):
    instructions = [i for i in dis.get_instructions(module) if i.opname != 'EXTENDED_ARG']
    for index, instruction in enumerate(instructions):
        if instruction.opname == 'LOAD_CONST' and instruction.argval is function:
            maker = instructions[index + 1]
            if maker.opname == 'MAKE_FUNCTION' and maker.arg & 1:
                prior = instructions[index - 1]
                assert prior.opname == 'LOAD_CONST' and isinstance(prior.argval, tuple)
                return prior.argval
    return None


def main():
    hg, hg_id = read_module('hongguo')
    sg, sg_id = read_module('safeguards')
    dp, dp_id = read_module('devicepool')
    hc = {c.co_qualname: c for c in walk(hg)}
    sc = {c.co_qualname: c for c in walk(sg)}
    dc = {c.co_qualname: c for c in walk(dp)}
    cfg_path = ROOT / 'config/config.json'
    devices_path = ROOT / 'config/devices.json'
    config = json.loads(cfg_path.read_text(encoding='utf-8-sig'))
    devices = json.loads(devices_path.read_text(encoding='utf-8-sig'))
    assert config['api_host'] == HOST
    report = {
        'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
        'mode': 'controlled replay of original code objects with live official API; not full original Windows app',
        'environment': {'python': sys.version.split()[0], 'platform': platform.platform(),
                        'curl_cffi': __import__('curl_cffi').__version__, 'impersonate': 'chrome'},
        'artifacts': [hg_id, sg_id, dp_id],
        'config_sha256': sha(cfg_path.read_bytes()),
        'devices_sha256': sha(devices_path.read_bytes()),
        'config_matches_packaged_original': cfg_path.read_bytes() == (ORIGINAL / 'config.json').read_bytes(),
        'devices_match_packaged_original': devices_path.read_bytes() == (ORIGINAL / 'devices.json').read_bytes(),
        'device_count': len(devices),
        'network_scope': {'official_host': HOST, 'allowed_paths': [MODEL_PATH, DETAIL_PATH],
                          'redirects': 'disabled by probe guard', 'external_request_limit': 4},
        'substitutes_and_boundaries': [
            'No original module top-level execution, Windows GUI, licensing/payment or updater.',
            'Original DevicePool methods; deterministic _pin set to selected existing device indices instead of random startup choice.',
            'Original sign(), _sign_post_once(), _sign_auth_headers(), _sign_session(); one local bundled JAR server. Semaphore/health/statistics use single-thread probe state.',
            'Original _ext_session()/http_request(); preseeded curl_cffi Session subclass adds host/path limits, disables redirects, records response metadata.',
            'Original safeguards.check_response; original cache functions disabled (force=True) with no Redis; throttle replaced by fixed 0.25s delay for serialized requests.',
            'Background retester/source-status/UI priority hooks only record calls; no background network.',
            'refresh_session replaced by a raising boundary hook to prohibit config mutation; occurrence is counted. rotate_device remains original.',
            'TLS/curl/Python/OS runtime differs from packaged Windows environment. Existing device pool tested only at indices 0 and 34.',
        ],
        'cases': [], 'function_coverage': [], 'hook_calls': {},
    }
    counts = Counter()
    hooks = Counter()
    known_codes = {}
    active = {}

    def record_hook(name, result=None):
        def call(*args, **kwargs):
            hooks[name] += 1
            return result
        return call

    def forbidden_refresh():
        hooks['refresh_session'] += 1
        raise RuntimeError('Probe boundary reached: refresh_session suppressed; no config mutation')

    sg_globals = literal_assignments(sg, {'GONE_CODES', 'GONE_KEYWORDS', 'AUTH_CODES',
                                         'AUTH_KEYWORDS', 'RISK_CODES', 'RISK_KEYWORDS'})
    for name, value in list(sg_globals.items()):
        if isinstance(value, int):
            sg_globals[name] = {value}
    for name in ('RiskControlError', 'AuthExpiredError', 'ContentUnavailableError'):
        sg_globals[name] = type(name, (Exception,), {})
    check = types.FunctionType(sc['check_response'], sg_globals)
    known_codes[check.__code__] = 'safeguards.check_response'
    safeguards = types.SimpleNamespace(
        check_response=check, throttle=types.SimpleNamespace(wait=lambda: time.sleep(0.25)),
        cache_get=record_hook('cache_get'), cache_set=record_hook('cache_set'),
        cache_key=lambda *args: tuple(args))
    pool_globals = {'random': random, 'threading': threading}
    methods = {}
    for name in ('__init__', '_advance', 'current', 'rotate', '__len__'):
        code = dc['DevicePool.' + name]
        methods[name] = types.FunctionType(code, pool_globals)
        known_codes[code] = 'devicepool.DevicePool.' + name
    Pool = type('DevicePool', (), methods)
    pool = Pool(devices, True)
    pool._pin = devices[0]

    class ExternalSession(curl_requests.Session):
        def request(self, method, url, **kwargs):
            parsed = urlsplit(url)
            assert parsed.scheme == 'https' and parsed.hostname == HOST
            assert parsed.path in (MODEL_PATH, DETAIL_PATH)
            hooks['external_request'] += 1
            assert hooks['external_request'] <= 4, 'Probe request budget exhausted'
            kwargs['allow_redirects'] = False
            body = kwargs.get('data') or b''
            headers = {k.lower(): str(v) for k, v in kwargs.get('headers', {}).items()}
            query = parse_qs(parsed.query)
            request_record = {
                'method': method, 'base_url': f'https://{HOST}', 'path': parsed.path,
                'query_keys': sorted(query),
                'application_identity': {key: query.get(key) for key in ('aid', 'app_name', 'version_code', 'version_name')},
                'device_identity_sha256': sha(json.dumps({k: query.get(k) for k in ('device_id', 'iid', 'cdid')}, sort_keys=True).encode()),
                'body_bytes': len(body), 'body_sha256': sha(body),
                'stub_matches_body': headers.get('x-ss-stub') == hashlib.md5(body).hexdigest().upper(),
                'signature_lengths': {key: len(headers.get(key, '')) for key in ('x-argus', 'x-gorgon', 'x-khronos', 'x-ladon')},
                'has_cookie': bool(headers.get('cookie')), 'has_x_tt_token': bool(headers.get('x-tt-token')),
            }
            active.setdefault('requests', []).append(request_record)
            start = time.monotonic()
            response = super().request(method, url, **kwargs)
            payload = response.json()
            request_record.update({
                'http_status': response.status_code, 'seconds': round(time.monotonic() - start, 3),
                'response_sha256': sha(response.content),
                'response_headers': {k: response.headers.get(k) for k in ('date', 'server', 'content-type', 'x-tt-logid')},
            })
            if parsed.path == MODEL_PATH:
                # Error bodies have no addresses/credentials; successful model URLs are deliberately not persisted.
                if not payload.get('data'):
                    request_record['response'] = payload
                else:
                    request_record['response_summary'] = {'code': payload.get('code'), 'model_count': len(payload['data'])}
            else:
                video_data = ((payload.get('data') or {}).get(SID) or {}).get('video_data') or {}
                request_record['response_summary'] = {
                    'code': payload.get('code'), 'episode_count': video_data.get('episode_cnt'),
                    'returned_episodes': len(video_data.get('video_list') or []),
                }
            return response

    with LocalSigner(ROOT / 'vendor') as signer:
        class SignSession(requests.Session):
            def request(self, method, url, **kwargs):
                assert url == signer.url + '/sign' and method.upper() == 'POST'
                kwargs['allow_redirects'] = False
                hooks['local_sign_request'] += 1
                return super().request(method, url, **kwargs)

        proxy_requests = types.SimpleNamespace(Session=SignSession, adapters=requests.adapters, utils=requests.utils,
                                               exceptions=requests.exceptions, RequestException=requests.RequestException)
        tls = threading.local()
        tls.ext = ExternalSession()
        warm = {}
        gl = {
            '__name__': 'controlled_original_hongguo', 'CFG': config, '_pool': pool,
            'time': time, 'json': json, 'hashlib': hashlib, '_tls': tls, 'HOST': HOST,
            'SG': safeguards, 'requests': proxy_requests, '_HAS_CFFI': True,
            'IMPERSONATE': 'chrome', 'HONGGUO_PROXY': None, '_cffi': curl_requests,
            'SIGN_SERVERS': [signer.url], '_src': {'down': False, 'reason': '', 'host_b': False},
            'os': types.SimpleNamespace(environ={'HG_SIGN_TOKEN': signer.token}),
            '_sign_permit': lambda _: contextlib.nullcontext(),
            '_next_sign_server': lambda: signer.url, '_sign_is_warm': lambda base: warm.get(base, False),
            '_sign_mark': lambda base, ok: warm.update({base: ok}), '_signer_cold_until': [0],
            '_SIGN_COLD_TIMEOUT': 45, '_SIGN_CONN_WINDOW': 45,
            '_sign_window': record_hook('sign_window'), '_sign_mark_cold': record_hook('sign_mark_cold'),
            '_sign_mark_fail': record_hook('sign_mark_fail'), 'signer_reachable': record_hook('signer_reachable', True),
            '_ensure_retester': record_hook('ensure_retester'), '_source_good': record_hook('source_good'),
            '_source_down': record_hook('source_down'), '_source_strike': record_hook('source_strike'),
            '_prio_enter': record_hook('prio_enter'), '_prio_leave': record_hook('prio_leave'),
            'refresh_session': forbidden_refresh, '_STRIKE_PATHS': {MODEL_PATH, DETAIL_PATH},
            '_risk_reply': lambda _: False, 'scrub_urls': lambda _: '<error redacted>',
            'is_cert_error': lambda _: False, '_conn_failure': lambda _: False,
            'API_HOST_B': HOST, 'NT': types.SimpleNamespace(cert_hint=lambda _: '<redacted>'),
        }
        gl.update({name: sg_globals[name] for name in ('RiskControlError', 'AuthExpiredError', 'ContentUnavailableError')})
        gl.update(literal_assignments(hg, {'IMAGE_SHRINK'}))
        selected = ('build_url', '_req_headers', '_api_once', 'api', 'get_video_tracks',
                    'rotate_device', 'sign', '_sign_post_once', '_sign_auth_headers',
                    '_sign_session', '_reset_sign_session', '_signer_warm',
                    '_ext_session', 'http_request', '_episodes_body')
        for name in selected:
            code = hc[name]
            gl[name] = types.FunctionType(code, gl, name, original_defaults(hg, code))
            known_codes[code] = 'hongguo.' + name

        def trace(frame, event, arg):
            if event == 'call' and frame.f_code in known_codes:
                counts[known_codes[frame.f_code]] += 1

        try:
            for index, kind in ((0, 'detail_control'), (0, 'video_model'), (34, 'video_model')):
                pool._pin = devices[index]
                active = {'device_index': index, 'kind': kind}
                report['cases'].append(active)
                before = Counter(counts)
                sys.setprofile(trace)
                try:
                    if kind == 'detail_control':
                        result = gl['api']('POST', DETAIL_PATH, body=gl['_episodes_body'](SID))
                        active['returned_data_keys'] = len(result.get('data') or {})
                    else:
                        result = gl['get_video_tracks']([VID], True, 1)
                        active['returned_track_map'] = {} if not result else {'video_count': len(result)}
                        active['usable_tracks'] = sum(len(v) for v in result.values())
                    active['exception'] = None
                except Exception as exc:
                    active['exception'] = {'type': type(exc).__name__, 'message': 'redacted; inspect local replay for runtime dependency'}
                    raise
                finally:
                    sys.setprofile(None)
                    active['original_function_calls'] = dict(counts - before)
        finally:
            sys.setprofile(None)
            tls.ext.close()
            if getattr(tls, 'sign', None):
                tls.sign.close()
            report['hook_calls'] = dict(hooks)
            report['refresh_called'] = hooks['refresh_session'] > 0
            report['rotate_called'] = counts['hongguo.rotate_device'] > 0
            for code, name in known_codes.items():
                report['function_coverage'].append({'function': name, 'original_line': code.co_firstlineno,
                    'code_sha256': sha(marshal.dumps(code)), 'call_count': counts[name]})
            report['verdict'] = {
                'detail_control_succeeded': any(c['kind'] == 'detail_control' and c.get('requests', [{}])[0].get('response_summary', {}).get('returned_episodes') == 74 for c in report['cases']),
                'usable_model_cases': sum(c.get('usable_tracks', 0) > 0 for c in report['cases']),
                'tested_model_cases': sum(c['kind'] == 'video_model' for c in report['cases']),
                'not_proven': ['all original versions/devices/networks fail', 'exact Windows executable runtime result',
                               'server outage', 'device registration is root cause'],
            }
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        signer.mark_success()
    print(json.dumps({'evidence': str(OUT), 'verdict': report['verdict'],
                      'refresh_called': report['refresh_called'], 'rotate_called': report['rotate_called']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
