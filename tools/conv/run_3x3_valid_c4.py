#!/usr/bin/env python3
"""Replay one captured FP16 valid 3x3 C4 task in Icarus and Verilator."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNNER = Path(__file__).resolve()
TB = ROOT / 'tests/conv/tb_conv_3x3_valid_c4.sv'
DONOR_RTL = ROOT / 'rtl/vendor/nvdla'
PASS_RE = re.compile(r'^PASS CONV_3X3_(VALID|STRIDE2|PAD1|GROUPED_C2|SPLITOC|DEPTHWISE)(?:_C4)? mode=(\d+) commands=(\d+) reads=(\d+) writes=(\d+) frames=(\d+)$')
CASES = {
    'conv_3x3_valid_c4_h9_w9_oc4': 'VALID',
    'conv_3x3_stride2_c4_h11_w11_oc4': 'STRIDE2',
    'conv_3x3_pad1_zero_frame_c4_h9_w9_oc4': 'PAD1',
    'conv_grouped_3x3_c4_h5_w5_oc8_g2_task0': 'GROUPED_C2',
    'conv_grouped_3x3_c4_h5_w5_oc8_g2_task1': 'GROUPED_C2',
    'conv_splitoc_3x3_c16_h9_w9_oc16_task0': 'SPLITOC',
    'conv_splitoc_3x3_c16_h9_w9_oc16_task1': 'SPLITOC',
    'conv_depthwise_3x3_c3_h11_w28_oc3': 'DEPTHWISE',
}
SOURCES = [
    'compat/nv_assert_never.v',
    'compat/nv_assert_no_x.v',
    'NV_DW_lsd.v',
    'NV_DW02_tree.v',
    'NV_NVDLA_CMAC_CORE_MAC_mul.v',
    'NV_NVDLA_CACC_CALC_fp_48b.v',
    'HLS_fp32_to_fp16.v',
]
RTL = [
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
    'rtl/cmac/rk_conv_3x3_valid_c4_profile.sv',
    'rtl/cmac/rk_conv_3x3_valid_c4_front.sv',
    'rtl/cmac/rk_frame_stage.sv',
    'rtl/cmac/rk_conv_3x3_valid_c4_core.sv',
    'rtl/cmac/rk_conv_3x3_stride2_c4_core.sv',
    'rtl/cmac/rk_conv_3x3_pad1_zero_frame_c4_core.sv',
    'rtl/cmac/rk_conv_3x3_grouped_c2_core.sv',
    'rtl/cmac/rk_conv_3x3_splitoc_c16_core.sv',
    'rtl/cmac/rk_conv_3x3_depthwise_c3_core.sv',
    'tests/conv/tb_conv_3x3_valid_c4.sv',
]
FIXTURE_FILES = (
    'a.bin', 'device_capture.json', 'device_out.bin', 'expected.bin', 'job.json',
    'manifest.json', 'provenance.json', 'regcmd.bin', 'source_input_nchw.bin',
    'source_weight_nchw.bin', 'w.bin',
)
ADDRESS_MAP = {'a': 0x1000, 'w': 0x2000, 'out': 0x3000}
FOUR_STATE_ONLY = {13, 14}


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def tool_version(argv: list[str]) -> str:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=30)
    text = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise RuntimeError(f'tool version command failed: {argv}: {text}')
    return text.splitlines()[0] if text else 'unknown'


def load_contract(case: str) -> tuple[dict, dict, bytes, bytes, Path]:
    if case not in CASES:
        raise ValueError(f'unknown strict convolution profile: {case}')
    fixture = ROOT / 'tests/conv/fixtures' / case
    manifest = json.loads((fixture / 'manifest.json').read_text())
    job = json.loads((fixture / 'job.json').read_text())
    capture = json.loads((fixture / 'device_capture.json').read_text())
    for name, record in manifest['files'].items():
        payload = (fixture / name).read_bytes()
        if len(payload) != record['bytes'] or sha_bytes(payload) != record['sha256']:
            raise ValueError(f'fixture hash/size mismatch: {name}')
    if manifest['case'] != case or capture['status'] != 'OK' or capture['submit_ret'] != 0:
        raise ValueError('capture identity or success status mismatch')
    if job['tasks'] != [{'regcmd_offset_words': 0, 'regcmd_words': 54}]:
        raise ValueError('candidate requires exactly one captured 54-QWORD task')
    if [patch['regcmd_index'] for patch in job['patches']] != [21, 27, 35]:
        raise ValueError('candidate requires the three documented DMA-address relocations')
    raw = (fixture / 'regcmd.bin').read_bytes()
    if len(raw) != 54 * 8:
        raise ValueError('raw command must contain exactly 54 QWORDs')
    # The capture's own relocation map is authoritative: depthwise mapped its
    # weight/output BOs at 0x3000/0x4000 rather than the sequential default.
    addresses = manifest['command']['addresses']
    patched = bytearray(raw)
    for patch in job['patches']:
        index = patch['regcmd_index']
        if patch['buffer'] not in addresses or patch['kind'] != 'value32':
            raise ValueError(f'unsupported relocation record: {patch}')
        qword, = struct.unpack_from('<Q', patched, index * 8)
        qword = (qword & ~(0xffffffff << 16)) | (addresses[patch['buffer']] << 16)
        struct.pack_into('<Q', patched, index * 8, qword)
    if sha_bytes(patched) != manifest['command']['captured_patched_sha256']:
        raise ValueError('relocated QWORD stream does not match captured command hash')
    if sha_bytes(patched) != capture['hashes']['command_stream']['sha256']:
        raise ValueError('relocated QWORD stream does not match device capture record')
    # The reproducible command, operands, output capture and provenance are
    # checked from the fixture itself. If the external donor checkout exists,
    # validate its pinned hash, but do not make portable simulation depend on it.
    source = Path(manifest['source']['example'])
    source_available = source.is_file()
    if source_available and sha(source) != manifest['source']['sha256']:
        raise ValueError('available pinned donor source differs from provenance')
    return manifest, job, raw, bytes(patched), fixture


def fixture_hex(directory: Path, patched: bytes, fixture: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for source, target in (
        ('a.bin', 'input.hex'),
        ('w.bin', 'weight.hex'),
        ('expected.bin', 'expected.hex'),
        ('device_out.bin', 'device.hex'),
    ):
        payload = (fixture / source).read_bytes()
        if len(payload) % 2:
            raise ValueError(f'{source} is not a whole number of halfwords')
        words = struct.unpack(f'<{len(payload)//2}H', payload)
        (directory / target).write_text(''.join(f'{word:04x}\n' for word in words))
    qwords = struct.unpack('<54Q', patched)
    (directory / 'commands.hex').write_text(''.join(f'{word:016x}\n' for word in qwords))


def traffic_contract(manifest: dict) -> tuple[int, int, int, int]:
    """Derive operand counts from the fixture's own layout declarations.

    Weight BO bytes and real input channels come from the packed layout, so a
    C2/K4, C4/K4 or C16/K8 task reports its own counts instead of the C4
    numbers.
    """
    shape = manifest['shape']
    execution = manifest.get('execution_geometry', shape)
    input_pixels = execution['input_height'] * execution['input_width']
    input_channels = shape['input_channels']
    weight_halfwords = manifest['layout']['weight_bytes'] // 2
    output_pixels = shape['output_height'] * shape['output_width']
    return weight_halfwords, input_channels, input_pixels, output_pixels


def source_paths(fixture: Path) -> list[Path]:
    return ([DONOR_RTL / name for name in SOURCES] +
            [ROOT / name for name in RTL] +
            [RUNNER, TB] + [fixture / name for name in FIXTURE_FILES])


def run_one(simulator: str, stamp: str, keep_build: bool,
            case: str, manifest: dict, patched: bytes, fixture: Path) -> Path:
    profile = CASES[case]
    addresses = manifest['command']['addresses']
    shape = manifest['shape']
    execution = manifest.get('execution_geometry', shape)
    input_pixels = execution['input_height'] * execution['input_width']
    output_pixels = shape['output_height'] * shape['output_width']
    weight_halfwords, input_channels, input_pixels, output_pixels = \
        traffic_contract(manifest)
    total_reads = weight_halfwords + input_pixels * input_channels
    total_writes = output_pixels * 8
    total_frames = output_pixels * 9
    stride2 = profile == 'STRIDE2'
    pad1 = profile == 'PAD1'
    grouped = profile == 'GROUPED_C2'
    splitoc = profile == 'SPLITOC'
    depthwise = profile == 'DEPTHWISE'
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    outdir_name = ('convolution-3x3-depthwise-c3' if depthwise else
                   'convolution-3x3-splitoc-c16' if splitoc else
                   'convolution-3x3-grouped-c2' if grouped else
                   'convolution-3x3-pad1-zero-frame-c4' if pad1 else
                   'convolution-3x3-stride2-c4' if stride2 else
                   'convolution-3x3-valid-c4')
    outdir = ROOT / 'build' / outdir_name / f'{simulator}-{stamp}'
    outdir.mkdir(parents=True, exist_ok=False)
    fixture_dir = outdir / 'fixture-hex'
    fixture_hex(fixture_dir, patched, fixture)
    paths = source_paths(fixture)
    hashes_before = {str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path): sha(path)
                     for path in paths}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                              text=True, capture_output=True, check=True).stdout.strip()
    git_status = subprocess.run(['git', 'status', '--short', '--untracked-files=all'],
                                cwd=ROOT, text=True, capture_output=True,
                                check=True).stdout.splitlines()
    report = {
        'status': 'RUNNING', 'started_utc': now(), 'case': case,
        'simulator': simulator, 'tool_version': tool_version(
            [compiler, '--version'] if simulator == 'verilator' else [compiler, '-V']),
        'runtime_version': tool_version([runtime, '-V']) if runtime else None,
        'python_version': platform.python_version(), 'source_revision': revision,
        'source_worktree_status': git_status,
        'scope': f"Captured FP16 valid 3x3 C4 {shape['input_height']}x{shape['input_width']} -> OC4 {shape['output_height']}x{shape['output_width']} stride {shape['stride'][0]}; exact raw 54-QWORD stream, three relocations; no DMA-descriptor/full-top/FPGA execution.",
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
        'seed': '0x3c4c9a31', 'seed_policy': 'fixed memory-handshake LCG in the SystemVerilog testbench',
        'donor_source_file_available': Path(manifest['source']['example']).is_file(),
        'fixture': {'template_command_sha256': sha(fixture / 'regcmd.bin'),
                    'captured_patched_command_sha256': sha_bytes(patched),
                    'device_output_bo_sha256': manifest['numeric']['device_output_bo_sha256'],
                    'logical_expected_sha256': manifest['numeric']['device_defined_output_sha256'],
                    'addresses': addresses, 'qwords': 54,
                    'relocations': [21, 27, 35]},
        'contract': {'input_bytes': (fixture / 'a.bin').stat().st_size,
                     'input_reads_halfwords': input_pixels * input_channels,
                     'weight_bytes': weight_halfwords * 2,
                     'weight_reads_halfwords': weight_halfwords,
                     'output_bo_bytes': (fixture / 'device_out.bin').stat().st_size,
                     'logical_output_bytes': (fixture / 'expected.bin').stat().st_size,
                     'output_writes_halfwords': total_writes,
                     'spatial_frames': total_frames,
                     'input_fetch_policy': (
                         f'read the {input_channels} real lanes of each packed C1 '
                         'plane at 16-byte pixel stride; verify source layout in '
                         'the fixture contract test'),
                     'whole_bo_padding_policy': 'simulation checks every unwritten halfword against a canary; captured padding is not a numerical oracle'},
        'negative_controls': {
            'fixed_register': {'mode': 1, 'code': 2},
            'unknown_target': {'mode': 2, 'code': 1},
            'early_task_boundary': {'mode': 3, 'code': 3},
            'terminal_tail_mutation': {'mode': 4, 'code': 3},
            'unaligned_input': {'mode': 5, 'code': 4},
            'overlapping_buffers': {'mode': 6, 'code': 4},
            'input_range_overflow': {'mode': 7, 'code': 4},
            'read_bus_error': {'mode': 8, 'code': 5},
            'read_timeout': {'mode': 9, 'code': 8},
            'write_bus_error': {'mode': 10, 'code': 5},
            'write_timeout': {'mode': 11, 'code': 8},
            'extra_qword': {'mode': 12, 'code': 7},
            'four_state_unknown_address': {'mode': 13, 'code': 4},
            'four_state_high_impedance_address': {'mode': 14, 'code': 4},
            'output_range_overflow': {'mode': 15, 'code': 4},
        },
        'source_hashes_before': hashes_before, 'runs': [],
    }
    build: Path | None = None
    try:
        donor_sources = [str(DONOR_RTL / name) for name in SOURCES]
        rtl_sources = [str(ROOT / name) for name in RTL]
        profile_flags = (['-DCONV_STRIDE2'] if stride2 else
                         ['-DCONV_PAD1'] if pad1 else
                         ['-DCONV_GROUPED'] if grouped else
                         ['-DCONV_SPLITOC'] if splitoc else
                         ['-DCONV_DEPTHWISE'] if depthwise else [])
        if simulator == 'iverilog':
            build = outdir / 'sim.vvp'
            parameter_flag = ['-Ptb_conv_3x3_valid_c4.STRIDE2=1'] if stride2 else []
            if pad1:
                parameter_flag = ['-Ptb_conv_3x3_valid_c4.PAD1=1']
            if grouped:
                parameter_flag = ['-Ptb_conv_3x3_valid_c4.GROUPED_C2=1']
            if splitoc:
                parameter_flag = ['-Ptb_conv_3x3_valid_c4.SPLIT_OC=1']
            if depthwise:
                parameter_flag = ['-Ptb_conv_3x3_valid_c4.DEPTHWISE=1']
            command = [compiler, '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                       *profile_flags, *parameter_flag,
                       f'-I{DONOR_RTL}', '-s', 'tb_conv_3x3_valid_c4',
                       '-o', str(build), *donor_sources, *rtl_sources]
            compile_result = subprocess.run(command, cwd=ROOT, text=True,
                                            capture_output=True, check=False, timeout=300)
            (outdir / 'compile.log').write_text(compile_result.stdout + compile_result.stderr)
            if compile_result.returncode or re.search(r'warning:|sorry:',
                                                       compile_result.stdout + compile_result.stderr, re.I):
                raise RuntimeError(f'Icarus compile failed/warned: {(compile_result.stdout + compile_result.stderr)[-5000:]}')
            prefix = [runtime, str(build)]
            report['runtime_version'] = tool_version([runtime, '-V'])
        else:
            build = outdir / 'obj_dir'
            command = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                       '-j', '2', '--timescale-override', '1ns/1ps',
                       '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', *profile_flags,
                       *(['-GSTRIDE2=1'] if stride2 else
                         ['-GPAD1=1'] if pad1 else
                         ['-GGROUPED_C2=1'] if grouped else
                         ['-GSPLIT_OC=1'] if splitoc else
                         ['-GDEPTHWISE=1'] if depthwise else []), f'-I{DONOR_RTL}',
                       '--top-module', 'tb_conv_3x3_valid_c4', '--Mdir', str(build),
                       '-o', 'sim', *donor_sources, *rtl_sources]
            compile_result = subprocess.run(command, cwd=ROOT, text=True,
                                            capture_output=True, check=False, timeout=600)
            compile_text = compile_result.stdout + compile_result.stderr
            (outdir / 'compile.log').write_text(compile_text)
            if compile_result.returncode:
                raise RuntimeError(f'Verilator compile failed: {compile_text[-5000:]}')
            report['compile_warning_headers'] = sum(
                line.startswith('%Warning-') for line in compile_text.splitlines())
            prefix = [str(build / 'sim')]

        for mode in range(16):
            if simulator == 'verilator' and mode in FOUR_STATE_ONLY:
                report['runs'].append({'mode': mode, 'status': 'SKIP',
                                       'reason': 'Verilator is a two-state simulator'})
                continue
            result = subprocess.run(prefix + [f'+FIXTURE={fixture_dir}', f'+MODE={mode}'],
                                    cwd=ROOT, text=True, capture_output=True,
                                    # The streaming weight feed assembles a
                                    # frame over KERNELS*INPUT_CHANNELS cycles;
                                    # a C16 page is 128x slower than the former
                                    # combinational mux. This cap is wall clock,
                                    # not a correctness signal.
                                    check=False, timeout=2400)
            output = result.stdout + result.stderr
            (outdir / f'mode-{mode}.log').write_text(output)
            matches = [PASS_RE.fullmatch(line) for line in output.splitlines()
                       if line.startswith('PASS CONV_3X3_')]
            if (result.returncode or len(matches) != 1 or
                    matches[0].group(1) != profile or int(matches[0].group(2)) != mode):
                raise RuntimeError(f'mode {mode} failed: {output[-4000:]}')
            details = tuple(int(matches[0].group(index)) for index in range(3, 7))
            if mode in (0, 12) and details != (
                    55 if mode == 12 else 54, total_reads, total_writes, total_frames):
                raise RuntimeError(f'mode {mode} successful traffic differs: {details}')
            report['runs'].append({'mode': mode, 'result': output.strip(),
                                   'status': 'PASS'})
        hashes_after = {str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path): sha(path)
                        for path in paths}
        if hashes_before != hashes_after:
            raise RuntimeError('RTL, fixture or runner changed during the run')
        report.update(status='PASS', finished_utc=now(), source_hashes_after=hashes_after,
                       summary={'raw_qwords': 54, 'relocations': [21, 27, 35],
                                'memory_reads': total_reads, 'output_writes': total_writes,
                                'spatial_frames': total_frames,
                               'negative_controls': 15,
                               'hardware_accessed': False})
    except Exception as exc:
        report.update(status='FAIL', finished_utc=now(), failure=str(exc))
        raise
    finally:
        if not keep_build and build is not None:
            if build.is_dir():
                shutil.rmtree(build)
            else:
                build.unlink(missing_ok=True)
            report['build_products_pruned'] = True
        (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return outdir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'), default='both')
    parser.add_argument('--case', choices=tuple(CASES),
                        default='conv_3x3_valid_c4_h9_w9_oc4')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    try:
        manifest, _job, _raw, patched, fixture = load_contract(args.case)
    except Exception as exc:
        print(f'CONTRACT FAIL: {exc}', file=sys.stderr)
        return 1
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    try:
        for simulator in simulators:
            outdir = run_one(simulator, stamp, args.keep_build, args.case,
                             manifest, patched, fixture)
            weight_halfwords, input_channels, input_pixels, pixels = \
                traffic_contract(manifest)
            reads = weight_halfwords + input_pixels * input_channels
            print(f'PASS captured {args.case} {simulator}: 54 raw QWORDs, '
                  f'{reads} reads, {pixels * 8} writes, {pixels * 9} spatial frames, '
                  f'15 negative controls; '
                  f'report={outdir / "report.json"}')
    except Exception as exc:
        print(f'FAIL captured {args.case}: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
