"""Read immutable captures, save private decoded bodies and public binding checks."""
from collections import Counter
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
import decode as d

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASELINE = ROOT.parent / 'batch-model-20261014'

def bindings(values, request, headers):
    query = urlsplit(request['url']).query
    params = dict(parse_qsl(query))
    body = request['body'].encode()
    time = int(headers['x-khronos'])
    query_sm3 = d.plugin.SM3(query).digest()
    body_md5 = hashlib.md5(body).digest()
    device = values['env']['device']
    return {
        'medusa_ms_app_id_equals_url_aid':values['ms_app_id'] == params['aid'],
        'medusa_device_id_equals_url':values['device_id'] == params.get('device_id',params.get('did')),
        'nested_device_id_equals_top':device['device_id'] == values['device_id'],
        'device_app_id_equals_top':device['aid'] == values['ms_app_id'],
        'app_version_equals_url':values['app_version'] == params['version_name'],
        'env_app_version_equals_top':values['env']['app_version'] == values['app_version'],
        'times_equal_khronos':values['time'] == values['time2'] == time,
        'query_sm3_matches':values['query_sm3'] == query_sm3[:6].hex(),
        'query_body_ts_hash_matches':values['query_body_ts_hash'] == d.plugin.hash_f13(query_sm3,body_md5,time.to_bytes(4,'little'),time).hex(),
        'query_body_hash_sm3_matches':values['query_body_hash_sm3'] == d.plugin.SM3(query.encode()+body_md5+b'none').digest().hex(),
        'body_md5_matches_header':body_md5.hex().upper() == headers['x-ss-stub'],
    }

