#!/usr/bin/env python3
"""Stopped-board MTS / RFDC intervention; use the installed current controller."""
import contextlib
import hashlib
import json
from pathlib import Path
import sys
import zlib
sys.path.insert(0, '/opt/t510-agent/current')
from python import t510_hw as hw


def reset_selected_tiles(core, kind, indices=None):
    """Reset only the selected indices of one converter kind."""
    if kind not in ('adc', 'dac'):
        raise ValueError('invalid converter kind')
    tiles = list(getattr(core.rfdc, kind + '_tiles'))
    if len(tiles) != 4:
        raise RuntimeError('expected exactly four selected RFDC tiles')
    indices = tuple(range(4)) if indices is None else tuple(indices)
    if not indices or len(set(indices)) != len(indices) or any(type(i) is not int or i not in range(4) for i in indices):
        raise ValueError("invalid tile selection")
    calls = []
    for index in indices:
        tile = tiles[index]
        method = next((name for name in ('Reset', 'reset') if callable(getattr(tile, name, None))), None)
        if method is None:
            raise RuntimeError(f'{kind} tile {index} has no Reset method')
        value = getattr(tile, method)()
        calls.append({'kind':kind, 'tile':index, 'method':method, 'result':repr(value)})
    return calls


def execute(action, observer=None):
    if action not in ('probe', 'M', 'P', 'R', 'ADC', 'DAC', 'T0', 'T3'):
        raise ValueError('unsupported intervention')
    with hw._configure_hardware_guard(True):
        request = hw._load_saved_configure_request()
        controller = hw._controller(request)
        core = controller.require_core()
        status = core.read_status()
        if status['streaming'] or status['board_id'] != 1:
            raise RuntimeError('requires stopped board 1')
        clock_before = dict(core.read_lmk_status(include_registers=True))
        if clock_before['profile_id'] != '160m_10m_request_manual_clkin0' or any(clock_before[k] != 1 for k in ('pll1_lock','pll2_lock')):
            raise RuntimeError('requires locked onboard TCXO')
        scaling_before = core.read_digital_scaling(require=True)
        result = {'action': action, 'clock_before': clock_before, 'scaling_before': scaling_before,
                  'helper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        if action == 'probe':
            return dict(result, ok=True)
        original_mts = None
        try:
            if observer is not None:
                original_mts = core._run_rfdc_mts_sequence
                def traced_mts(*args, **kwargs):
                    observer("before_mts", core)
                    value = original_mts(*args, **kwargs)
                    observer("after_mts", core)
                    return value
                core._run_rfdc_mts_sequence = traced_mts
            core.set_dac_enable_mask(0)
            if observer is not None:
                observer("before_operation", core)
            if action == 'M':
                # No tile Reset, mixer/NCO rewrite, QMC rewrite, PL reload, or LMK profile rewrite.
                mts = core._run_rfdc_mts_sequence(required=True, adc_tiles=15, dac_tiles=15,
                                                 adc_target_latency=492, dac_target_latency=-1)
                if not mts.get('calls') or mts.get('failures'):
                    raise RuntimeError('MTS call evidence missing or failed')
                core.rfdc_sync_status = {'mts': mts}
                core.persist_mts_result_id(zlib.crc32(json.dumps(mts, sort_keys=True, default=str).encode()) or 1)
                summary = hw._mts_summary(core, core_version='0x00010036')
                hw._persist_mts_summary(summary)
                result.update(mts_calls=mts, mts=summary)
            else:
                # All reset selections share this exact production restore path.
                config = hw._config_from_saved_request(request, sample_rate_msps=320,
                    center_mhz=200.0, mts_adc_target_latency=492, mts_dac_target_latency=-1)
                sysref = core.clock.set_sysref(True)
                if observer is not None:
                    observer("before_reset", core)
                if action in ('T0', 'T3'):
                    reset_calls = reset_selected_tiles(core, 'adc', (int(action[1]),))
                elif action in ('ADC', 'DAC'):
                    reset_calls = reset_selected_tiles(core, action.lower())
                else:
                    reset_calls = core.reset_all_rfdc_tiles() if action == 'R' else []
                if observer is not None:
                    observer("after_reset" if reset_calls else "no_reset_control", core)
                applied = controller.prepare(config, fresh_download=False, program_dac=False,
                    clock_ref='tcxo_10mhz', clock_profile='160m_10m_request_manual_clkin0',
                    force_clock_reconfigure=False, require_clock_preserved=True)
                if observer is not None:
                    observer("after_prepare", core)
                recovery = applied['observation']['clock_recovery']
                if recovery.get('clock_reconfigured') or recovery.get('tile_reset_calls') or not recovery.get('clock_preserved'):
                    raise RuntimeError('prepare changed the clock or reset tiles unexpectedly')
                if len(reset_calls) != {'P':0, 'R':8, 'ADC':4, 'DAC':4, 'T0':1, 'T3':1}[action]:
                    raise RuntimeError('explicit tile reset count mismatch')
                summary = hw._mts_summary(core, core_version='0x00010036')
                hw._persist_mts_summary(summary)
                result.update(mts=summary, operation={'applied':applied,
                    'sysref_for_prepare':sysref, 'explicit_tile_reset_calls':reset_calls})
            if result['mts']['adc']['active_measured_latency'] != [492]*4:
                raise RuntimeError('ADC fixed latency did not pass')
            result['scaling_after'] = core.read_digital_scaling(require=True)
            if scaling_before != result['scaling_after']:
                raise RuntimeError('digital scale changed')
            result['clock_after'] = dict(core.read_lmk_status(include_registers=True))
            if any(result['clock_after'][k] != 1 for k in ('pll1_lock','pll2_lock')):
                raise RuntimeError('PLL unlocked')
            if result['clock_after'].get('profile_sha256') != clock_before.get('profile_sha256'):
                raise RuntimeError('clock profile identity changed')
            return dict(result, ok=True)
        finally:
            if original_mts is not None:
                core._run_rfdc_mts_sequence = original_mts
            core.stop()
            core.set_dac_enable_mask(0)
            core.clock.set_sysref(False)

if __name__ == '__main__':
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = execute(sys.argv[1])
        print(json.dumps(result, default=str))
    except Exception as exc:
        print(json.dumps({'ok':False, 'error':f'{type(exc).__name__}: {exc}'}))
        raise
