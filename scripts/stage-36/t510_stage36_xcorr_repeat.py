#!/usr/bin/env python3
"""One additional 900 s cross scan; verify, stop, and await operator restart.

Reuse the qualified acquisition lifecycle. Never auto-start another scan.
"""
import fcntl
import json
from pathlib import Path
import sys
import t510_stage36_science_capture_queue as science
import t510_stage35_fullband100_verify as fullband

class Repeat(science.Queue):
    def __init__(self, args, template):
        super().__init__(args, template)
        self.phases = [dict(index=0, kind='xcorr', label='pairs-repeat',
            scan='PAIRS', position='scan', mode='spec_only', duration_seconds=900,
            scan_id=args.queue_id+'-xcorr-900s', status='pending')]
        self.state.update(phases=self.phases,
            products=['28_pairs_4096_bins_900s_native_100ms_derived_1s'],
            next_action=('COMPARE_THREE_SCANS' if getattr(args, 'after_restart', False)
                         else 'WAIT_FOR_OPERATOR_FENGINE_RESTART'),
            after_operator_restart=bool(getattr(args, 'after_restart', False)),
            automatic_second_capture=False)

    def preflight(self):
        super().preflight()
        science.base.write_json_new(self.evidence/'repeat_implementation.json', {
            'runner_sha256':science.base.sha256_file(Path(__file__)),
            'numeric_verifier_sha256':science.base.sha256_file(Path(fullband.__file__)),
            'scope':'one scan only; restart and next scan require operator continuation'})

    def independent_verify(self):
        self.state['verification_status']='running';self.save()
        dataset=self.args.measurement_root/self.phases[0]['scan_id']
        manifest_path=dataset/'dataset_manifest.json'
        digest=(dataset/'dataset_manifest.sha256').read_text().split()[0]
        if science.base.sha256_file(manifest_path)!=digest:
            raise RuntimeError('dataset manifest hash mismatch')
        manifest=json.loads(manifest_path.read_text())
        for row in manifest['files']:
            path=dataset/row['path']
            if path.stat().st_size!=row['bytes'] or science.base.sha256_file(path)!=row['sha256']:
                raise RuntimeError('sealed file identity mismatch: '+str(path))
        result=fullband.verify(dataset,900)
        science.base.write_json_new(self.evidence/'fullband_numeric_verification.json',result)
        if result['status']!='PASS':raise RuntimeError('numeric verification failed')
        self.state['verification_status']='PASS';self.save()

def main():
    after_restart = "--after-restart" in sys.argv
    if after_restart:
        sys.argv.remove("--after-restart")
    args=science.parse_args()
    args.after_restart = after_restart
    if args.dry_run:
        print(json.dumps({'scans':1,'duration_seconds':900,'stop_after':True,
            'automatic_second_capture':False}));return 0
    args.lock.parent.mkdir(parents=True,exist_ok=True)
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return Repeat(args,json.loads(args.template.read_text())).run()

if __name__=='__main__':sys.exit(main())
