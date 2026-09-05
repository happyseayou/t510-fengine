"""Version-bound digital amplitude identities, independent of PYNQ.

Gains are relative to the the v34 baseline integer scale at the same FFT
schedule. They describe units, not an improvement in ADC information.
"""
from __future__ import annotations
import json

CURRENT_CORE_VERSION = 0x00010036
CURRENT_QMC_GAIN = 16383 / 8192
CURRENT_SCALING_PROFILE = "qmc16383of8192-pfb16-fft0556"


def qmc_settings() -> dict:
    return dict(EnableGain=1, EnablePhase=0,
                GainCorrectionFactor=CURRENT_QMC_GAIN, PhaseCorrectionFactor=0.0,
                OffsetCorrectionFactor=0, EventSource=2)


def scaling_identity(core_version: int, fft_shift: int, blocks: list[dict]) -> dict:
    """Validate all physical ADC readbacks; never infer gain from a label alone."""
    errors = []
    v36 = core_version == CURRENT_CORE_VERSION
    if core_version not in (0x00010034, CURRENT_CORE_VERSION):
        errors.append("unsupported core version for amplitude interpretation")
    expected_pairs = [(t, b) for t in range(4) for b in range(2)]
    if [(r.get("tile"), r.get("block")) for r in blocks] != expected_pairs:
        errors.append("expected eight physical ADCs in tile/block order")
    if fft_shift != 0x0556:
        errors.append("FFT schedule differs from the frozen 0x0556 science contract")
    gains = []
    for row in blocks:
        qmc = row.get("qmc", {})
        if v36 and qmc != qmc_settings():
            errors.append(f"ADC {row.get('tile')}/{row.get('block')} QMC mismatch")
        if not v36 and (qmc.get("EnableGain") != 0 or qmc.get("EnablePhase") != 0
                        or qmc.get("OffsetCorrectionFactor") != 0):
            errors.append("v34 is not in its frozen unity QMC profile")
        gain = qmc.get("GainCorrectionFactor") if qmc.get("EnableGain") else 1.0
        gains.append(gain)
    pfb_gain = 2 if v36 else 1
    return dict(format="T510_DIGITAL_SCALING_V1", ok=not errors, errors=errors,
                core_version=f"0x{core_version:08x}",
                profile=CURRENT_SCALING_PROFILE if v36 else "baseline-qmc-off-pfb17-fft0556",
                coefficient_fraction_bits=17, pfb_output_shift=16 if v36 else 17,
                pfb_voltage_gain=pfb_gain, fft_shift=fft_shift,
                qmc_gain_by_adc=gains, blocks=blocks,
                time_voltage_gain_by_adc=gains,
                spec_voltage_gain_by_adc=[g*pfb_gain if g is not None else None for g in gains],
                normalization="voltage/g; power and visibility/(g_i*g_j); power Allan variance/g**4")


def manifest_metadata(identity: dict) -> dict[str, str]:
    """Attach the actual readback to the receiver's existing string metadata map."""
    checked = scaling_identity(int(identity['core_version'], 0), identity['fft_shift'], identity['blocks'])
    if not checked['ok'] or checked != identity:
        raise ValueError("refusing unverified or inconsistent amplitude identity")
    return dict(core_version=checked['core_version'], scaling_profile=checked['profile'],
                pfb_output_shift=str(checked['pfb_output_shift']),
                fft_shift=f"0x{checked['fft_shift']:04x}",
                digital_scaling=json.dumps(checked, sort_keys=True, separators=(',', ':')))


def historical_unit_divisor(identity: dict, product: str, *, stream: str,
                         adc: int, other_adc: int | None = None) -> float:
    """Divide an unnormalized count product by this factor for historical units.

Normalized Allan variance (variance divided by mean squared) is invariant;
it must not be rescaled a second time. Cross products use both actual gains.
"""
    manifest_metadata(identity)
    if stream not in ('time', 'spec') or not 0 <= adc < 8:
        raise ValueError('invalid stream or ADC')
    gains = identity[f'{stream}_voltage_gain_by_adc']
    gain = gains[adc]
    if product in ('visibility', 'allan_visibility_variance'):
        if other_adc is None or not 0 <= other_adc < 8:
            raise ValueError('visibility requires both ADCs')
        return (gain*gains[other_adc])**(2 if product == 'allan_visibility_variance' else 1)
    powers = dict(voltage=1, power=2, allan_voltage_variance=2,
                  allan_power_variance=4, normalized_allan_variance=0)
    if product not in powers:
        raise ValueError('unsupported count product')
    return gain**powers[product]
