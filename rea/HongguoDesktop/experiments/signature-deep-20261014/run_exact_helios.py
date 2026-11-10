"""One-variable comparison: identical URL/body/nonce/time/all other headers."""
from deep_lab import *
sys.path.insert(0,str(HERE/'decoder'))
from decode import decode_helios,encode_helios

lab=DeepLab('09-exact-helios-counterfactual')
catalog=json.loads((HERE/'episode-catalog.json').read_text())
vids=[ep['vid'] for ep in catalog['A']['episodes'][:3]]+[catalog['B']['episodes'][0]['vid'],catalog['B']['episodes'][-1]['vid']]
with LocalSigner(ROOT/'vendor') as signer:
    api=lab.api(signer)
    try:
        template=lab.model_template(vids,api)
        for _ in range(4):
            jar=lab.signed_headers(template,'jar',api)
            py=lab.signed_headers(template,'python',api)
            if jar['x-khronos']==py['x-khronos']:break
        else:raise RuntimeError('Local signature timestamps did not align')
        original={**jar,'x-helios':py['x-helios'],'x-medusa':py['x-medusa']}
        decoded=decode_helios(py['x-helios'])
        nonce=base64.b64decode(py['x-helios'])[:4]
        unchanged={k:v for k,v in original.items() if k!='x-helios'}
        invariant=hashlib.sha256(json.dumps({'url':template['url'],'body':template['body'].decode(),
            'headers_except_helios':unchanged},sort_keys=True).encode()).hexdigest()
        write_private(lab.phase+'-signature-parts.json',{'jar':jar,'python':py})
        variants=[('license_only_first','1611921764','8662'),
                  ('original_valid','1588093228','8662'),
                  ('app_id_only','1588093228','3019'),
                  ('jar_license_and_app','1611921764','3019'),
                  ('original_valid_replay','1588093228','8662')]
        for label,license_id,app_id in variants:
            value=f"{decoded['khronos']}-{license_id}-{app_id}".encode()
            headers={**original,'x-helios':encode_helios(value,nonce)}
            assert {k:v for k,v in headers.items() if k!='x-helios'}==unchanged
            parsed=decode_helios(headers['x-helios'])
            assert parsed['license_id']==license_id and parsed['app_id']==app_id
            lab.signing='hybrid_fixed_everything_except_helios_plaintext'
            lab.case(label,lambda headers=headers:lab.send('POST',template['url'],headers,template['body']))
            lab.results[-1]['counterfactual']={'unchanged_request_except_helios_sha256':invariant,
                'same_random_nonce_and_khronos':True,'helios_license_id':license_id,'helios_app_id':app_id,
                'helios_roundtrip':parsed['roundtrip']}
            lab.save()
    finally:
        api.close()
    signer.mark_success()
lab.save()
