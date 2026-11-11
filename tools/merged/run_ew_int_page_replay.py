#!/usr/bin/env python3
"""Page-level offline replay for the Image-B ew-int page form (task-23).

Instantiates the real page wrapper (`rk_ew_int_page_axi`) and sparse aperture
(`rk_ew_int_aperture`) in `tests/tb_ew_int_page.sv`, stages the frozen ew-int
BO images through the aperture AXI4-Lite staging port, submits the raw captured
command BO through the frozen `rk_job_control` page ABI, reads the output BO
back through the same port and compares it under `expected.mask.bin`.

Also checks:
  * staging byte order and no engine rewrites of a/b or the command BO
    (full readback comparison);
  * reset-per-job (two clean jobs back-to-back in one reset session);
  * fail-closed page behaviour: unsupported op/dtype, unknown register, wrong
    amount, unaligned START_ADDRESS, aperture-hole operand (memory bus error),
    incomplete fields (missing JOB_TAG) and partial write strobes are refused,
    and a failed job is sticky until fabric reset.

No policy violations: offline only, no Vivado, no hardware, no heavy jobs.
Receipts are source-hash-bound under build/ew-int-page/<stamp>/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from model.int_profile import decode_regcmd, patch_value32  # noqa: E402
from model.int_sim import IntMemory, IntEmulator, masked_compare  # noqa: E402
from tools.merged import ew_int_aperture_audit as audit  # noqa: E402

CAPTURES = ROOT / 'build/rk3588-example-captures/ew-int'
MANIFEST = CAPTURES / 'manifest.json'
A_BANK = 0x1100_1000
B_BANK = 0x1100_2000
D_BANK = 0x1100_3000
C_BANK = 0x1100_4000
BO_BYTES = 4096
PATCHES = (((0x1001, 0x4020), D_BANK), ((0x2001, 0x5018), A_BANK),
           ((0x2001, 0x5038), B_BANK))
RTL = ['rtl/rk_ew_int_page_axi.sv', 'rtl/rk_ew_int_aperture.sv',
       'rtl/rk_ew_int_regs.sv', 'rtl/rk_ew_int_engine.sv',
       'rtl/rk_int_alu.sv', 'rtl/rk_job_control.sv',
       'rtl/rk_axil_mem_bridge.sv', 'rtl/rk_bram.sv']
TB = 'tests/tb_ew_int_page.sv'
TOOL = 'tools/merged/run_ew_int_page_replay.py'
EVIDENCE = RTL + [TB, TOOL, 'tools/merged/ew_int_aperture_audit.py',
                  'docs/EW_INT_APERTURE_AUDIT.md',
                  'docs/EW_INT.md',
                  'build/rk3588-example-captures/ew-int/manifest.json']
SCOPE = ('Offline page-form RTL replay only. Not Vivado, timing closure, '
         'bitstream, Image-B build or hardware/silicon validation.')


def utc() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha(Path(path).read_bytes())


def tool_version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        text = (result.stdout or '') + (result.stderr or '')
        return text.strip().splitlines()[0] if text.strip() else 'unknown'
    except Exception as error:  # pragma: no cover - diagnostic only
        return f'unavailable: {error}'


def run(command: list[str], log: Path, timeout: int = 900) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('wb') as stream:
        stream.write(('$ ' + ' '.join(command) + '\n').encode())
        stream.flush()
        result = subprocess.run(command, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout)
    return result.returncode


def strict_warnings(log: Path) -> list[str]:
    text = log.read_text(errors='replace')
    return [line for line in text.splitlines()
            if line.startswith('%Warning') or 'warning:' in line.lower()]


# ---------------------------------------------------------------------------
# Stimulus / comparison helpers
# ---------------------------------------------------------------------------
def words_from_bytes(data: bytes) -> list[int]:
    padded = data + bytes((-len(data)) % 4)
    return [int.from_bytes(padded[i:i + 4], 'little') for i in range(0, len(padded), 4)]


def bytes_from_words(words: list[int]) -> bytes:
    return b''.join(int(word & 0xFFFFFFFF).to_bytes(4, 'little') for word in words)


def words_hex(words: list[int]) -> str:
    return '\n'.join(f'{word & 0xFFFFFFFF:08x}' for word in words) + '\n'


def parse_word_hex(text: str) -> tuple[bytes, int]:
    """Parse 32-bit hex words; X/Z nibbles become 0 (they can only occur in
    unstaged/unasserted bytes, which the mask comparison ignores)."""
    data = bytearray()
    unknowns = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if any(ch in 'xXzZ' for ch in line):
            unknowns += 1
            line = ''.join('0' if ch in 'xXzZ' else ch for ch in line)
        data += int(line, 16).to_bytes(4, 'little')
    return bytes(data), unknowns


def patched_stream(entry: dict) -> bytes:
    raw = (CAPTURES / entry['bundle_dir'] / 'regcmd.bin').read_bytes()
    for (target, offset), address in PATCHES:
        raw = patch_value32(raw, target, offset, address)
    return raw


def words_of(raw: bytes) -> list[int]:
    return [int.from_bytes(raw[i:i + 8], 'little') for i in range(0, len(raw), 8)]


def pack_words(words: list[int]) -> bytes:
    return b''.join(int(word).to_bytes(8, 'little') for word in words)


def write_stim(directory: Path, entry: dict, stream: bytes, tag: str) -> dict:
    bundle = CAPTURES / entry['bundle_dir']
    a_bytes = (bundle / 'a.bin').read_bytes()
    b_bytes = (bundle / 'b.bin').read_bytes()
    (directory / f'{tag}_a_words.hex').write_text(words_hex(words_from_bytes(a_bytes)))
    (directory / f'{tag}_b_words.hex').write_text(words_hex(words_from_bytes(b_bytes)))
    # Pad the command hex image to the TB's 88-word array so $readmemh fills the
    # whole array (no simulator warning); the staged command bytes are unchanged.
    cmd_words = words_from_bytes(stream)
    cmd_words += [0] * (88 - len(cmd_words))
    (directory / f'{tag}_cmd_words.hex').write_text(words_hex(cmd_words))
    return {
        'entry': entry,
        'stim': str(directory / f'{tag}_'),
        'cmd_words': len(stream) // 8,
        'patched_stream': stream,
        'a_bytes_sha256': sha(a_bytes),
        'b_bytes_sha256': sha(b_bytes),
        'stream_sha256': sha(stream),
    }


def compare_case(entry: dict, prefix: Path) -> dict:
    bundle = CAPTURES / entry['bundle_dir']
    out_bytes, out_unknown = parse_word_hex(Path(str(prefix) + 'out.hex').read_text())
    expected = (bundle / 'expected.bin').read_bytes()
    mask = (bundle / 'expected.mask.bin').read_bytes()
    comparison = masked_compare(out_bytes[:BO_BYTES], expected, mask)
    a_read, a_unknown = parse_word_hex(Path(str(prefix) + 'a_read.hex').read_text())
    b_read, b_unknown = parse_word_hex(Path(str(prefix) + 'b_read.hex').read_text())
    cmd_read, cmd_unknown = parse_word_hex(Path(str(prefix) + 'cmd_read.hex').read_text())
    return {
        'masked_comparison': comparison,
        'out_unknown_words': out_unknown,
        'input_a_bytes_exact': a_read[:BO_BYTES] == (bundle / 'a.bin').read_bytes(),
        'input_b_bytes_exact': b_read[:BO_BYTES] == (bundle / 'b.bin').read_bytes(),
        'input_unknown_words': a_unknown + b_unknown,
        'command_bo_untouched': None,   # filled by caller (needs the staged stream)
        'cmd_unknown_words': cmd_unknown,
        'actual_out_sha256': sha(out_bytes[:BO_BYTES]),
        'expected_sha256': sha(expected),
        'mask_sha256': sha(mask),
    }


# ---------------------------------------------------------------------------
# Negative controls (stream mutations applied AFTER page-form address patches)
# ---------------------------------------------------------------------------
def find_word(words: list[int], target: int, offset: int) -> int:
    matches = [i for i, word in enumerate(words)
               if (word >> 48) == target and (word & 0xFFFF) == offset]
    if len(matches) != 1:
        raise SystemExit(f'expected one {target:#06x}:{offset:#06x} write, '
                         f'found {len(matches)}')
    return matches[0]


def set_value(words: list[int], target: int, offset: int, value: int) -> list[int]:
    result = list(words)
    index = find_word(result, target, offset)
    result[index] = (result[index] & 0xFFFF_0000_0000_FFFF) | ((value & 0xFFFFFFFF) << 16)
    return result


def negative_controls(entries: dict) -> list[dict]:
    simple = entries['int8_add_c8_w1']
    simple_words = words_of(patched_stream(simple))
    controls = []

    def add(name, words, ecode, note, amount=None, plusargs=None, refusal=False,
            compare_output=False):
        controls.append({
            'name': name,
            'entry': simple,
            'stream': pack_words(words),
            'cmd_words': len(words),
            'amount': amount if amount is not None else len(words),
            'ecode': ecode,
            'note': note,
            'plusargs': plusargs or [],
            'refusal': refusal,
            'compare_output': compare_output,
        })

    add('nc_unsupported_op_div',
        set_value(simple_words, 0x1001, 0x4070, 0x104302C0), 2,
        'EW_CFG selects DIV (not an evidenced integer op) -> E2')
    add('nc_fp16_dtype',
        set_value(simple_words, 0x1001, 0x4010, 0x48000002), 2,
        'DATA_FORMAT FP16 is not an evidenced integer dtype -> E2')
    hole = list(simple_words)
    hole_index = find_word(hole, 0x2001, 0x5018)
    hole[hole_index] = ((hole[hole_index] & 0xFFFF_0000_0000_0000) |
                        (0x1100_0000 << 16) | (hole[hole_index] & 0xFFFF))
    add('nc_hole_operand', hole, 5,
        'operand a in an aperture hole -> engine memory bus error E5', compare_output=False)
    unknown = list(simple_words)
    unknown_index = find_word(unknown, 0x2001, 0x5018)
    unknown[unknown_index] = (unknown[unknown_index] & 0xFFFF_FFFF_0000_0000) | 0x00FE
    add('nc_unknown_register', unknown, 1,
        'RDMA.SRC_BASE_ADDR retargeted to an unknown offset -> E1')
    add('nc_wrong_amount', simple_words.copy(), 6,
        'START_AMOUNT=17 is not a captured shape -> E6', amount=17)
    add('nc_unaligned_start', simple_words.copy(), 6,
        'START_ADDRESS is not 8-byte aligned -> E6',
        plusargs=['+START_ADDR=%d' % (C_BANK + 4)])
    add('nc_missing_tag', simple_words.copy(), 0,
        'JOB_TAG never written -> submit refused with SLVERR',
        plusargs=['+SKIP_TAG=1'], refusal=True)
    add('nc_bad_strobe', simple_words.copy(), 0,
        'partial write strobe on START_AMOUNT -> SLVERR and no submit',
        plusargs=['+BAD_STROBE=1'], refusal=True)
    return controls


# ---------------------------------------------------------------------------
# Simulator drivers
# ---------------------------------------------------------------------------
def build(simulator: str, work: Path) -> list[str]:
    sources = [str(ROOT / name) for name in RTL + [TB]]
    if simulator == 'verilator':
        obj = work / 'obj_tb_ew_int_page'
        command = ['verilator', '--binary', '--timing', '--assert', '-Wall',
                   '-Wno-SYNCASYNCNET', '-Wno-PINCONNECTEMPTY',
                   '-j', '2', '--top-module', 'tb_ew_int_page',
                   '--Mdir', str(obj), '-o', 'sim'] + sources
        log = work / 'verilator_build.log'
        code = run(command, log)
        if code or strict_warnings(log):
            raise SystemExit(f'verilator build failed/warned; see {log}')
        return [str(obj / 'sim')]
    binary = work / 'tb_ew_int_page.vvp'
    command = ['iverilog', '-g2012', '-o', str(binary)] + sources
    log = work / 'iverilog_build.log'
    code = run(command, log)
    if code or strict_warnings(log):
        raise SystemExit(f'iverilog build failed/warned; see {log}')
    return ['vvp', str(binary)]


def execute(launch: list[str], work: Path, tag: str, plusargs: list[str],
            timeout: int = 600) -> tuple[int, list[str]]:
    command = list(launch) + plusargs
    log = work / 'logs' / f'{tag}.log'
    code = run(command, log, timeout=timeout)
    return code, strict_warnings(log)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('both', 'verilator', 'iverilog'),
                        default='both')
    parser.add_argument('--stamp', default=None)
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    ready = [entry for entry in manifest['cases'] if entry['status'] == 'READY']
    blocked = [entry for entry in manifest['cases'] if entry['status'] != 'READY']
    entries = {entry['case']: entry for entry in ready}
    if len(ready) != 15 or len(blocked) != 3:
        raise SystemExit('unexpected capture family counts')

    stamp = args.stamp or time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    work = ROOT / 'build/ew-int-page' / stamp
    if work.exists():
        raise SystemExit(f'receipt directory already exists: {work}')
    stim_dir = work / 'stimulus'
    stim_dir.mkdir(parents=True)

    aperture_audit = audit.run()
    if aperture_audit['verdict'] != 'PASS':
        raise SystemExit('aperture audit is not PASS; refusing page replay')
    if (aperture_audit['aperture']['physical_bytes'] != 16384 or
            aperture_audit['banks'][0]['address'] != A_BANK or
            aperture_audit['banks'][1]['address'] != B_BANK or
            aperture_audit['banks'][2]['address'] != D_BANK or
            aperture_audit['banks'][3]['address'] != C_BANK):
        raise SystemExit('aperture audit bank map does not match this replay')

    report = {
        'schema': 1,
        'status': 'RUNNING',
        'scope': SCOPE,
        'started_utc': utc(),
        'stamp': stamp,
        'execution_root': str(ROOT),
        'capture_manifest_sha256': sha_file(MANIFEST),
        'aperture_audit': {
            'verdict': aperture_audit['verdict'],
            'banks': aperture_audit['banks'],
            'holes': aperture_audit['holes'],
            'union_span': aperture_audit['union_span'],
            'physical_bytes': aperture_audit['aperture']['physical_bytes'],
            'decoded_bytes': aperture_audit['aperture']['decoded_bytes'],
        },
        'source_hashes': {name: sha_file(ROOT / name) for name in EVIDENCE},
        'bundle_hashes': {entry['case']: entry['hashes'] for entry in ready},
        'cases': {},
        'back_to_back': {},
        'negative_controls': {},
        'blocked_cases': [{'case': entry['case'],
                           'blocked_reason': entry.get('blocked_reason')}
                          for entry in blocked],
        'simulators': {},
        'notes': [
            'Page form uses the frozen rk_job_control ABI with DEVICE_ID RKEI.',
            'Command BO lives in aperture bank C at 0x1100_4000; START_AMOUNT is '
            'fail-closed to the three captured shapes {18,31,44}.',
            'Error status is sticky until fabric reset (frozen rk_job_control '
            'contract); engine/decoder state is reset per job.',
            'X/uninitialized bytes may appear only in unstaged/unasserted BRAM '
            'locations; the mask comparison ignores them and the readback files '
            'are retained for audit.',
        ],
    }

    def save() -> None:
        (work / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    save()
    print(f'[ew-int-page] receipts: {work}')
    failures: list[str] = []

    # stimulus for all 15 READY cases
    case_stim = {}
    for entry in ready:
        stream = patched_stream(entry)
        case_stim[entry['case']] = write_stim(stim_dir, entry, stream, entry['case'])
        config = decode_regcmd(stream)[0]
        report['cases'][entry['case']] = {
            'status': 'STIMULUS_READY',
            'mode': config.mode, 'op': config.op, 'dtype': config.dtype,
            'out_dtype': config.out_dtype, 'count': config.count,
            'cmd_words': len(stream) // 8,
            'stream_sha256': sha(stream),
            'a_sha256': case_stim[entry['case']]['a_bytes_sha256'],
            'b_sha256': case_stim[entry['case']]['b_bytes_sha256'],
        }
    back_to_back_first = 'int8_add_c8_w1'
    back_to_back_second = 'int16_minus_c8_w1'
    controls = negative_controls(entries)
    for control in controls:
        control['stimulatory'] = write_stim(stim_dir, control['entry'],
                                            control['stream'], control['name'])
    save()

    simulators = ['verilator', 'iverilog'] if args.simulator == 'both' \
        else [args.simulator]
    versions = {'verilator': tool_version(['verilator', '--version']),
                'iverilog': tool_version(['iverilog', '-V'])}
    report['tool_versions'] = versions
    for simulator in simulators:
        if shutil.which(simulator) is None:
            failures.append(f'{simulator} unavailable')
            report['simulators'][simulator] = {'status': 'UNAVAILABLE'}
            continue
        print(f'[ew-int-page] {simulator}: building page bench')
        report['simulators'][simulator] = {'status': 'RUNNING',
                                           'version': versions[simulator],
                                           'cases': {},
                                           'negative_controls': {},
                                           'back_to_back': {}}
        launch = build(simulator, work)
        out_dir = work / 'out' / simulator
        out_dir.mkdir(parents=True, exist_ok=True)

        for entry in ready:
            name = entry['case']
            plusargs = [
                f'+STIM={case_stim[name]["stim"]}',
                f'+CMD_WORDS={case_stim[name]["cmd_words"]}',
                f'+AMOUNT={case_stim[name]["cmd_words"]}',
                f'+NAME={name}',
                f'+OUT={out_dir / (name + "_")}',
            ]
            code, warnings = execute(launch, work, f'{simulator}_{name}', plusargs)
            record = {'status': 'FAIL'}
            if code or warnings:
                failures.append(f'{simulator} page replay {name}')
                record['warnings'] = warnings
            else:
                comparison = compare_case(entry, out_dir / f'{name}_')
                cmd_read, cmd_unknown = parse_word_hex(
                    (out_dir / f'{name}_cmd_read.hex').read_text())
                command_untouched = (
                    cmd_read[:len(case_stim[name]['patched_stream'])] ==
                    case_stim[name]['patched_stream'])
                record = {
                    'status': 'PASS' if (
                        comparison['masked_comparison']['exact'] and
                        comparison['input_a_bytes_exact'] and
                        comparison['input_b_bytes_exact'] and
                        command_untouched) else 'FAIL',
                    'asserted_bytes': comparison['masked_comparison']['asserted_bytes'],
                    'mismatch_count': comparison['masked_comparison']['mismatch_count'],
                    'actual_out_sha256': comparison['actual_out_sha256'],
                    'expected_sha256': comparison['expected_sha256'],
                    'mask_sha256': comparison['mask_sha256'],
                    'input_a_bytes_exact': comparison['input_a_bytes_exact'],
                    'input_b_bytes_exact': comparison['input_b_bytes_exact'],
                    'command_bo_untouched': command_untouched,
                    'unknown_words': comparison['out_unknown_words'] +
                                     comparison['input_unknown_words'] +
                                     comparison['cmd_unknown_words'],
                    'cmd_words': case_stim[name]['cmd_words'],
                    'cmd_sha256': case_stim[name]['stream_sha256'],
                }
            record['log'] = f'logs/{simulator}_{name}.log'
            record['log_sha256'] = sha_file(work / 'logs' / f'{simulator}_{name}.log')
            report['simulators'][simulator]['cases'][name] = record
            report['cases'][name]['status'] = record['status']
            if record['status'] != 'PASS':
                failures.append(f'{simulator} page compare {name}')
        save()

        # reset-per-job: two clean jobs in one reset session
        first = case_stim[back_to_back_first]
        second = case_stim[back_to_back_second]
        code, warnings = execute(
            launch, work, f'{simulator}_back_to_back', [
                f'+STIM={first["stim"]}', f'+CMD_WORDS={first["cmd_words"]}',
                f'+NAME={back_to_back_first}',
                f'+OUT={out_dir / "b2b_first_"}',
                f'+STIM2={second["stim"]}', f'+CMD_WORDS2={second["cmd_words"]}',
                f'+NAME2={back_to_back_second}',
                f'+OUT2={out_dir / "b2b_second_"}',
            ])
        b2b = {'status': 'FAIL'}
        if not code and not warnings:
            first_cmp = compare_case(entries[back_to_back_first],
                                    out_dir / 'b2b_first_')
            second_cmp = masked_compare(
                parse_word_hex((out_dir / 'b2b_second_out.hex').read_text())[0][:BO_BYTES],
                (CAPTURES / entries[back_to_back_second]['bundle_dir'] /
                 'expected.bin').read_bytes(),
                (CAPTURES / entries[back_to_back_second]['bundle_dir'] /
                 'expected.mask.bin').read_bytes())
            b2b = {
                'status': 'PASS' if (first_cmp['masked_comparison']['exact'] and
                                     second_cmp['exact']) else 'FAIL',
                'first_case': back_to_back_first,
                'second_case': back_to_back_second,
                'first_asserted_bytes': first_cmp['masked_comparison']['asserted_bytes'],
                'second_asserted_bytes': second_cmp['asserted_bytes'],
                'first_mismatch_count': first_cmp['masked_comparison']['mismatch_count'],
                'second_mismatch_count': second_cmp['mismatch_count'],
                'note': 'two clean jobs, one reset session (reset-per-job)',
            }
        b2b['log'] = f'logs/{simulator}_back_to_back.log'
        b2b['log_sha256'] = sha_file(work / 'logs' / f'{simulator}_back_to_back.log')
        report['simulators'][simulator]['back_to_back'] = b2b
        if b2b['status'] != 'PASS':
            failures.append(f'{simulator} back-to-back job')

        # negative controls through the replayed page
        for control in controls:
            name = control['name']
            stim = control['stimulatory']
            plusargs = [
                f'+STIM={stim["stim"]}', f'+CMD_WORDS={stim["cmd_words"]}',
                f'+AMOUNT={control["amount"]}',
                f'+ECASE={control["ecode"]}', f'+NAME={name}',
                f'+OUT={out_dir / (name + "_")}',
            ] + control['plusargs']
            code, warnings = execute(launch, work, f'{simulator}_{name}', plusargs)
            ok = not code and not warnings
            record = {
                'status': 'PASS' if ok else 'FAIL',
                'expected_error_code': control['ecode'],
                'refusal': control['refusal'],
                'note': control['note'],
                'log': f'logs/{simulator}_{name}.log',
                'log_sha256': sha_file(work / 'logs' / f'{simulator}_{name}.log'),
            }
            if control['refusal']:
                record['bo_compare'] = 'not executed (submit refused)'
            elif ok and control['ecode'] == 0:
                cmp = compare_case(control['entry'], out_dir / f'{name}_')
                record['masked_exact'] = cmp['masked_comparison']['exact']
            report['simulators'][simulator]['negative_controls'][name] = record
            if not ok:
                failures.append(f'{simulator} negative control {name}')
        report['simulators'][simulator]['status'] = 'PASS' if not [
            failure for failure in failures if failure.startswith(simulator)] \
            else 'FAIL'
        save()

    report['completed_utc'] = utc()
    report['status'] = 'PASS' if not failures else 'FAIL'
    report['failures'] = failures
    (work / 'report.txt').write_text(
        f'ew-int Image-B page replay receipt {stamp}\n'
        f'status: {report["status"]}\nscope: {SCOPE}\n'
        f'aperture audit: {aperture_audit["verdict"]} '
        f'(4 x 4 KiB banks, 16 KiB physical)\n'
        f'READY cases: {len(ready)}  BLOCKED: {len(blocked)}  '
        f'negative controls: {len(controls)}\n'
        f'simulators: {report["simulators"]}\nfailures: {failures}\n')
    save()
    print(f'[ew-int-page] {report["status"]}: {len(ready)} cases, '
          f'{len(controls)} negative controls, back-to-back reset-per-job')
    if failures:
        for failure in failures:
            print('  FAIL', failure)
        return 1
    print(f'[ew-int-page] receipt: {work / "report.json"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
