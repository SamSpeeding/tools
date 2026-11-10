"""Fast live regression: a known previously downloaded episode must have tracks."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'.runtime/site-packages')]
os.environ['HG_DATA_DIR'] = str(ROOT/'docs/evidence/model-repro-runtime')
from app_api import AppAPI
from hongguo_signer import LocalSigner

start = time.monotonic()
with LocalSigner(ROOT/'vendor') as signer:
    api = AppAPI(ROOT/'config/config.json', signer.url, signer.token,
                 device=json.loads((ROOT/'config/devices.json').read_text(encoding='utf-8-sig'))[0], timeout=25)
    try:
        result = api.models(['7689903116275174462'])
        passed = result['complete'] and bool(result['models']['7689903116275174462']['tracks'])
        report = {'passed': bool(passed), 'seconds': round(time.monotonic()-start, 2),
                  'errors': result['errors'], 'model_count': len(result['models']),
                  'attempts': result.get('attempts', []),
                  'model_api': result['models'].get('7689903116275174462', {}).get('model_api'),
                  'model_fallback': result['models'].get('7689903116275174462', {}).get('model_fallback')}
        (ROOT/'docs/evidence/model-repro.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False), flush=True)
        signer.mark_success()
        assert passed, 'Previously downloadable episode returned no usable video tracks'
    finally:
        api.close()
