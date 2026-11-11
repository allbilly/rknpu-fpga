#!/usr/bin/env python3
"""Image-A replay scaffolding (S1): fixtures/ABI legs now, engine replay on attach.

This tool is deliberately ahead of the real runtime page so that only the wrapper
file and its hashes have to be pinned when conveng's parameterised equivalence
rerun lands. It never invents fixtures: the case set is discovered from the
frozen `tests/conv/fixtures/` tree and every file is hashed.

Modes
-----
``fixtures`` (default) build and validate the complete-BO replay plan for the
    Image-A 64 KiB window from the frozen conv fixtures (conv-simple profiles and
    vendor conv-fp16 captures): command-QWORD count, address-patch indices,
    buffer sizes, staged window addresses, non-overlap, complete-output-BO
    comparison metadata. Writes ``plan.json`` + source-bound ``inputs.json``.
    This mode does not execute RTL (the engine is not attached yet).
``abi`` compile and run ``tests/tb_image_a_job_abi.sv`` through Icarus: the
    mailbox->AXI->page ABI, register contract, submit/ack/re-arm lifecycle and
    the scaffold negative controls (unaligned/out-of-window/zero/oversized
    START, submit-while-pending, recovery after acknowledged errors).
``full`` the real family replay. It **refuses** until the profile's
    ``conv_runtime_page.ref`` is the real page wrapper (``rk_conv_runtime_page_axi``;
the plan called it ``rk_conv_runtime_axi``) and the wrapper source is
    listed, then (at S1) would generate per-case benches, run them and diff the
    complete output BO against the frozen capture. Until then it exits non-zero
    with the exact missing items, so a green full mode is proof the real page is
    attached.

No synthesis, no Vivado, no hardware. Long simulations are the caller's
responsibility (heavy-job policy).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.merged import vivado_merged_image as image_tool  # noqa: E402

FIXTURES = ROOT / 'tests/conv/fixtures'
STUBS = 'tests/merged/merged_primitive_stubs.sv'
ABI_BENCH = 'tests/tb_image_a_job_abi.sv'
ABI_MARK = 'PASS YPCB_IMAGE_A_JOB_ABI'
WINDOW_BYTES = 65536
# One fixed staging layout that keeps every frozen conv case inside one window.
#   command BO     0x0000.. (<= 0x1000, 52/54 QWORDs = 416/432 B)
#   input BO       0x1000.. (<= 0x1000)
#   weight BO      0x2000.. (<= 0x2400 for the C16 profile)
#   output BO      0x5000.. (<= 0x1000)
#   PC tail/task   0x7000.. (reserved, <= 0x1000)
# Staging layout: the command BO starts at window offset 0; the operand/output
# BOs are then packed per case with 64-byte granularity (every patch address is
# 16-byte aligned), because the frozen corpus spans 1 KiB..15 KiB BOs. The whole
# set must fit the 64 KiB Image-A window; the plan records every address.
COMMAND_BASE = 0x0000_0000
STAGING_GRANULE = 64


def align(value: int, granule: int = STAGING_GRANULE) -> int:
    return (value + granule - 1) // granule * granule


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_sha(files: dict) -> str:
    text = ''.join(f'{digest}  {name}\n' for name, digest in sorted(files.items()))
    return hashlib.sha256(text.encode()).hexdigest()


def discover_fixtures() -> list[dict]:
    cases = []
    for directory in sorted(FIXTURES.iterdir()):
        manifest_path = directory / 'manifest.json'
        if not directory.is_dir() or not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text())
        case = manifest.get('case') or directory.name
        if not case.startswith('conv_'):
            continue
        files = {}
        for name in ('regcmd.bin', 'input.bin', 'weight.bin', 'a.bin', 'w.bin',
                     'expected.bin', 'device_out.bin', 'manifest.json', 'job.json'):
            path = directory / name
            if path.is_file():
                files[name] = dict(bytes=path.stat().st_size, sha256=sha(path))
        command = manifest.get('command_stream') or manifest.get('command') or {}
        qwords = command.get('qwords') or command.get('words')
        if qwords is None and 'regcmd.bin' in files:
            qwords = files['regcmd.bin']['bytes'] // 8
        # Two frozen fixture generations:
        #   new: input.bin/weight.bin BO images (conv-simple captures, 52 QWORDs)
        #   old: a.bin/w.bin BO images (vendor conv-fp16 captures, 54 QWORDs)
        if 'input.bin' in files and 'weight.bin' in files:
            family, input_name, weight_name = 'conv-simple', 'input.bin', 'weight.bin'
        elif 'a.bin' in files and 'w.bin' in files:
            family, input_name, weight_name = 'vendor', 'a.bin', 'w.bin'
        else:
            continue
        if 'regcmd.bin' not in files or qwords is None:
            continue
        # Complete-BO comparison uses the captured device output BO when
        # present; expected.bin alone is a logical oracle for the vendor family.
        expected = 'device_out.bin' if 'device_out.bin' in files else 'expected.bin'
        cases.append(dict(
            case=case, directory=str(directory.relative_to(ROOT)),
            status=manifest.get('status', 'unknown'), family=family,
            command_qwords=int(qwords),
            address_qwords=command.get('address_qwords') or [],
            files=files, expected_file=expected,
            input_file=input_name, weight_file=weight_name,
            comparison=manifest.get('comparison', {}),
            shape=manifest.get('shape', {})))
    if not cases:
        raise SystemExit('no usable frozen conv fixtures found; refusing to invent cases')
    return cases


def plan_case(case: dict) -> dict:
    buffers = [
        ('input', case['files'][case['input_file']]['bytes']),
        ('weight', case['files'][case['weight_file']]['bytes']),
        ('output', case['files'][case['expected_file']]['bytes']),
    ]
    command_bytes = case['files']['regcmd.bin']['bytes']
    problems = []
    planned = {'command': dict(address=COMMAND_BASE, bytes=command_bytes)}
    cursor = max(align(command_bytes), STAGING_GRANULE)
    for name, size in buffers:
        cursor = align(cursor)
        planned[name] = dict(address=cursor, bytes=size)
        cursor += size
    planned['task'] = dict(address=align(cursor), bytes=0)  # single-task fixtures
    if cursor > WINDOW_BYTES:
        problems.append(f'{case["case"]}: staged BOs need {cursor} B > window {WINDOW_BYTES} B')
    for name, span in planned.items():
        if span['address'] % 16:
            problems.append(f'{case["case"]}: {name} staged address not 16-byte aligned')
    if not case['address_qwords']:
        # The frozen manifests record the command-QWORD indices that carry the
        # three data pointers; without them the staged addresses cannot be patched.
        problems.append(f'{case["case"]}: manifest has no address_qwords patch indices')
    return dict(case=case['case'], fixture=case['directory'],
                family=case['family'],
                command_qwords=case['command_qwords'],
                address_qwords=case['address_qwords'],
                files=case['files'], expected_file=case['expected_file'],
                comparison=case['comparison'],
                staging=planned,
                complete_bo_compare=True,
                problems=problems)


def source_hashes() -> dict:
    files = [ROOT / 'tools/merged/run_image_a_replay.py',
             ROOT / 'tools/merged/vivado_merged_image.py',
             ROOT / 'fpga/merged/merged_sources.json',
             ROOT / 'fpga/merged/build_merged.tcl.in',
             ROOT / 'tests/merged/test_merged_map_contract.py',
             ROOT / STUBS, ROOT / ABI_BENCH]
    files += sorted(FIXTURES.glob('conv_*/manifest.json'))
    return {str(path.relative_to(ROOT)): sha(path) for path in files}


def out_dir(requested: Path | None) -> Path:
    directory = requested or (ROOT / 'build/merged-image' /
                              f'replay-{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}')
    directory = Path(directory)
    if not directory.is_absolute():
        directory = ROOT / directory
    if not directory.resolve().is_relative_to((ROOT / 'build').resolve()):
        raise SystemExit('replay output must be below build/')
    if directory.exists():
        raise SystemExit('replay output must be a fresh directory')
    return directory


def write_receipt(directory: Path, mode: str, status: str, payload: dict,
                  source_match: bool) -> dict:
    before = source_hashes()
    record = dict(schema='rk3588-image-a-replay/v1', mode=mode, status=status,
                  generated_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  source_hashes=before, source_manifest_sha256=manifest_sha(before),
                  source_match=source_match, vivado_executed=False,
                  hardware_accessed=False, payload=payload)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'plan.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def mode_fixtures(directory: Path) -> int:
    cases = [plan_case(case) for case in discover_fixtures()]
    problems = [problem for case in cases for problem in case['problems']]
    conv_simple = [case for case in cases if case['family'] == 'conv-simple']
    vendor = [case for case in cases if case['family'] == 'vendor']
    payload = dict(cases=cases, problems=problems,
                   conv_simple_cases=len(conv_simple),
                   vendor_cases=len(vendor),
                   window_bytes=WINDOW_BYTES, command_base=COMMAND_BASE,
                   staging_granule=STAGING_GRANULE,
                   comparison='complete captured output BO, byte-exact',
                   engine_negative_controls=[
                       'unsupported geometry (kernel >5, stride >2, non-square stride)',
                       'second stream without a reset pulse (decoder fault 7)',
                       'out-of-window operand/output BO address',
                       'overlapping input/weight/output buffers',
                       'unaligned START_ADDRESS (wrapper, ABI bench)',
                       'second submit while a result is pending (ABI bench)',
                   ],
                   pending=['conveng parameterised equivalence rerun green',
                            'real page wrapper pinned in profile sources/ref'])
    status = 'PLAN_READY' if not problems else 'FAIL'
    before = source_hashes()
    record = write_receipt(directory, 'fixtures', status, payload, source_match=True)
    after = source_hashes()
    if after != before:
        record['status'] = 'FAIL'
        record['source_match'] = False
        (directory / 'plan.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    if record['status'] != 'PLAN_READY':
        print(f'Image-A replay plan: {record["status"]}')
        for problem in problems[:20]:
            print('  PROBLEM', problem)
        return 1
    print(f'Image-A replay plan: PLAN_READY '
          f'({len(cases)} cases: {len(conv_simple)} conv-simple + {len(vendor)} vendor; '
          f'{sum(c["command_qwords"] for c in cases)} command QWORDs total)')
    print(f'  receipt: {directory}/plan.json  source={record["source_manifest_sha256"][:8]}')
    return 0


def mode_abi(directory: Path) -> int:
    if not shutil.which('iverilog') or not shutil.which('vvp'):
        print('Image-A ABI replay: SKIPPED (Icarus not installed)')
        return 0
    spec = image_tool.load_spec()
    # The scaffold ABI bench drove the `merged_job_stub` reference model, which
    # modelled a submit->done lifecycle without touching memory. S1 attached the
    # REAL page: it fetches its command stream through its own memory master and
    # runs the engine, so this bench needs a halfword memory model plus a valid
    # frozen command stream before its lifecycle expectations can mean anything.
    # Refuse explicitly instead of reporting a pass/fail for the wrong model.
    real_page = any('rk_conv_runtime_page_axi' in name for name in spec['sources'])
    if real_page:
        record = write_receipt(directory, 'abi', 'REFUSED',
                               dict(reason='REFUSED_UNTIL_MEMORY_MODEL',
                                    detail=('the runtime page is attached, so the ABI '
                                            'bench needs a halfword memory model and a '
                                            'valid frozen command stream; the scaffold '
                                            'bench only matched the retired stub model'),
                                    superseded_by=[
                                        'build/runtime-conv-lab/page-contract (54/54 captured QWORDs)',
                                        'leg A/B equivalence receipts (3/3 + 51/51)']),
                               source_match=True)
        print('Image-A ABI replay: REFUSED_UNTIL_MEMORY_MODEL')
        print('  reason: the attached runtime page needs a memory model + valid stream;')
        print('          the previous PASS was bound to the retired ABI reference stub.')
        print('  superseded by: page contract (54/54) + leg A/B equivalence')
        print(f'  receipt: {directory}/plan.json')
        return 3

    sources = [str(ROOT / name) for name in spec['sources']]
    with tempfile.TemporaryDirectory(prefix='image_a_abi_') as tmp:
        binary = Path(tmp) / 'abi.vvp'
        compile_argv = [shutil.which('iverilog'), '-g2012', '-Itests',
                        '-Irtl/vendor/nvdla', '-DDESIGNWARE_NOEXIST',
                        '-o', str(binary), '-s', 'tb_image_a_job_abi',
                        str(ROOT / STUBS)] + sources + [str(ROOT / ABI_BENCH)]
        compiled = subprocess.run(compile_argv, cwd=ROOT, capture_output=True,
                                  text=True, timeout=180)
        if compiled.returncode != 0:
            before = source_hashes()
            record = write_receipt(directory, 'abi', 'FAIL',
                                   dict(error='compile failed',
                                        log=(compiled.stdout + compiled.stderr)[-4000:]),
                                   source_match=True)
            print('Image-A ABI replay: FAIL (compile)')
            return 1
        ran = subprocess.run([shutil.which('vvp'), str(binary)], cwd=ROOT,
                             capture_output=True, text=True, timeout=600)
        output = ran.stdout + ran.stderr
        passed = ran.returncode == 0 and ABI_MARK in output
        before = source_hashes()
        record = write_receipt(directory, 'abi', 'PASS' if passed else 'FAIL',
                               dict(run=dict(returncode=ran.returncode,
                                             log=output[-4000:])),
                               source_match=True)
        after = source_hashes()
        if after != before:
            record['status'] = 'FAIL'
            record['source_match'] = False
            (directory / 'plan.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
        print(f'Image-A ABI replay: {record["status"]}')
        if not passed:
            print(output[-1500:])
            return 1
        print(f'  receipt: {directory}/plan.json')
    return 0


def mode_full(directory: Path) -> int:
    spec = image_tool.load_spec()
    page = next(p for p in spec['pages'] if p['name'] == 'conv_runtime_page')
    wrapper = 'rk_conv_runtime_page_axi'   # real S1 page wrapper (attached)
    missing = []
    if page['ref'] != wrapper:
        missing.append(f'conv_runtime_page.ref is {page["ref"]!r}, expected {wrapper!r}')
    if not any(wrapper in name for name in spec['sources']):
        missing.append(f'{wrapper} source is not listed in the profile sources')
    if missing:
        print('Image-A family replay: REFUSED_UNTIL_WRAPPER')
        for item in missing:
            print('  missing:', item)
        print('  gate: conveng parameterised equivalence rerun green + wrapper pinned + '
              'Lead-scheduled cool window')
        return 1
    # Wrapper attached: the replay generator/executor is the S1 remaining step;
    # it must run the frozen cases through the real page and diff complete BOs.
    cases = [plan_case(case) for case in discover_fixtures()]
    before = source_hashes()
    record = write_receipt(directory, 'full', 'WRAPPER_ATTACHED',
                           dict(cases=cases, note=('wrapper present; per-case bench '
                                                   'generation/execution is the S1 step')),
                           source_match=True)
    after = source_hashes()
    if after != before:
        record['status'] = 'FAIL'
        record['source_match'] = False
        (directory / 'plan.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print(f'Image-A family replay: {record["status"]} ({len(cases)} cases prepared)')
    print(f'  receipt: {directory}/plan.json')
    return 0 if record['status'] == 'WRAPPER_ATTACHED' else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mode', choices=('fixtures', 'abi', 'full'), default='fixtures')
    parser.add_argument('--out', type=Path, help='fresh directory below build/')
    args = parser.parse_args()
    directory = out_dir(args.out)
    if args.mode == 'fixtures':
        return mode_fixtures(directory)
    if args.mode == 'abi':
        return mode_abi(directory)
    return mode_full(directory)


if __name__ == '__main__':
    raise SystemExit(main())