def audit():
    results = []
    paths = sorted((BASELINE/'private').glob('*-signature-parts.json')) + sorted((ROOT/'private').glob('*-signature-parts.json'))
    for path in paths:
        parts = json.loads(path.read_text())
        capture = path.with_name(path.name.replace('-signature-parts.json','.json'))
        if not capture.exists() and path.name == '09-exact-helios-counterfactual-signature-parts.json':
            capture = path.with_name('09-exact-helios-counterfactual-original_valid.json')
        request = json.loads(capture.read_text())['request']
        private = {}
        result = {'capture':str(path.relative_to(ROOT.parent)), 'families':{}}
        for family in ['jar','python']:
            headers = parts[family]
            h = d.decode_helios(headers['x-helios'])
            env = d.medusa_envelope(headers['x-medusa'],int(headers['x-khronos']))
            entry = {'helios_roundtrip':h['roundtrip'], 'helios_app_id_position':h['app_id'],
                     'helios_license_id_position':h['license_id'],
                     'helios_time_matches_header':h['khronos'] == int(headers['x-khronos']),
                     'medusa_envelope':env}
            private[family] = {'helios':h,'envelope':env}
            if env['version'] == 3:
                m = d.decode_medusa(headers['x-medusa'],int(headers['x-khronos']))
                private[family]['medusa'] = m
                v = m['values']
                entry.update({'medusa_roundtrip':m['roundtrip'], 'bindings':bindings(v,request,headers),
                              'protobuf_profile':{key:v[key] for key in ['version','ms_app_id','license_id','app_version','sdk_version_str','sdk_version','psk_version','call_type']},
                              'env_version':v['env']['version'], 'nested_device_id_present':bool(v['env']['device']['device_id'])})
            result['families'][family] = entry
        d.write_private(HERE/'private'/(path.stem+'-decoded.json'),private)
        results.append(result)
    output = {'scope':'Offline parsing only; no HTTP or signer calls. Private decoded identity fields are omitted.',
              'capture_count':len(results), 'header_pair_count':len(results)*2, 'results':results}
    (HERE/'capture-audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    count = Counter()
    for item in results:
        for family,data in item['families'].items():
            count[(family,'helios',data['helios_app_id_position'],data['helios_license_id_position'])] += 1
            count[(family,'medusa',data['medusa_envelope']['version'])] += 1
            for key,value in data.get('bindings',{}).items():
                if not value:
                    print('BINDING MISMATCH',item['capture'],family,key)
    print('Captured pairs',len(results))
    print(json.dumps({str(key):value for key,value in count.items()},indent=2))

def audit_sent_requests():
    results = []
    all_paths = sorted((BASELINE/'private').glob('*.json')) + sorted((ROOT/'private').glob('*.json'))
    phase09_base = json.loads((ROOT/'private/09-exact-helios-counterfactual-original_valid.json').read_text())['request']
    base_helios = d.decode_helios(phase09_base['headers']['x-helios'])
    for path in all_paths:
        capture = json.loads(path.read_text())
        if not isinstance(capture,dict) or not isinstance(capture.get('request'),dict):
            continue
        request = capture['request']
        if 'video_model' not in urlsplit(request['url']).path:
            continue
        headers = {key.lower():value for key,value in request.get('headers',{}).items()}
        if not {'x-helios','x-medusa','x-khronos'} <= headers.keys():
            continue
        wire_headers = {key.lower():value for key,value in request.get('wire_headers',{}).items()}
        h = d.decode_helios(headers['x-helios'])
        env = d.medusa_envelope(headers['x-medusa'],int(headers['x-khronos']))
        response = capture.get('response',{})
        if isinstance(response,str):
            try: response = json.loads(response)
            except ValueError: response = {}
        public = {'capture':str(path.relative_to(ROOT.parent)),
                  'request_url_sha256':hashlib.sha256(request['url'].encode()).hexdigest(),
                  'request_body_sha256':hashlib.sha256(request['body'].encode()).hexdigest(),
                  'helios':{key:h[key] for key in ['roundtrip','app_id','license_id']},
                  'helios_time_matches_header':h['khronos'] == int(headers['x-khronos']),
                  'sent_signatures_match_captured_headers':all(wire_headers.get(key) == headers[key] for key in ['x-helios','x-medusa','x-khronos']),
                  'medusa_envelope':env, 'response_code':response.get('code',response.get('Code'))}
        private = {'helios':h,'medusa_envelope':env}
        if env['version'] == 3:
            m = d.decode_medusa(headers['x-medusa'],int(headers['x-khronos']))
            private['medusa'] = m
            public.update({'medusa_roundtrip':m['roundtrip'],'bindings':bindings(m['values'],request,headers)})
        if path.name.startswith('09-'):
            public['counterfactual_against_original_valid'] = {
                'same_url':request['url'] == phase09_base['url'],
                'same_body':request['body'] == phase09_base['body'],
                'same_other_headers':{k:v for k,v in request['headers'].items() if k != 'x-helios'} == {k:v for k,v in phase09_base['headers'].items() if k != 'x-helios'},
                'same_helios_random':h['random'] == base_helios['random'],
                'same_helios_khronos':h['khronos'] == base_helios['khronos'],
                'same_helios_app_id':h['app_id'] == base_helios['app_id'],
                'same_helios_license_id':h['license_id'] == base_helios['license_id']}
        d.write_private(HERE/'private'/(path.stem+'-sent-decoded.json'),private)
        results.append(public)
    output = {'scope':'Actual transmitted model-request headers, separate from candidate signatures.',
              'source_script_sha256':hashlib.sha256(d.SCRIPT.read_bytes()).hexdigest(),
              'request_count':len(results), 'results':results}
    (HERE/'sent-request-audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print('Actual transmitted model requests audited',len(results))
    print('v3 decoded',sum(x['medusa_envelope']['version']==3 for x in results),'v4 envelopes',sum(x['medusa_envelope']['version']==4 for x in results))
    for item in results:
        for key,value in item.get('bindings',{}).items():
            if not value: print('ACTUAL BINDING MISMATCH',item['capture'],key)
        if not item['sent_signatures_match_captured_headers']:
            print('WIRE HEADER MISMATCH',item['capture'])

if __name__ == '__main__':
    audit()
    audit_sent_requests()
