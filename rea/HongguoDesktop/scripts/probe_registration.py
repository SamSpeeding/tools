"""Bounded registration experiment, separate from application configuration.

Three candidate payloads only. No activation, login, or payment requests.
All TLS certificates are verified. Issued identities stay in a private report.
"""
from pathlib import Path
import hashlib
import json
import os
import secrets
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / '.runtime/site-packages')]
from curl_cffi import requests

URL = 'https://i.snssdk.com/service/2/device_register/'
PUBLIC = ROOT / 'docs/evidence/registration-probe.json'
PRIVATE = ROOT / 'docs/evidence/registration-runtime'
PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
config = json.loads((ROOT / 'config/config.json').read_text(encoding='utf-8-sig'))
query = config['base_query']
hardware = {'openudid': secrets.token_hex(8), 'device_model': query['device_type']}
cdid = str(uuid.uuid4())
variants = [
    ('reference_package_minimal', {'header': {'package': 'com.dragon.read', **hardware}}),
    ('target_package_minimal', {'header': {'package': 'com.phoenix.read.oversea.gp', **hardware}}),
    ('target_app_metadata_candidate', {'header': {
        'package': 'com.phoenix.read.oversea.gp', **hardware, 'cdid': cdid,
        'aid': int(query['aid']), 'app_name': query['app_name'],
        'app_version': query['version_name'], 'version_code': int(query['version_code']),
        'update_version_code': int(query['update_version_code']),
        'channel': query['channel'], 'os': query['os'], 'os_version': query['os_version'],
        'os_api': int(query['os_api']), 'device_brand': query['device_brand'],
        'resolution': query['resolution'], 'density_dpi': int(query['dpi']),
        'language': query['language'],
    }, 'magic_tag': 'ss_app_log'}),
]
report = {'endpoint': URL, 'certificate_verification': True,
          'scope': 'payload candidates, not a verified aid=8662 registration protocol',
          'unchanged_configuration': True, 'attempts': []}
with requests.Session(impersonate='chrome') as client:
    for label, payload in variants:
        body = json.dumps(payload, separators=(',', ':')).encode()
        item = {'name': label, 'package': payload['header']['package'],
                'declared_aid': payload['header'].get('aid'),
                'body_sha256': hashlib.sha256(body).hexdigest()}
        start = time.monotonic()
        try:
            # PHP's unconfigured POSTFIELDS string uses this MIME type.
            r = client.post(URL, data=body,
                            headers={'content-type': 'application/x-www-form-urlencoded'},
                            timeout=20, allow_redirects=False, verify=True)
            item.update(http_status=r.status_code, response_bytes=len(r.content),
                        content_type=r.headers.get('content-type'),
                        log_id=r.headers.get('x-tt-logid'))
            try:
                response = r.json()
            except ValueError:
                response = None
            if isinstance(response, dict):
                item['response_keys'] = sorted(response)
                item['error_fields'] = {k: response[k] for k in ['code', 'Code', 'message', 'Message', 'error', 'status_code'] if k in response}
                device = str(response.get('device_id_str') or response.get('device_id') or '0')
                install = str(response.get('install_id_str') or response.get('install_id') or '0')
                item['device_id_nonzero'] = device.isdigit() and int(device) > 0
                item['install_id_nonzero'] = install.isdigit() and int(install) > 0
                item['paired_identity_received'] = item['device_id_nonzero'] and item['install_id_nonzero']
                path = PRIVATE / (label + '.json')
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'w') as f:
                    json.dump({'request': payload, 'response': response}, f, ensure_ascii=False, indent=2)
            else:
                item['paired_identity_received'] = False
                item['response_sha256'] = hashlib.sha256(r.content).hexdigest()
        except Exception as exc:
            item['error'] = str(exc)
            item['paired_identity_received'] = False
        item['seconds'] = round(time.monotonic() - start, 2)
        report['attempts'].append(item)
        PUBLIC.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(item, ensure_ascii=False), flush=True)
