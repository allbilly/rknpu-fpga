#!/usr/bin/env python3
"""Equivalence runner: adopted per-profile conv core vs runtime-decoded engine.

For each frozen conv capture this runner:

1. rebuilds the fixture's exact raw command stream (the same three documented
   DMA-address relocations the strict runners use) and the packed operand bytes;
2. compiles one bench that instantiates BOTH the adopted per-profile core and
   the runtime-decoded prototype on the same clock, memory contract and stream;
3. runs the equivalence replay (complete operand-read and output-write sequence
   compare, complete memory-image compare, frame/ack counters) and the runtime
   decoder's fail-closed negative controls (each must raise the specific code
   and touch no memory);
4. compares the runtime engine's written output BO bytes against the fixture's
   frozen expected/device bytes (byte-exact for FP16, documented tolerance for
   the FP32 capture) and the untouched padding against the canary;
5. writes a source-hash-bound receipt under build/runtime-conv-lab/.

Every compile/simulation is launched through build/verif/host_guard/safe_run.sh
(battery + thermal gate + global heavy-job lock).
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import shlex
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
FIXTURES = ROOT / 'tests/conv/fixtures'
BUNDLES = ROOT / 'build/rk3588-example-captures'
TB = HERE / 'tb_conv_runtime_equiv.sv'
MODEL = HERE / 'conv_runtime_model.py'
RUNNER = Path(__file__).resolve()
OUT_ROOT = ROOT / 'build/runtime-conv-lab'
GUARD = ROOT / 'build/verif/host_guard/safe_run.sh'
DONOR_RTL = ROOT / 'rtl/vendor/nvdla'

sys.path.insert(0, str(HERE))
import conv_runtime_model as model  # noqa: E402

DONOR_SOURCES = [
    'compat/nv_assert_never.v',
    'compat/nv_assert_no_x.v',
    'NV_DW_lsd.v',
    'NV_DW02_tree.v',
    'NV_NVDLA_CMAC_CORE_MAC_mul.v',
    'NV_NVDLA_CACC_CALC_fp_48b.v',
    'HLS_fp32_to_fp16.v',
]
RTL_SOURCES_COMMON = [
    'rtl/cmac/rk_cmac_fp16_cell.sv',
    'rtl/cmac/rk_cmac_fp16_array.sv',
    'rtl/cmac/rk_nvdla_cacc.sv',
    'rtl/cmac/rk_cacc_fp16_array.sv',
    'rtl/cmac/rk_cmac_cacc_fp16_array.sv',
    'rtl/cmac/rk_nvdla_fp32_to_fp16.sv',
    'rtl/cmac/rk_cmac_writer.sv',
    'rtl/cmac/rk_cmac_output_nvdla.sv',
    'rtl/cmac/rk_cmac_frame_output.sv',
    'rtl/cmac/rk_cmac_rw_arbiter.sv',
    'rtl/cmac/rk_conv_output_atom.sv',
    'rtl/cmac/rk_cmac_fp32_writer.sv',
    'rtl/cmac/rk_cmac_output_fp32.sv',
    'rtl/cmac/rk_conv_output_c1c2_fp32.sv',
    'rtl/cmac/rk_conv_3x3_valid_c4_profile.sv',
    'rtl/cmac/rk_conv_3x3_valid_c4_front.sv',
    'rtl/cmac/rk_frame_stage.sv',
    'rtl/cmac/rk_conv_3x3_valid_c4_core.sv',
    'rtl/cmac/experimental/runtime/rk_conv_runtime_decode.sv',
    'rtl/cmac/experimental/runtime/rk_conv_runtime_front.sv',
    'rtl/cmac/experimental/runtime/rk_conv_runtime_fp32_output.sv',
    'rtl/cmac/experimental/runtime/rk_conv_runtime_core.sv',
    # ADDITIVE experimental copies used by the parameterised runtime core
    # (C16-capable cell/array/cacc + parameterised stage); FINAL-frozen files
    # rk_cmac_fp16_cell/array/cacc and rk_frame_stage remain untouched.
    'rtl/cmac/experimental/runtime/rk_runtime_frame_stage.sv',
    'rtl/cmac/experimental/runtime/rk_runtime_fp16_cell.sv',
    'rtl/cmac/experimental/runtime/rk_runtime_fp16_array.sv',
    'rtl/cmac/experimental/runtime/rk_runtime_cacc_fp16_array.sv',
]
# The adopted conv-simple reference path is only compiled for conv-simple cases;
# its production decoder uses always_comb, which Icarus reports as a
# sensitivity-list "sorry:" (the same limitation the adopted conv-simple
# receipts already carry). Vendor cases compile no conv-simple module at all.
RTL_SOURCES_SIMPLE = [
    'rtl/cmac/rk_conv_simple_profile.sv',
    'rtl/cmac/rk_conv_simple_core.sv',
]
RTL_SOURCES = RTL_SOURCES_COMMON + RTL_SOURCES_SIMPLE
PRODUCTION_SORRY_ALLOWED = [
    'rtl/cmac/rk_conv_simple_profile.sv',
]

# Case registry: fixture family, placement, reference-core parameters and the
# output-byte comparison policy. `bundle` cases are the unpinned READY capture
# bundles; they have no adopted per-profile core, so they are replay-only
# (labelled UNPINNED-BUNDLE in every receipt).
CASES = {
    'conv_3x3_valid_c4_h9_w9_oc4': dict(
        family='conv-fp16', sim_params=dict(V_STRIDE2=0),
        expected_tolerance=0.0),
    'conv_3x3_stride2_c4_h11_w11_oc4': dict(
        family='conv-fp16', sim_params=dict(V_STRIDE2=1),
        expected_tolerance=0.0),
    'conv_3x3_pad1_zero_frame_c4_h9_w9_oc4': dict(
        family='conv-fp16', sim_params=dict(V_PAD1=1),
        expected_tolerance=0.0),
    'conv_grouped_3x3_c4_h5_w5_oc8_g2_task0': dict(
        family='conv-fp16', sim_params=dict(V_GROUPED=1),
        expected_tolerance=0.0),
    'conv_grouped_3x3_c4_h5_w5_oc8_g2_task1': dict(
        family='conv-fp16', sim_params=dict(V_GROUPED=1),
        expected_tolerance=0.0),
    'conv_splitoc_3x3_c16_h9_w9_oc16_task0': dict(
        family='conv-fp16', sim_params=dict(V_SPLITOC=1),
        expected_tolerance=0.0),
    'conv_splitoc_3x3_c16_h9_w9_oc16_task1': dict(
        family='conv-fp16', sim_params=dict(V_SPLITOC=1),
        expected_tolerance=0.0),
    'conv_depthwise_3x3_c3_h11_w28_oc3': dict(
        family='conv-fp16', sim_params=dict(V_DEPTHWISE=1),
        expected_tolerance=0.0),
    'conv_simple_fp16_3x3_c4_h8_w8_oc16': dict(
        family='conv-simple',
        sim_params=dict(S_PROFILE=0, S_INPUT_H=8, S_INPUT_W=8, S_KH=3,
                        S_KW=3, S_INPUT_CHANNELS=4, S_KERNELS=8,
                        S_C1_BLOCKS=2, S_ALIGN_C=8, S_PACK_C2=4,
                        S_CHUNK_LANES=16, S_OUTPUT_FP16=1),
        expected_tolerance=0.0),
    'conv_simple_fp16_5x5_c4_h8_w8_oc16': dict(
        family='conv-simple',
        sim_params=dict(S_PROFILE=1, S_INPUT_H=8, S_INPUT_W=8, S_KH=5,
                        S_KW=5, S_INPUT_CHANNELS=4, S_KERNELS=8,
                        S_C1_BLOCKS=2, S_ALIGN_C=8, S_PACK_C2=4,
                        S_CHUNK_LANES=16, S_OUTPUT_FP16=1),
        expected_tolerance=0.0),
    'conv_simple_fp16_3x3_c16_h8_w8_oc32': dict(
        family='conv-simple',
        sim_params=dict(S_PROFILE=2, S_INPUT_H=8, S_INPUT_W=8, S_KH=3,
                        S_KW=3, S_INPUT_CHANNELS=16, S_KERNELS=8,
                        S_C1_BLOCKS=4, S_ALIGN_C=16, S_PACK_C2=8,
                        S_CHUNK_LANES=16, S_OUTPUT_FP16=1),
        expected_tolerance=0.0),
    'conv_simple_fp16_1x1_c4_h8_w8_oc16': dict(
        family='conv-simple',
        sim_params=dict(S_PROFILE=3, S_INPUT_H=8, S_INPUT_W=8, S_KH=1,
                        S_KW=1, S_INPUT_CHANNELS=4, S_KERNELS=8,
                        S_C1_BLOCKS=2, S_ALIGN_C=8, S_PACK_C2=4,
                        S_CHUNK_LANES=16, S_OUTPUT_FP16=0),
        expected_tolerance=0.001),
    'conv_1x1_valid_c8_h5_w5_oc8': dict(
        family='conv-fp16', sim_params=dict(V_STRIDE2=0),
        expected_tolerance=0.0, bundle=True),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def tool_version(argv: list[str]) -> str:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=60)
    text = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise RuntimeError(f'tool version command failed: {argv}: {text}')
    return text.splitlines()[0] if text else 'unknown'


def load_case(case: str) -> dict:
    spec = CASES[case]
    if spec.get('bundle'):
        loaded = model.load_bundle(case)
        bundle = loaded['fixture']
        addresses = {'a': 0x1000, 'w': 0x2000, 'out': 0x3000}
        loaded['addresses'] = addresses
        loaded['expected_file'] = bundle / 'expected.bin'
        loaded['device_file'] = bundle / 'expected.bin'  # no device_out.bin
        loaded['bundle_label'] = 'UNPINNED-BUNDLE'
    else:
        loaded = model.load_case(case)
        manifest = loaded['manifest']
        if spec['family'] == 'conv-fp16':
            addresses = manifest['command']['addresses']
            loaded['expected_file'] = loaded['fixture'] / 'expected.bin'
            loaded['device_file'] = loaded['fixture'] / 'device_out.bin'
        else:
            addresses = manifest['command_stream']['addresses']
            loaded['expected_file'] = loaded['fixture'] / 'expected.bin'
            loaded['device_file'] = loaded['fixture'] / 'device_out.bin'
        loaded['addresses'] = addresses
        loaded['bundle_label'] = None
    config = loaded['config']
    loaded['bo'] = {
        'in_base': addresses.get('a', addresses.get('input')),
        'in_hw': loaded['input_bytes'] // 2,
        'w_base': addresses.get('w', addresses.get('weight')),
        'w_hw': loaded['weight_bytes'] // 2,
        'out_base': addresses.get('out'),
        'out_hw': loaded['output_bytes'] // 2,
    }
    assert config['input_bytes'] == loaded['input_bytes']
    assert config['weight_bytes'] == loaded['weight_bytes']
    assert config['output_bytes'] == loaded['output_bytes']
    return loaded


def fixture_hex(directory: Path, loaded: dict, spec: dict,
                mem_words: int = 0) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    commands = loaded['commands']
    (directory / 'commands.hex').write_text(
        ''.join(f'{word:016x}\n' for word in struct.unpack(
            f'<{len(commands) // 8}Q', commands)))
    for source, target in ((loaded['input_path'], 'input.hex'),
                           (loaded['weight_path'], 'weight.hex')):
        payload = source.read_bytes()
        if len(payload) % 2:
            raise ValueError(f'{source.name} is not whole halfwords')
        words = struct.unpack(f'<{len(payload) // 2}H', payload)
        (directory / target).write_text(
            ''.join(f'{word:04x}\n' for word in words))
    if mem_words:
        # One exact-size image shared by both memory models: canary fill plus
        # the packed operand BOs at their word offsets (harness data only).
        bo = loaded['bo']
        image = [0xa5a5 ^ ((k * 17) & 0xffff) for k in range(mem_words)]
        in_words = struct.unpack(f'<{len((directory / "input.hex").read_text().split())}H', b'')             if False else []
        inputs = [int(x, 16) for x in
                  (directory / 'input.hex').read_text().split()]
        weights = [int(x, 16) for x in
                   (directory / 'weight.hex').read_text().split()]
        for k, value in enumerate(inputs):
            image[bo['in_base'] // 2 + k] = value
        for k, value in enumerate(weights):
            image[bo['w_base'] // 2 + k] = value
        (directory / 'init.hex').write_text(
            ''.join(f'{value:04x}\n' for value in image))


def reference_params(case: str, loaded: dict) -> dict:
    spec = CASES[case]
    params = {'FAMILY': 1 if spec['family'] == 'conv-simple' else 0,
              'NUM_CMD': len(loaded['commands']) // 8}
    for key, value in spec['sim_params'].items():
        params[key] = value
    # Size the bench's address window to this case's BO aperture (rounded up to
    # a 1 KiB word boundary). This keeps preload/compare loops small; it is
    # harness-only and the engines still address the same bytes.
    bo = loaded['bo']
    aperture_bytes = max(bo['in_base'] + loaded['input_bytes'],
                         bo['w_base'] + loaded['weight_bytes'],
                         bo['out_base'] + loaded['output_bytes'])
    mem_words = ((aperture_bytes + 1) // 2 + 1023) // 1024 * 1024
    params['MEM_WORDS'] = max(2048, mem_words)
    return params


def rtl_sources_for(family: str) -> list[str]:
    if family == 'conv-simple':
        return RTL_SOURCES
    return RTL_SOURCES_COMMON


def command_sources(loaded: dict) -> list[Path]:
    return ([DONOR_RTL / name for name in DONOR_SOURCES] +
            [ROOT / name for name in rtl_sources_for(loaded['family'])] +
            [TB])


def negative_controls(case: str, loaded: dict) -> list[dict]:
    """Decoder fail-closed controls derived from the decoded field map."""
    config = loaded['config']
    # The golden model uses conv_fp16/conv_simple internally; the case registry
    # uses conv-fp16/conv-simple. Accept either spelling here.
    vendor = config['family'] in ('conv_fp16', 'conv-fp16')
    address_words = ([21, 27, 35] if vendor else [18, 24, 32])
    ds0_index = 7 if vendor else 4
    conv1_index = 4 if vendor else 1
    conv3_index = 6 if vendor else 3
    ws2_index = 13 if vendor else 10
    cvt5_index = 28 if vendor else 25
    out_hw = loaded['bo']['out_hw']
    out_base = loaded['bo']['out_base']
    controls = [
        dict(name='unknown_target', mode=2, index=10, xor_lo=0x0400, code=1),
        dict(name='unknown_offset', mode=3, index=10, xor_lo=4, code=1),
        dict(name='out_of_order_fields', mode=8, index=8, code=1),
        dict(name='early_command_boundary', mode=4, index=20, code=3),
        dict(name='x_value_in_stream', mode=10, index=address_words[0], code=2),
        dict(name='second_stream', mode=9, code=7),
        dict(name='invalid_input_geometry', mode=1, index=ds0_index,
             xor_lo=1, code=2),
        dict(name='dtype_precision_mismatch', mode=1, index=conv1_index,
             xor_lo=1 << 4, code=2),
        dict(name='packing_selector_mismatch', mode=1, index=cvt5_index,
             xor_lo=1, code=2),
        dict(name='weight_kernel_mismatch', mode=1, index=ws2_index,
             xor_lo=1, code=2),
        dict(name='stride_beyond_supported', mode=6, index=conv3_index,
             val_lo=0x1b, code=2),
        dict(name='kernel_beyond_supported', mode=6, index=ws2_index,
             val_lo=(7 << 24) | (3 << 16) |
             (config['output_channels'] if not config['depthwise'] else 1),
             code=2),
        dict(name='misaligned_input_base', mode=1,
             index=address_words[0], xor_lo=0x8, code=4),
        dict(name='overlapping_buffers', mode=6, index=address_words[1],
             val_lo=out_base, code=4),
        dict(name='address_range_overflow', mode=6, index=address_words[0],
             val_lo=0xfffffff0, code=4),
    ]
    # A depthwise capture additionally exercises the depthwise-mode mismatch.
    if config['depthwise']:
        controls.append(dict(name='depthwise_mode_mismatch', mode=1,
                             index=conv1_index, xor_lo=1, code=2))
    else:
        controls.append(dict(name='depthwise_mode_mismatch', mode=1,
                             index=conv1_index, xor_lo=1, code=2))
    # Weight/output size field disagreements.
    if vendor:
        controls.append(dict(name='weight_size_mismatch', mode=1,
                             index=11, xor_lo=2, code=2))
    else:
        controls.append(dict(name='weight_size_mismatch', mode=1,
                             index=8, xor_lo=2, code=2))
    return controls


def guarded(command: list[str]) -> list[str]:
    """The runner must itself be launched through the host guard, which holds
    the global heavy-job lock for the whole multi-case run; wrapping each batch
    again would deadlock on the non-reentrant lock. Detect the guard-provided
    environment and otherwise refuse to launch a heavy job unguarded.
    """
    if 'BENCH_MIN_BATTERY' not in os.environ:
        raise RuntimeError(
            'heavy work refused: launch this runner through '
            f'`BENCH_MIN_BATTERY=30 BENCH_CPUS=0-1 BENCH_CPU_QUOTA=60 '
            f'{GUARD} python3 {Path(__file__).relative_to(ROOT)} ...`')
    return command


def sim_command(simulator: str, build: Path) -> list[str]:
    if simulator == 'iverilog':
        return [shutil.which('vvp'), str(build)] if build.name.endswith('.vvp') \
            else [shutil.which('vvp'), str(build)]
    return [str(build / 'sim')]


def build_batch(simulator: str, outdir: Path, params: dict,
                fixture_dir: Path, bo: dict, controls: list[dict],
                params_family: str, leg: str = 'full') -> list[str]:
    """Build the compile + every simulation invocation as one shell script so
    the whole case runs under a single heavy-lock acquisition."""
    outdir.mkdir(parents=True, exist_ok=True)
    donor = [str(DONOR_RTL / name) for name in DONOR_SOURCES]
    rtl = [str(ROOT / name) for name in rtl_sources_for(params_family)]
    lines = ['#!/bin/bash', 'set -u', f'cd {shlex.quote(str(ROOT))}']
    if simulator == 'iverilog':
        build = outdir / 'sim.vvp'
        param_args = [f'-Ptb_conv_runtime_equiv.{key}={value}'
                      for key, value in params.items()]
        compile_cmd = [shutil.which('iverilog'), '-g2012',
                       '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                       *param_args, '-Irtl', f'-I{DONOR_RTL}', '-s',
                       'tb_conv_runtime_equiv', '-o', str(build),
                       *donor, *rtl, str(TB)]
        run_prefix = [shutil.which('vvp'), str(build)]
    else:
        build = outdir / 'obj_dir'
        param_args = [f'-G{key}={value}' for key, value in params.items()]
        compile_cmd = [shutil.which('verilator'), '--binary', '--timing',
                       '--assert', '-Wall', '-Wno-fatal', '-j', '1',
                       '--timescale-override', '1ns/1ps',
                       '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', *param_args,
                       '-Irtl', f'-I{DONOR_RTL}', '--top-module',
                       'tb_conv_runtime_equiv', '--Mdir', str(build),
                       '-o', 'sim', *donor, *rtl, str(TB)]
        run_prefix = [str(build / 'sim')]
    lines.append('status=0')
    log = lambda name: shlex.quote(str(outdir / name))
    lines.append(f'{" ".join(shlex.quote(part) for part in compile_cmd)}'
                 f' > {log("compile.log")} 2>&1')
    lines.append(f'rc=$?; echo "COMPILE=$rc" >> {log("status.txt")}; status=$rc')
    lines.append('if [ "$rc" -eq 0 ]; then')
    # The memory models own their contents and dumps (no hierarchical memory
    # access from the bench); they load the same operand bytes via plusargs.
    base_args = [
        f'+FIXTURE={fixture_dir}',
        f'+IN_BASE={bo["in_base"]}', f'+IN_HW={bo["in_hw"]}',
        f'+W_BASE={bo["w_base"]}', f'+W_HW={bo["w_hw"]}',
        f'+OUT_BASE={bo["out_base"]}', f'+OUT_HW={bo["out_hw"]}',
        f'+INIT_FILE={fixture_dir / "init.hex"}',
        f'+RT_DUMP={fixture_dir / "mem_rt.hex"}',
        f'+REF_DUMP={fixture_dir / "mem_ref.hex"}',
        '+MUT_MODE=0', '+MUT_INDEX=0', '+MUT_CODE=0', '+MUT_XOR_LO=0',
        '+MUT_XOR_HI=0', '+MUT_VAL_LO=0', '+MUT_VAL_HI=0',
    ]
    invocations = []
    if leg in ('full', 'primary'):
        invocations.append(('mode-0', 0, None))
    if leg in ('full', 'controls'):
        for control in controls:
            invocations.append((
                f'reject-{control["name"]}', 1,
                {**{k: v for k, v in control.items()
                    if k in ('mode', 'index', 'code', 'xor_lo', 'val_lo')}}))
    for name, mode, control in invocations:
        args = list(base_args)
        args.append(f'+MODE={mode}')
        if control is not None:
            # Drop every baseline mutation plusarg so the control's values are
            # the only match (a later duplicate would otherwise be ignored).
            args = [arg for arg in args if not arg.startswith('+MUT_')]
            args += [
                f'+MUT_MODE={control["mode"]}',
                f'+MUT_INDEX={control.get("index", 0)}',
                f'+MUT_CODE={control["code"]}',
                f'+MUT_XOR_LO={control.get("xor_lo", 0)}',
                f'+MUT_XOR_HI=0',
                f'+MUT_VAL_LO={control.get("val_lo", 0)}',
                f'+MUT_VAL_HI=0',
            ]
        command = ' '.join(shlex.quote(part) for part in run_prefix + args)
        lines.append(f'{command} > {log(name + ".log")} 2>&1')
        lines.append(f'rc=$?; echo "RUN={name}=$rc" >> {log("status.txt")}')
        lines.append('if [ "$rc" -ne 0 ]; then status=1; fi')
    lines.append('fi')
    lines.append('exit $status')
    script = outdir / 'run_batch.sh'
    script.write_text('\n'.join(lines) + '\n')
    script.chmod(0o755)
    return ['bash', str(script)]


def tool_versions(simulator: str) -> str:
    if simulator == 'iverilog':
        return tool_version([shutil.which('iverilog'), '-V'])
    return tool_version([shutil.which('verilator'), '--version'])


def compare_output(loaded: dict, spec: dict, image_rt: list[int]) -> dict:
    """Compare the runtime engine's complete written output surface with the
    frozen capture. Returns counts and the first mismatch (if any)."""
    config = loaded['config']
    out_base = loaded['bo']['out_base']
    out_hw = loaded['bo']['out_hw']
    runtime_words = image_rt[out_base // 2: out_base // 2 + out_hw]
    device = loaded['device_file'].read_bytes()
    expected = loaded['expected_file'].read_bytes()
    tolerance = spec['expected_tolerance']
    report = {'output_boundary_halfwords': out_hw, 'mismatches': 0,
              'first_mismatch': None, 'compared': 'complete output BO',
              'written_region_bytes': 0,
              'runtime_written_region_sha256': None,
              'capture_written_region_sha256': None}
    if config['output_fp16']:
        if spec['family'] == 'conv-fp16' and not spec.get('bundle'):
            # The vendor captures' captured channel padding inside the written
            # atom is explicitly NOT a numerical oracle (docs/CONV_SPATIAL_3x3_
            # C4.md): the device BO carries arbitrary values in the padded OC
            # lanes while the engine contract writes zeros there. The repository
            # evidence is the defined NCHW values (expected.bin) plus the zero
            # padded lanes, so those are compared; the fixture integrity check
            # confirms the captured device BO carries the same defined values.
            atoms = config['total_atoms']
            out_c = config['output_channels']
            expected_words = struct.unpack(
                f'<{len(expected) // 2}H', expected)
            device_words = struct.unpack(f'<{len(device) // 2}H', device)
            integrity = 0
            rt_region: list[int] = []
            cap_region: list[int] = []
            for atom in range(atoms):
                for lane in range(8):
                    idx = atom * 8 + lane
                    got = runtime_words[idx]
                    if lane < out_c:
                        want = expected_words[lane * atoms + atom]
                        if idx < len(device_words) and \
                                device_words[idx] != want:
                            integrity += 1
                        if got != want:
                            report['mismatches'] += 1
                            report['first_mismatch'] = report['first_mismatch'] or (
                                'expected', idx, got, want)
                        rt_region.append(got)
                        cap_region.append(want)
                    else:
                        if got != 0:
                            report['mismatches'] += 1
                            report['first_mismatch'] = report['first_mismatch'] or (
                                'padding', idx, got, 0)
                        rt_region.append(got)
                        cap_region.append(0)
            rt_bytes = struct.pack(f'<{len(rt_region)}H', *rt_region)
            cap_bytes = struct.pack(f'<{len(cap_region)}H', *cap_region)
            report['written_region_bytes'] = len(rt_bytes)
            report['runtime_written_region_sha256'] = hashlib.sha256(
                rt_bytes).hexdigest()
            report['capture_written_region_sha256'] = hashlib.sha256(
                cap_bytes).hexdigest()
            report['fixture_device_defined_value_mismatches'] = integrity
        else:
            # conv-simple FP16 BOs are written end-to-end in capture order, and
            # the unpinned 1x1 bundle's written region is its flat_1x1 oracle.
            if spec['family'] == 'conv-simple' or spec.get('bundle'):
                device_words = struct.unpack(f'<{len(device) // 2}H', device)
                expected_words = struct.unpack(f'<{len(expected) // 2}H',
                                               expected)
                for idx in range(out_hw):
                    got = runtime_words[idx]
                    if idx < len(expected_words) and got != expected_words[idx]:
                        report['mismatches'] += 1
                        report['first_mismatch'] = report['first_mismatch'] or (
                            'expected', idx, got, expected_words[idx])
                    if idx < len(device_words) and got != device_words[idx]:
                        report['mismatches'] += 1
                        report['first_mismatch'] = report['first_mismatch'] or (
                            'device', idx, got, device_words[idx])
                rt_bytes = struct.pack(f'<{out_hw}H', *runtime_words)
                report['written_region_bytes'] = len(rt_bytes)
                report['runtime_written_region_sha256'] = hashlib.sha256(
                    rt_bytes).hexdigest()
                report['capture_written_region_sha256'] = hashlib.sha256(
                    expected).hexdigest()
    else:
        # FP32 capture: written surface is [c1][pixel][c2] 32-bit words; the
        # documented device/host bound is 0.001 absolute (last-bit divergence).
        device_words = struct.unpack(f'<{len(device) // 4}I', device)
        expected_words = struct.unpack(f'<{len(expected) // 4}I', expected)
        mismatches = 0
        worst = 0.0
        for idx in range(min(out_hw // 2, len(device_words))):
            got = struct.unpack('<f', struct.pack('<I', runtime_words[2 * idx] |
                                                  (runtime_words[2 * idx + 1]
                                                   << 16)))[0]
            want = struct.unpack('<f', struct.pack(
                '<I', expected_words[idx]))[0]
            dev = struct.unpack('<f', struct.pack('<I', device_words[idx]))[0]
            for label, target in (('expected', want), ('device', dev)):
                if abs(got - target) > tolerance:
                    mismatches += 1
                    report['first_mismatch'] = report['first_mismatch'] or (
                        label, idx, got, target)
                worst = max(worst, abs(got - target))
        report['mismatches'] = mismatches
        report['worst_abs_diff'] = worst
        report['tolerance'] = tolerance
        rt_bytes = struct.pack(f'<{out_hw}H', *runtime_words)
        report['written_region_bytes'] = len(rt_bytes)
        report['runtime_written_region_sha256'] = hashlib.sha256(
            rt_bytes).hexdigest()
        report['capture_written_region_sha256'] = hashlib.sha256(
            expected).hexdigest()
    return report


def canary_report(loaded: dict, image_rt: list[int], image_ref: list[int]) -> dict:
    # Untouched memory must still hold the harness canary. The operand BOs are
    # legitimately non-canary (the bench loads the captured bytes there) and
    # the output BO is covered by the written-region comparison, so both are
    # excluded from the canary check.
    out_base = loaded['bo']['out_base']
    out_hw = loaded['bo']['out_hw']
    in_base = loaded['bo']['in_base']
    in_hw = loaded['bo']['in_hw']
    w_base = loaded['bo']['w_base']
    w_hw = loaded['bo']['w_hw']
    excluded = out_hw + in_hw + w_hw
    bad_canary = 0
    for idx in range(len(image_rt)):
        if in_base // 2 <= idx < in_base // 2 + in_hw:
            continue
        if w_base // 2 <= idx < w_base // 2 + w_hw:
            continue
        if out_base // 2 <= idx < out_base // 2 + out_hw:
            continue
        canary = 0xa5a5 ^ ((idx * 17) & 0xffff)
        if image_rt[idx] != canary or image_ref[idx] != canary:
            bad_canary += 1
    return {'non_output_halfwords': len(image_rt) - excluded,
            'canary_mismatches': bad_canary}


def parse_status(path: Path) -> dict:
    status = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if '=' in line:
                key, _, value = line.partition('=')
                # Drives record one `RUN=<label>=<exit-code>` line each; keep
                # the label so callers can look up e.g. `RUN=mode-0`.
                if key == 'RUN' and '=' in value:
                    label, _, code = value.partition('=')
                    status['RUN=' + label] = code
                else:
                    status[key] = value
    return status


def run_case(simulator: str, case: str, keep_build: bool,
             leg: str = 'full') -> dict:
    spec = CASES[case]
    loaded = load_case(case)
    outdir = OUT_ROOT / case / f'{simulator}-{stamp()}'
    outdir.mkdir(parents=True, exist_ok=True)
    fixture_dir = outdir / 'fixture-hex'
    params = reference_params(case, loaded)
    fixture_hex(fixture_dir, loaded, spec, params['MEM_WORDS'])
    controls = negative_controls(case, loaded)
    paths = command_sources(loaded) + [MODEL, RUNNER,
                                       fixture_dir / 'commands.hex']
    hashes_before = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    report = {
        'status': 'RUNNING', 'started_utc': now(), 'case': case,
        'family': spec['family'], 'bundle_label': loaded['bundle_label'],
        'simulator': simulator,
        'python_version': platform.python_version(),
        'source_revision': subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
            capture_output=True, check=True).stdout.strip(),
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
        'leg': leg,
        'reference_core_params': params,
        'decoded_config': loaded['config'],
        'bo_placement': loaded['bo'],
        'fixture': {
            'command_sha256': hashlib.sha256(loaded['commands']).hexdigest(),
            'input_bytes': loaded['input_bytes'],
            'weight_bytes': loaded['weight_bytes'],
            'output_bytes': loaded['output_bytes'],
            'expected_sha256': sha(loaded['expected_file']),
            'device_sha256': sha(loaded['device_file']),
            'unpinned_bundle': bool(spec.get('bundle')),
        },
        'scope': (
            'adopted per-profile conv core vs runtime-decoded engine: same raw '
            'command QWORDs, same BOs; complete read/write sequence and full '
            'memory-image compare; written output BO bytes vs frozen capture. '
            'No full-top, FPGA or hardware execution.'),
        'runs': [], 'negative_controls': [],
        'source_hashes_before': hashes_before,
    }
    try:
        report['tool_version'] = tool_versions(simulator)
        batch = build_batch(simulator, outdir, params, fixture_dir,
                            loaded['bo'], controls, spec['family'], leg)
        result = subprocess.run(guarded(batch), cwd=ROOT, text=True,
                                capture_output=True, check=False, timeout=7200)
        (outdir / 'batch.log').write_text(result.stdout + result.stderr)
        status = parse_status(outdir / 'status.txt')
        compile_log = outdir / 'compile.log'
        compile_text = compile_log.read_text() if compile_log.exists() else ''
        if status.get('COMPILE', '1') != '0':
            raise RuntimeError(f'{simulator} compile failed: '
                               f'{compile_text[-6000:]}')
        if simulator == 'iverilog':
            if re.search(r'warning:', compile_text, re.I):
                raise RuntimeError('Icarus compile warned: '
                                   f'{compile_text[-6000:]}')
            sorry_lines = [line for line in compile_text.splitlines()
                           if 'sorry:' in line.lower()]
            disallowed = [line for line in sorry_lines
                          if not any(name in line
                                     for name in PRODUCTION_SORRY_ALLOWED)]
            if disallowed:
                raise RuntimeError('Icarus compile reported a non-production '
                                   f'"sorry:" limitation: {disallowed[:5]}')
            report['icarus_sorry_headers'] = len(sorry_lines)
            if sorry_lines:
                report['icarus_sorry_policy'] = (
                    'allowed only for the adopted conv-simple production '
                    'decoder always_comb sensitivity-list limitation '
                    '(same as the adopted conv-simple receipts); none from the '
                    'runtime engine or this harness')
        run_replay = leg in ('full', 'primary')
        run_controls = leg in ('full', 'controls')
        if run_replay:
            replay_log = outdir / 'mode-0.log'
            replay_text = replay_log.read_text() if replay_log.exists() else ''
            match = re.search(r'^PASS RUNTIME_EQUIV .*$', replay_text, re.M)
            fatal = re.search(r'^FATAL: .*$', replay_text, re.M)
            if not match:
                # Distinguish an explicit TB failure from an interrupted run
                # (guard kill / host loss produce no PASS and no FATAL line).
                if fatal:
                    raise RuntimeError('equivalence replay rejected: '
                                       f'{fatal.group(0)}')
                raise RuntimeError(
                    'equivalence replay produced no result (interrupted or '
                    f'guard-killed): status={status.get("RUN=mode-0")}')
            if status.get('RUN=mode-0', '1') != '0':
                raise RuntimeError('equivalence replay process exited nonzero: '
                                   f'{status.get("RUN=mode-0")}')
            report['runs'].append({'mode': 0, 'status': 'PASS',
                                   'result': match.group(0)})
        compare = None
        if run_replay:
            try:
                rt_image = read_dump(fixture_dir / 'mem_rt.hex')
                ref_image = read_dump(fixture_dir / 'mem_ref.hex')
            except FileNotFoundError as exc:
                raise RuntimeError(
                    'memory dumps missing (interrupted or benchmark did not '
                    f'reach the dump phase): {exc}')
            compare = compare_output(loaded, spec, rt_image)
            report['compare'] = {
                'complete_memory_image_equal': rt_image == ref_image,
                'written_output_vs_capture': compare,
                'canary': canary_report(loaded, rt_image, ref_image),
            }
            if not report['compare']['complete_memory_image_equal']:
                raise RuntimeError(
                    'runtime/reference complete memory images differ')
            if report['compare']['canary']['canary_mismatches'] != 0:
                raise RuntimeError(
                    'canary bytes were modified outside the output BO')
            if compare['mismatches'] != 0:
                raise RuntimeError('runtime output BO differs from the frozen '
                                   f'capture: {compare}')
            if compare['runtime_written_region_sha256'] != \
                    compare['capture_written_region_sha256']:
                raise RuntimeError(
                    'written-region hash differs from the capture')
        control_failures = []
        for control in (controls if run_controls else []):
            log = outdir / f'reject-{control["name"]}.log'
            text = log.read_text() if log.exists() else ''
            match = re.search(r'^PASS RUNTIME_REJECT mut=(\d+) index=(\d+) '
                              r'code=(\d+) reads=(\d+) writes=(\d+)',
                              text, re.M)
            fatal = re.search(r'code=(\d+) != expected (\d+)', text)
            entry = {'name': control['name'], 'status': 'FAIL',
                     'mutation_mode': control['mode'],
                     'mutation_index': control.get('index', 0),
                     'expected_code': control['code'],
                     'actual_code': int(match.group(3)) if match
                                    else (int(fatal.group(1)) if fatal
                                          else None)}
            if match and int(match.group(3)) == control['code']:
                entry['status'] = 'PASS'
            else:
                control_failures.append(entry['name'])
                debugs = [line for line in text.splitlines()
                          if line.startswith('DEBUG_')]
                entry['log_tail'] = '\n'.join(debugs[-2:] +
                                              text.splitlines()[-2:])
            report['negative_controls'].append(entry)
        report['negative_control_failures'] = control_failures
        if control_failures:
            raise RuntimeError(
                'negative controls failed: ' + ', '.join(control_failures))
        report.update(status='PASS', finished_utc=now())
    except Exception as exc:  # noqa: BLE001 - receipt must record any failure
        report.update(status='FAIL', finished_utc=now(), failure=str(exc))
    finally:
        hashes_after = {str(p.relative_to(ROOT)): sha(p) for p in paths
                        if p.exists()}
        report['source_hashes_after'] = hashes_after
        if hashes_after != hashes_before:
            report['status'] = 'FAIL'
            report['failure'] = (report.get('failure', '') +
                                 ' source hash changed during the run').strip()
        if not keep_build:
            for name in ('sim.vvp', 'obj_dir'):
                target = outdir / name
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
            report['build_products_pruned'] = True
        (outdir / 'report.json').write_text(
            json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report


def read_dump(path: Path) -> list[int]:
    return [int(line, 16) for line in path.read_text().splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator'),
                        default='iverilog')
    parser.add_argument('--case', action='append', default=None,
                        help='case name (repeatable); default: all')
    parser.add_argument('--keep-build', action='store_true')
    parser.add_argument('--leg', choices=('full', 'primary', 'controls'),
                        default='full',
                        help='full: replay+controls (default); primary: only '
                             'the equivalence replay (short leg); controls: '
                             'only the decoder fail-closed controls')
    args = parser.parse_args(argv)
    cases = args.case or list(CASES)
    unknown = [case for case in cases if case not in CASES]
    if unknown:
        print(f'unknown cases: {unknown}', file=sys.stderr)
        return 2
    failures = 0
    for case in cases:
        report = run_case(args.simulator, case, args.keep_build,
                          args.leg)
        if report['status'] != 'PASS':
            failures += 1
            print(f'FAIL {case}: {report.get("failure", "unknown")}',
                  file=sys.stderr)
            continue
        leg = report.get('leg', 'full')
        if report.get('compare'):
            compare = report['compare']['written_output_vs_capture']
            print(f'PASS {case} [{report.get("bundle_label") or "PINNED-FIXTURE"}] '
                  f'{report["simulator"]} leg={leg}: complete memory image equal, '
                  f'{compare.get("compared")} '
                  f'mismatches={compare.get("mismatches")}, '
                  f'negative_controls={len(report["negative_controls"])}')
        else:
            print(f'PASS {case} [{report.get("bundle_label") or "PINNED-FIXTURE"}] '
                  f'{report["simulator"]} leg={leg}: '
                  f'negative_controls={len(report["negative_controls"])} all explicit')
        for run in report['runs']:
            print(f'  {run["result"]}')
        for run in report['runs']:
            print(f'  {run["result"]}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
