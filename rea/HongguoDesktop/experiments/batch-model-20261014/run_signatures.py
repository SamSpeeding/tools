from lab import *

lab = Lab('02-signature-crossover')
with LocalSigner(ROOT/'vendor') as signer:
    api = lab.api(signer)
    try:
        for profile in ('script', 'ours'):
            for order, families in [('jar_first', ('jar', 'python')), ('python_first', ('python', 'jar'))]:
                ids = identity(profile+'_'+order)
                for family in families:
                    label = profile+'_'+order+'_'+family
                    lab.case(label, lambda p=profile, i=ids, f=family: lab.sign_and_send(lab.template(p, i, api), f, api))
    finally:
        api.close()
    signer.mark_success()
lab.save()
