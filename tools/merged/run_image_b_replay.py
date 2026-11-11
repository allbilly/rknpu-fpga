#!/usr/bin/env python3
"""Image-B S3/S4 replay plan (pooling corpus + EW FP16/FDIV + ew-int).

Offline planner/validator only. It discovers the frozen fixture families, binds
every file by sha256, checks that each case's staging fits the Image-B address
map (19 x 4 KiB pooling band, EW six-bank aperture, ew-int four-bank aperture),
records the **complete-BO comparison scope** per family (including the honest
gaps where the frozen bundle has only a logical oracle), lists the negative
controls, and writes a source-bound plan receipt under build/.

``fixtures`` (default) never runs RTL. ``full`` refuses with the exact missing
real pages until the pooling/EW page refs are flipped, and even then refuses
without ``--execute`` because the ewint both-simulator page replay is ~10 min
single-core (a Lead-scheduled heavy-window item, never a quick local check).

No Vivado, no synthesis, no hardware.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.merged import vivado_merged_image as image_tool  # noqa: E402

POOLING = ROOT / 'tests/ppu_pooling/fixtures'
EW_FP16 = ROOT / 'build/rk3588-example-captures/ew-fp16/cases'
FDIV = ROOT / 'build/rk3588-example-captures/fdiv-systematic/cases'
EW_INT = ROOT / 'build/rk3588-example-captures/ew-int/cases'
PRODUCTION_EW = ROOT / 'tests/backend_ew_captures.json'

POOL_BAND_BASE, POOL_BAND_PAGES, POOL_PAGE_BYTES = 0x0001_0000, 19, 4096
EW_BANK = {'a': 0x1000_1000, 'b': 0x1002_0000, 'd': 0x1004_0000,
           'command': 0x100E_0000, 'task': 0x100F_0000}
EW_INT_BANK = {'a': 0x1100_1000, 'b': 0x1100_2000, 'd': 0x1100_3000,
               'command': 0x1100_4000}
EW_INT_AMOUNTS = {18, 31, 44}


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest_sha(files: dict) -> str:
    text = ''.join(f'{digest}  {name}\n' for name, digest in sorted(files.items()))
    return hashlib.sha256(text.encode()).hexdigest()


def file_record(path: Path) -> dict:
    return dict(bytes=path.stat().st_size, sha256=sha(path))


def frozen_cases(directory: Path) -> list[dict]:
    cases = []
    for case_dir in sorted(directory.iterdir()):
        if not case_dir.is_dir() or not (case_dir / 'job.json').is_file():
            continue
        job = json.loads((case_dir / 'job.json').read_text())
        files = {name: file_record(case_dir / name)
                 for name in ('regcmd.bin', 'job.json', 'a.bin', 'b.bin',
                              'input-a.bin', 'input-b.bin', 'expected.bin',
                              'expected.mask.bin', 'in.bin', 'device_out.bin')
                 if (case_dir / name).is_file()}
        qwords = int(job['tasks'][0]['regcmd_words'])
        cases.append(dict(case=case_dir.name,
                          fixture=str(case_dir.relative_to(ROOT)),
                          status=job.get('status', 'READY'),
                          command_qwords=qwords,
                          buffers=job.get('buffers', []),
                          patches=job.get('patches', []),
                          files=files))
    return cases


def pool_cases() -> list[dict]:
    cases = []
    for case_dir in sorted(POOLING.iterdir()):
        manifest_path = case_dir / 'manifest.json'
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text())
        status = manifest.get('status', '')
        files = {name: file_record(case_dir / name)
                 for name in ('regcmd.bin', 'in.bin', 'out_init.bin',
                              'device_out.bin', 'expected.bin', 'manifest.json')
                 if (case_dir / name).is_file()}
        cases.append(dict(case=case_dir.name,
                          fixture=str(case_dir.relative_to(ROOT)),
                          status=status,
                          ready='READY' in status,
                          command_bytes=files.get('regcmd.bin', {}).get('bytes'),
                          complete_bo=('device_out.bin' in files),
                          files=files))
    return cases


def plan_families() -> dict:
    pool = pool_cases()
    pool_ready = [case for case in pool if case['ready']]
    ew_fp16 = frozen_cases(EW_FP16)
    fdiv = frozen_cases(FDIV)
    ew_int = frozen_cases(EW_INT)
    production_count = len(json.loads(PRODUCTION_EW.read_text())['cases'])

    if len(pool_ready) != POOL_BAND_PAGES:
        raise SystemExit(f'pooling corpus has {len(pool_ready)} READY cases, '
                         f'expected {POOL_BAND_PAGES} band pages')
    if len(ew_fp16) != 54:
        raise SystemExit(f'ew-fp16 has {len(ew_fp16)} cases, expected 54')
    if len(fdiv) != 8:
        raise SystemExit(f'fdiv-systematic has {len(fdiv)} cases, expected 8')
    if len(ew_int) != 15:
        raise SystemExit(f'ew-int has {len(ew_int)} READY cases, expected 15')

    problems = []
    pool_plan = []
    for index, case in enumerate(pool_ready):
        address = POOL_BAND_BASE + index * POOL_PAGE_BYTES
        if case['command_bytes'] and case['command_bytes'] > POOL_PAGE_BYTES:
            problems.append(f'{case["case"]}: pooling command {case["command_bytes"]} B > page')
        pool_plan.append(dict(case=case['case'], fixture=case['fixture'],
                              page_address=address, command_bytes=case['command_bytes'],
                              files=case['files']))

    ew_plan = []
    for case in ew_fp16:
        for key, bank in (('a', EW_BANK['a']), ('b', EW_BANK['b'])):
            if case['files'].get(key + '.bin', {}).get('bytes') != 4096:
                problems.append(f'{case["case"]}: ew-fp16 {key} buffer is not 4096 B')
        if case['command_qwords'] != 22:
            problems.append(f'{case["case"]}: ew-fp16 command is {case["command_qwords"]} QWORDs')
        ew_plan.append(dict(case=case['case'], fixture=case['fixture'],
                            command_qwords=case['command_qwords'],
                            staging={'a': EW_BANK['a'], 'b': EW_BANK['b'],
                                     'out': EW_BANK['d'], 'command': EW_BANK['command']},
                            files=case['files']))

    fdiv_plan = []
    for case in fdiv:
        if case['command_qwords'] != 22:
            problems.append(f'{case["case"]}: fdiv command is {case["command_qwords"]} QWORDs')
        fdiv_plan.append(dict(case=case['case'], fixture=case['fixture'],
                              command_qwords=case['command_qwords'],
                              staging={'a': EW_BANK['a'], 'b': EW_BANK['b'],
                                       'out': EW_BANK['d'], 'command': EW_BANK['command']},
                              files=case['files']))

    ew_int_plan = []
    for case in ew_int:
        if case['command_qwords'] not in EW_INT_AMOUNTS:
            problems.append(f'{case["case"]}: ew-int command {case["command_qwords"]} '
                            f'not in {sorted(EW_INT_AMOUNTS)}')
        complete = 'expected.bin' in case['files'] and 'expected.mask.bin' in case['files']
        ew_int_plan.append(dict(case=case['case'], fixture=case['fixture'],
                                command_qwords=case['command_qwords'],
                                staging=dict(EW_INT_BANK),
                                masked_complete_bo=complete, files=case['files']))

    return dict(problems=problems,
                families=[
                    dict(family='pooling-corpus', total=len(pool), ready=len(pool_ready),
                         command_bytes=sorted({c['command_bytes'] for c in pool_ready}),
                         complete_bo_oracle='device_out.bin (4096 B) per case',
                         staging='19 x 4 KiB band pages at 0x0001_0000 + i*0x1000',
                         cases=pool_plan),
                    dict(family='ew-fp16', total=len(ew_plan), ready=len(ew_plan),
                         command_qwords=22, complete_bo_oracle=None,
                         comparison_scope=('frozen bundles are device-free: expected.bin is a '
                                           'logical oracle, so a complete-BO compare is only '
                                           'available for the production captures leg '
                                           f'({production_count} cases, tests/backend_ew_captures.json); '
                                           'these 54 bundles compare defined elements per the '
                                           'captured layout in the S4 replay, not full BO bytes'),
                         oracle_decision=dict(
                             adopted='logical expected.bin comparison only (Lead decision, 2026-11-11)',
                             complete_bo_leg=('reserved for the 9 production captures '
                                              '(tests/backend_ew_captures.json); these bundles are '
                                              'device-free prepared fixtures, not capture-derived '
                                              'complete BOs'),
                             rule='no invented device expectations'),
                         staging='EW six-bank aperture (A/B/D + command bank)',
                         cases=ew_plan),
                    dict(family='fdiv-systematic', total=len(fdiv_plan),
                         ready=len(fdiv_plan), command_qwords=22,
                         complete_bo_oracle=None,
                         comparison_scope=('operand-class truth table; expected values come from '
                                           'the device-confirmed three-guard-bit RTL model '
                                           '(docs/FDIV.md), not from a capture-derived expected BO: '
                                           'logical float compare with the documented exception set'),
                         oracle_decision=dict(
                             adopted=('three-guard-bit RTL model from docs/FDIV.md '
                                      '(Lead decision, 2026-11-11)'),
                             evidence=('device-confirmed live differential 1,452/1,452 captured '
                                       'lanes (build/rk3588-live-verify/FDIV-RESIDUAL.md, '
                                       'build/rk3588-live-verify/20261109T201838Z-j07/, '
                                       'build/rtl/report.json)'),
                             exception_set=('exactly the 20 documented A/7 one-ULP-low lanes '
                                            '(19 unique A/7 operand pairs + the p1_n33 repeat) are '
                                            'expected to differ by -1 bit from donor-RNE'),
                             comparison=('logical float compare against the three-guard-bit model with '
                                         'the documented exception set; a value outside that set fails'),
                             nature=('model/contract oracle (device-confirmed); NOT a capture-derived '
                                     'expected BO for these bundles'),
                             special_values=('candidate behaviour per docs/FDIV.md; not an RK3588 '
                                             'specification or IEEE-clean divider')),
                         staging='EW six-bank aperture (A/B/D + command bank)',
                         cases=fdiv_plan),
                    dict(family='ew-int', total=len(ew_int_plan), ready=len(ew_int_plan),
                         command_qwords=sorted(EW_INT_AMOUNTS),
                         complete_bo_oracle='expected.bin + expected.mask.bin (masked complete 4096-B BO)',
                         staging='ew-int four-bank aperture A/B/D/C (command in bank C)',
                         cases=ew_int_plan),
                ],
                negatives=[
                    'unsupported op/dtype register -> decoder E2',
                    'aperture-hole operand address -> memory-bus E5',
                    'unknown register target -> E1',
                    'wrong START_AMOUNT (not 18/31/44 / wrong shape) -> E6/fail closed',
                    'unaligned START_ADDRESS -> fail closed',
                    'missing JOB_TAG / missing fields -> refusal',
                    'partial WSTRB / protected access -> SLVERR',
                    'host staging while page busy -> SLVERR',
                    'engine access to a hole -> mem_rsp_error',
                    'command BO must not be modified by a job (byte compare after run)',
                    'sticky error until fabric reset; clean back-to-back jobs need no fabric reset',
                ],
                heavy_run="ewint page replay is ~2 min Verilator / ~10 min Icarus single-core: "
                          "Lead-scheduled heavy window only",
                production_ew_cases=production_count)


def write_receipt(directory: Path, payload: dict) -> dict:
    files = {}
    for path in [ROOT / 'tools/merged/run_image_b_replay.py',
                 ROOT / 'tools/merged/vivado_merged_image.py',
                 ROOT / 'fpga/image_b/image_b_sources.json',
                 ROOT / 'fpga/image_b/build_image_b.tcl.in',
                 ROOT / 'tests/merged/test_image_b_contract.py',
                 PRODUCTION_EW]:
        files[str(path.relative_to(ROOT))] = sha(path)
    for family_dir in (POOLING, EW_FP16, FDIV, EW_INT):
        for path in sorted(family_dir.rglob('*')):
            if path.is_file():
                files[str(path.relative_to(ROOT))] = sha(path)
    record = dict(schema='rk3588-image-b-replay-plan/v1', status='PLAN_READY',
                  generated_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  mode='fixtures', payload=payload,
                  source_hashes=files, source_manifest_sha256=manifest_sha(files),
                  vivado_executed=False, hardware_accessed=False)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'plan.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def out_dir(requested: Path | None) -> Path:
    directory = requested or (ROOT / 'build/merged-image' /
                              f'replay-b-{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}')
    directory = Path(directory)
    if not directory.is_absolute():
        directory = ROOT / directory
    if not directory.resolve().is_relative_to((ROOT / 'build').resolve()):
        raise SystemExit('replay output must be below build/')
    if directory.exists():
        raise SystemExit('replay output must be a fresh directory')
    return directory


def mode_fixtures(directory: Path) -> int:
    payload = plan_families()
    problems = payload.pop('problems')
    status = 'PLAN_READY' if not problems else 'FAIL'
    record = write_receipt(directory, dict(payload, problems=problems))
    record['status'] = status
    (directory / 'plan.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    if problems:
        print('Image-B replay plan: FAIL')
        for problem in problems[:20]:
            print('  PROBLEM', problem)
        return 1
    counts = ', '.join(f'{f["family"]}={f["ready"]}' for f in payload['families'])
    print(f'Image-B replay plan: PLAN_READY ({counts})')
    print(f'  receipt: {directory}/plan.json source={record["source_manifest_sha256"][:8]}')
    return 0


def mode_full(directory: Path, execute: bool) -> int:
    spec = image_tool.load_spec(profile='image-b')
    pages = {page['name']: page for page in spec['pages']}
    missing = []
    if pages['pool_band_page']['ref'] == 'merged_page_stub':
        missing.append('pool_band_page is still merged_page_stub (real pooling pages not attached)')
    if pages['ew_page']['ref'] == 'merged_page_stub':
        missing.append('ew_page is still merged_page_stub (EW control front end not attached)')
    if pages['ew_aperture_page']['ref'] == 'merged_page_stub':
        missing.append('ew_aperture_page is still merged_page_stub (EW sparse aperture not attached)')
    if missing:
        print('Image-B family replay: REFUSED_UNTIL_REAL_PAGES')
        for item in missing:
            print('  missing:', item)
        print('  then: Lead-scheduled heavy window for the both-simulator replay')
        return 1
    if not execute:
        print('Image-B family replay: HEAVY_WINDOW_REQUIRED')
        print('  note: the ewint page replay is ~2 min Verilator / ~10 min Icarus single-core;')
        print('    re-run with --execute only inside a Lead-scheduled cool window through')
        print('    build/verif/host_guard/safe_run.sh.')
        return 1
    print('Image-B family replay: heavy execution is a Lead-window item; '
          'this scaffold only prepares the plan.')
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mode', choices=('fixtures', 'full'), default='fixtures')
    parser.add_argument('--out', type=Path, help='fresh directory below build/')
    parser.add_argument('--execute', action='store_true',
                        help='explicit heavy-window authorization for full mode')
    args = parser.parse_args()
    directory = out_dir(args.out)
    if args.mode == 'fixtures':
        return mode_fixtures(directory)
    return mode_full(directory, args.execute)


if __name__ == '__main__':
    raise SystemExit(main())
