"""Perturb only Helios plaintext fields in the isolated Python signer."""
import types
from deep_lab import *

lab=DeepLab('08-helios-field-isolation')
catalog=json.loads((HERE/'episode-catalog.json').read_text())
vids=[ep['vid'] for ep in catalog['A']['episodes'][:3]]+[catalog['B']['episodes'][0]['vid'],catalog['B']['episodes'][-1]['vid']]
original=plugin._encrypt_helios
assert original.__code__.co_consts.count('-1588093228-8662')==1

with LocalSigner(ROOT/'vendor') as signer:
    api=lab.api(signer)
    try:
        lab.model('correct_hm_before',vids,api)
        for label,suffix in [('helios_app3019_only','-1588093228-3019'),
                             ('helios_license1611921764_only','-1611921764-8662'),
                             ('helios_jar_app_and_license','-1611921764-3019')]:
            constants=tuple(suffix if c=='-1588093228-8662' else c for c in original.__code__.co_consts)
            plugin._encrypt_helios=types.FunctionType(original.__code__.replace(co_consts=constants),
                original.__globals__,original.__name__,original.__defaults__,original.__closure__)
            try:
                lab.model(label,vids,api)
                lab.results[-1]['controlled_change']={'helios_plaintext_suffix':suffix,
                    'key_derivation_suffix_unchanged':'8662','medusa':'original Python v3'}
                lab.save()
            finally:
                plugin._encrypt_helios=original
        lab.model('correct_hm_after_fields',vids,api)
        lab.signing='jar_with_python_helios_only'
        lab.case('jar_medusa_with_correct_python_helios',lambda:lab.hybrid_send(
            lab.model_template(vids,api),'jar',['x-helios'],api))
        lab.model('correct_hm_final',vids,api)
    finally:
        plugin._encrypt_helios=original
        api.close()
    signer.mark_success()
lab.save()
