#!/usr/bin/env python3
"""One 60 s common-tone measurement after a separately journaled ADC reset."""
import fcntl
import json
from pathlib import Path
import sys
import t510_stage36_tg_queue as tg


def plan(qid):
    phase = tg.plan(qid)[1]
    phase.update(index=0, segment=1, short_gate=False)
    return [phase]


class RepeatQueue(tg.TGQueue):
    def __init__(self, args, template):
        super().__init__(args, template)
        self.preparation = Path(__file__).resolve().parents[3] / 'preparation'
        init = json.loads((self.preparation/'adc-initialize.json').read_text())
        baseline = json.loads((self.preparation/'interrupt-baseline.json').read_text())
        if not init.get('ok') or init.get('action') != 'ADC' or not baseline.get('ok'):
            raise RuntimeError('missing successful ADC initialization evidence')
        calls = init['operation']['explicit_tile_reset_calls']
        if [(r['kind'],r['tile']) for r in calls] != [('adc',i) for i in range(4)]:
            raise RuntimeError('unexpected reset scope')
        self.phases = plan(args.queue_id)
        self.context.update(initialization_evidence_sha256=tg.science.base.sha256_file(self.preparation/'adc-initialize.json'),
                            intervention='four ADC tile resets then prepare/MTS with TG off')
        self.state.update(phases=self.phases, physical_context=self.context)
        self.state['experiment']['sequence'] = ['60s steady', 'verification and analysis', 'safe stop']

    def preflight(self):
        for name in ('adc-initialize.json','interrupt-baseline.json'):
            tg.science.base.write_json_new(self.evidence/name,json.loads((self.preparation/name).read_text()))
        super().preflight()

    def compare_segments(self):
        super().compare_segments()
        original = self.args.measurement_root/'stage36-tg-capture-20260911-r3-queue/evidence/phase_01_tone.json'
        before = json.loads(original.read_text())
        after = json.loads((self.evidence/'phase_00_tone.json').read_text())
        phase_delta = (after['phase02_complex_mean_deg']-before['phase02_complex_mean_deg']+180)%360-180
        tg.science.base.write_json_new(self.evidence/'comparison_to_original.json',dict(
            original_path=str(original), original_sha256=tg.science.base.sha256_file(original),
            original=before, after_initialization=after, phase_change_wrapped_deg=phase_delta,
            power_ratio_change_db=after['power_ratio_0_over_2_db']-before['power_ratio_0_over_2_db'],
            limitation='One initialization comparison; elapsed time and TG off/on also differ. No cold-boot or broadband claim.'))


def main():
    args = tg.science.parse_args()
    if args.dry_run:
        print(json.dumps(dict(phases=plan(args.queue_id)),indent=2));return 0
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return RepeatQueue(args,json.loads(args.template.read_text())).run()


if __name__ == '__main__':
    sys.exit(main())
