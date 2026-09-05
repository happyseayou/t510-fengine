#!/usr/bin/env python3
"""Versioned, fail-closed numerical contract for Stage 36 FFT evidence.

PG109 (2022-05-04), pp. 33, 70, 77: rounding occurs at multiple internal
locations. The C model is bit accurate (not cycle accurate) without overflow.
An empirical 4-count float-distance threshold is not a correctness oracle.
"""
import hashlib
import json
from pathlib import Path
import re

GENERICS = dict(C_NFFT_MAX=12, C_ARCH=3, C_HAS_NFFT=0, C_USE_FLT_PT=0,
                C_INPUT_WIDTH=16, C_TWIDDLE_WIDTH=16, C_HAS_SCALING=1,
                C_HAS_BFP=0, C_HAS_ROUNDING=1)
SCHEDULE = [2, 1, 1, 1, 1, 1]
FORMAT = 'T510_STAGE36_XFFT_BITACCURATE_V2'
ARTIFACTS = ('fixture.json', 'reference.npz', 'input.mem',
             'production_xfft.vhd', 'real_xfft_prefix_preserved.txt',
             'vendor_xfft_output.txt')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_ip(path):
    text = Path(path).read_text()
    for key, expected in GENERICS.items():
        actual = re.findall(r'\b' + key + r'\s*=>\s*(\d+)\b', text, re.I)
        if actual != [str(expected)]:
            raise RuntimeError(f'production IP parameter mismatch: {key}={actual}')


def read_words(path):
    for line in Path(path).read_text().splitlines():
        f, k, word = line.split()
        f, k = int(f), int(k)
        if f < 0 or not 0 <= k < 4096 or not re.fullmatch(r'[0-9a-fA-F]{64}', word):
            raise RuntimeError('invalid FFT output row')
        yield f * 4096 + k, int(word, 16)


def verify_contract(root):
    root = Path(root)
    proof = json.loads((root/'vendor_xfft_crosscheck.json').read_text())
    if proof.get('format') != FORMAT or proof.get('status') != 'PASS':
        raise RuntimeError('missing qualified bit-accurate evidence')
    if proof.get('generics') != GENERICS or proof.get('scaling_schedule') != SCHEDULE:
        raise RuntimeError('model configuration mismatch')
    if proof.get('model_overflow') != 0 or proof.get('rtl_mismatches') != 0:
        raise RuntimeError('model overflow or RTL mismatch')
    for name in ARTIFACTS:
        if proof.get('artifact_sha256', {}).get(name) != sha(root/name):
            raise RuntimeError(f'FFT evidence identity mismatch: {name}')
    verify_ip(root/'production_xfft.vhd')
    meta = json.loads((root/'fixture.json').read_text())
    if (meta.get('fft_shift') != 0x556 or meta.get('coeff_crc32') != '0xb9ba227c'
            or meta.get('frames') != 35 or meta.get('noise_frames') != 16
            or meta.get('input_mem_sha256') != sha(root/'input.mem')
            or proof.get('model_frames') != meta['frames']):
        raise RuntimeError('fixture configuration mismatch')
    model = []
    for index, word in read_words(root/'vendor_xfft_output.txt'):
        if index != len(model):
            raise RuntimeError('model output noncontiguous or duplicate')
        model.append(word)
    if len(model) != meta['frames'] * 4096:
        raise RuntimeError('incomplete model output')
    count = 0
    for index, word in read_words(root/'real_xfft_prefix_preserved.txt'):
        if index != count or index >= len(model) or word != model[index]:
            raise RuntimeError('RTL/model exact comparison failed')
        count += 1
    if count < 4 * 4096 or proof.get('rtl_prefix_bins') != count:
        raise RuntimeError('inadequate real RTL witness')
    if (proof.get('rtl_complete_frames') != count // 4096
            or proof.get('rtl_complex_cells') != count * 8):
        raise RuntimeError('RTL witness count mismatch')
    return proof, model
