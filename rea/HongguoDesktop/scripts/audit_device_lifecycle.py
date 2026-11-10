"""Offline audit of original bytecode with synthetic inputs and fake I/O.

Does not import/execute module top levels, contact a server, or modify analysis.
Runs only inspected refresh_session/check_response functions in supplied globals.
"""
import contextlib
import dis
import hashlib
import io
import json
import marshal
from pathlib import Path
import tempfile
import threading
import types
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT.parent / 'analysis/extracted/app'
OUT = ROOT / 'docs/evidence'


def load(name):
    path = ORIGINAL / (name + '.pyc')
    raw = path.read_bytes()
    return marshal.loads(raw[16:]), {'file': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def functions(code):
    yield code
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from functions(const)


pool, pool_identity = load('devicepool')
hg, hg_identity = load('hongguo')
sg, sg_identity = load('safeguards')
hg_functions = {c.co_name: c for c in functions(hg)}
sg_functions = {c.co_name: c for c in functions(sg)}
report = {'mode': 'offline controlled replay; no network',
          'artifacts': [pool_identity, hg_identity, sg_identity]}
report['devicepool_imports'] = sorted({i.argval for c in functions(pool) for i in dis.get_instructions(c) if i.opname == 'IMPORT_NAME'})

# Read constants assigned to the six response-classification globals directly
# from original bytecode, without executing module initialization (Redis, etc.).
constants = {}
last_const = None
for instruction in dis.get_instructions(sg):
    if instruction.opname == 'LOAD_CONST':
        last_const = instruction.argval
    if instruction.opname == 'STORE_NAME' and instruction.argval in {
        'GONE_CODES', 'GONE_KEYWORDS', 'AUTH_CODES', 'AUTH_KEYWORDS', 'RISK_CODES', 'RISK_KEYWORDS'
    }:
        constants[instruction.argval] = {last_const} if isinstance(last_const, int) else last_const
for name in ['AuthExpiredError', 'RiskControlError', 'ContentUnavailableError']:
    constants[name] = type(name, (Exception,), {})
check = types.FunctionType(sg_functions['check_response'], constants)
cases = {
    'current_capital_Code': {'Code': 110001, 'Message': '未知异常', 'BaseResp': {'StatusMessage': 'unknown error', 'StatusCode': 110001}},
    'lowercase_same_code': {'code': 110001, 'message': '未知异常'},
    'explicit_auth_expired': {'code': 401, 'message': 'session expired'},
}
report['original_response_classification'] = {}
for name, response in cases.items():
    try:
        check(response)
        result = 'no exception'
    except Exception as exc:
        result = type(exc).__name__
    report['original_response_classification'][name] = result
assert report['original_response_classification'] == {
    'current_capital_Code': 'no exception',
    'lowercase_same_code': 'RiskControlError',
    'explicit_auth_expired': 'AuthExpiredError',
}

calls = []
fresh_query = {'device_id': 'synthetic-new-device', 'iid': 'synthetic-new-install',
               'cdid': 'synthetic-new-cdid', 'version_name': 'synthetic-new-version',
               'channel': 'synthetic-channel', 'klink_egdi': 'synthetic-klink',
               'not_in_original_keys': 'ignored'}
fake_response = {'url': 'https://example.invalid/?' + urlencode(fresh_query),
                 'headers': {'Cookie': 'synthetic-cookie', 'X-Tt-Token': 'synthetic-token',
                             'X-Tt-Store-Region': 'synthetic-region',
                             'User-Agent': 'ignored-UA'}}


class FakeSession:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def get(self, url, **kwargs):
        calls.append({'url': url, 'timeout': kwargs.get('timeout')})
        return types.SimpleNamespace(json=lambda: fake_response)


with tempfile.TemporaryDirectory() as temporary:
    cfg = {'base_query': {k: 'old' for k in ['device_id', 'iid', 'cdid', 'version_name']},
           'session_headers': {'user-agent': 'original-UA'}}
    globals_map = {'_refresh_lock': threading.Lock(), '_last_refresh': 0,
                   'time': types.SimpleNamespace(time=lambda: 1000),
                   'SIGN_SERVERS': ['http://127.0.0.1:1'],
                   '_sign_sem_for': lambda _: contextlib.nullcontext(),
                   'requests': types.SimpleNamespace(Session=FakeSession),
                   '_sign_auth_headers': lambda: {}, 'CFG': cfg, 'json': json,
                   'os': __import__('os'), 'HERE': temporary}
    refresh = types.FunctionType(hg_functions['refresh_session'], globals_map)
    with contextlib.redirect_stdout(io.StringIO()):
        refresh()
        refresh()  # Same clock: the 20-second guard must suppress the second call.
    saved = json.loads((Path(temporary) / 'config.json').read_text())
    report['original_refresh_replay'] = {
        'fake_grab_calls': len(calls),
        'updated_query_fields': sorted(k for k, v in saved['base_query'].items() if v != 'old'),
        'unknown_query_ignored': 'not_in_original_keys' not in saved['base_query'],
        'copied_session_header_names': sorted(k for k in saved['session_headers'] if k != 'user-agent'),
        'user_agent_unchanged': saved['session_headers']['user-agent'] == 'original-UA',
        'written_only_to_temporary_config': True,
    }
    assert len(calls) == 1
    assert all(saved['base_query'][k] == fresh_query[k] for k in ['device_id', 'iid', 'cdid', 'version_name', 'channel', 'klink_egdi'])
    assert report['original_refresh_replay']['unknown_query_ignored']

# Preserve fresh disassembly beside the new app's evidence, not in frozen analysis.
buffer = io.StringIO()
for code in [pool, sg_functions['check_response'], hg_functions['refresh_session']]:
    print(f'FUNCTION {code.co_name} ORIGINAL_LINE {code.co_firstlineno}', file=buffer)
    dis.dis(code, file=buffer)
(OUT / 'device-lifecycle-bytecode.txt').write_text(buffer.getvalue())
(OUT / 'device-lifecycle-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
