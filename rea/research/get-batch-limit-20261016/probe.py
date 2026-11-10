"""Bounded GET batch-size experiment. Never edits production or rotates IDs.

probe_support.py is an exact copy of the previous audited experiment harness;
only its Probe class and utilities are used. Every supplied VID is distinct and
comes from the already recorded episode catalog. No retry/fallback/media access.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import time

import probe_support as p

CATALOG = p.PROJECT/'experiments/signature-deep-20261014/episode-catalog.json'
DEPS = ('sign/unidbg-sign.jar', 'capture/fq_oversea/libmetasec_ml.so',
        'capture/fq_oversea/libc++_shared.so', 'capture/fq_oversea/ms_16777218.bin')


class LimitProbe(p.Probe):
    def _json_request(self, stage, method, url, headers, data, request_body=None):
        if stage == 'api':
            self.active['request_url_bytes'] = len(url.encode())
            self.active['request_target_bytes'] = len(url.split(self.host, 1)[1].encode())
        return super()._json_request(stage, method, url, headers, data, request_body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('label')
    parser.add_argument('sizes', type=int, nargs='+')
    parser.add_argument('--reverse', action='store_true')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--stop-on-incomplete', action='store_true')
    args = parser.parse_args()
    assert args.label.replace('-', '').isalnum()
    catalog = json.loads(CATALOG.read_text())
    episodes = [dict(ep, series_id=series['series_id'])
                for series in catalog.values() for ep in series['episodes']]
    vids = [ep['vid'] for ep in episodes]
    assert len(vids) == len(set(vids)) and all(v.isdigit() for v in vids)
    assert all(1 <= n <= min(100, len(vids)-args.offset) for n in args.sizes)
    report_path = p.HERE/(args.label+'.json')
    assert not report_path.exists(), 'Do not overwrite an existing run'
    before = p.protected_hashes()
    p.write(p.HERE/(args.label+'-before-hashes.json'), before)
    p.write(p.HERE/'catalog.json', {'source':str(CATALOG.relative_to(p.ROOT)),
                                  'source_sha256':p.sha(CATALOG.read_bytes()),
                                  'episodes':episodes})
    vendor = p.HERE/'runtime/vendor'
    assert not vendor.exists(), 'Previous signer runtime needs investigation'
    for rel in DEPS:
        src = p.PROJECT/'vendor'/rel
        dest = vendor/rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        assert p.sha(src.read_bytes()) == p.sha(dest.read_bytes())
    report = {'started':p.now(), 'label':args.label,
              'endpoint':p.TAB, 'policy':'current', 'sizes':args.sizes,
              'reverse':args.reverse, 'offset':args.offset,
              'device':'unchanged production devices.json[0]',
              'signature_policy':'JAR other headers + unchanged production Python H/M v3',
              'no_retry_fallback_rotation_cache':True, 'media_requests':0,
              'max_batch_count':100, 'per_request_gap_seconds':3,
              'results':[]}
    p.write(report_path, report)
    device = json.loads((p.PROJECT/'config/devices.json').read_text(encoding='utf-8-sig'))[0]
    try:
        with p.LocalSigner(vendor) as signer:
            report['signer_pid'] = signer.process.pid
            api = LimitProbe(p.PROJECT/'config/config.json', signer.url, signer.token,
                             timeout=25, device=deepcopy(device))
            try:
                for n in args.sizes:
                    time.sleep(3)
                    selected = vids[args.offset:args.offset+n]
                    if args.reverse:
                        selected.reverse()
                    assert len(selected) == n == len(set(selected))
                    row = {'id':f'{args.label}-{len(report["results"])+1:02d}-n{n}',
                           'policy':'current', 'endpoint':'new_get',
                           'requested_count':n, 'vids':selected}
                    api.active = row
                    try:
                        api._api_once('GET', p.TAB, extra_query={
                            'video_id':','.join(selected), 'video_platform':'1024',
                            'need_all_video_definition':'true', 'device_level':'3',
                            'detail_page_version':'0'})
                    except Exception as exc:
                        row['error'] = p.safe_error(exc)
                        row.setdefault('success', False)
                    finally:
                        api.active = None
                    returned = set(row.get('returned_vids', []))
                    row['returned_count'] = len(returned)
                    row['valid_models'] = sum(bool(m.get('tracks', 0) > 0 and m.get('usable_urls'))
                                              for m in row.get('models', {}).values())
                    row['missing_vids'] = sorted(set(selected)-returned)
                    row['unexpected_vids'] = sorted(returned-set(selected))
                    row['exact_coverage'] = returned == set(selected)
                    row['success'] = row.get('success', False) and row['exact_coverage']
                    report['results'].append(row)
                    p.write(report_path, report)
                    print(json.dumps({k:row.get(k) for k in (
                        'id','requested_count','returned_count','valid_models','success',
                        'http_status','codes','base_resp','message','seconds',
                        'response_bytes','request_url_bytes','error')}, ensure_ascii=False), flush=True)
                    if row.get('http_status') == 429:
                        report['stop_reason'] = 'HTTP 429'; break
                    if args.stop_on_incomplete and not row['success']:
                        report['stop_reason'] = 'first incomplete/failure'; break
                signer.mark_success()
            finally:
                api.close()
    finally:
        report['finished'] = p.now()
        after = p.protected_hashes()
        changed = [k for k in sorted(before.keys()|after.keys()) if before.get(k) != after.get(k)]
        report['preservation'] = {'checked_files':len(before), 'changed':changed,
                                  'unchanged':not changed}
        # This directory was created by this run and contains only copied deps
        # and disposable signer state; original vendor files remain untouched.
        shutil.rmtree(vendor)
        vendor.parent.rmdir()
        report['runtime_copy_removed'] = True
        p.write(report_path, report)
        print(json.dumps({'event':'finished', 'label':args.label,
                          'preservation':report['preservation']}, ensure_ascii=False), flush=True)
        assert not changed, changed


if __name__ == '__main__':
    main()
