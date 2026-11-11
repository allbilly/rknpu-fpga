#!/usr/bin/env python3
"""Whole-image replay of the frozen pooling corpus through the AXI4-Lite page.

For every READY case of build/rk3588-example-captures/pooling/manifest.json
(19 cases: 18 live-captured + one source-derived) the runner:

  1. validates every frozen fixture file against the capture manifest hashes;
  2. patches the two relocatable base-address QWORD fields exactly like the
     existing raw pooling engines (in -> 0x1000, out -> 0x2000) and writes the
     patched command stream + the fixture's in/out_init/expected BOs as
     byte-hex memories for the bench;
  3. compiles the pooling-corpus image top with the replay bench once per
     simulator, then invokes it once per corpus page through real AXI4-Lite;
  4. the bench checks the page identity and the COMPLETE 4096-byte BO in
     hardware: exact for integer/max/min/index lanes and untouched bytes, and
     the capture's declared absolute tolerance for FP16 average lanes (compared
     exactly in FP16 2^-24 fixed-point units). It also runs the image-level
     refusals on page 0: SLVERR for unmapped addresses, SLVERR for a submit
     while another page is active, and a tampered captured command field that
     must fault its page instead of succeeding.

No device, Vivado, bitstream or hardware access is involved.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ppu import gen_pool_corpus_tables as corpus  # noqa: E402

RUNNER = Path(__file__).resolve()
TB = ROOT / 'tests/tb_ypcb_ppu_corpus.sv'
SPEC = ROOT / 'fpga/ppu/corpus_sources.json'
TB_INCLUDE = ROOT / 'tests/axil_host.svh'
BO_BYTES = 4096
IN_BASE = 0x0000_1000
OUT_BASE = 0x0000_2000
PASS_RE = re.compile(
    r'^PASS PPU_CORPUS page=(\d+) polls=(\d+) mismatches=(\d+) '
    r'over_tolerance=(\d+)$')
IMAGE_RE = re.compile(r'^PASS PPU_CORPUS_IMAGE negative_code=(\d+)$')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def tool_version(argv: list[str]) -> str:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=30)
    text = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise RuntimeError(f'tool version command failed: {argv}: {text}')
    return text.splitlines()[0] if text else 'unknown'


def rtl_sources() -> list[Path]:
    """Everything the simulators compile; constraints/CDC stay out of this list."""
    spec = json.loads(SPEC.read_text())
    # axil_host.svh is included by the bench, never compiled as its own source.
    return [ROOT / name for name in spec['sources']] + [TB]


def source_list() -> list[Path]:
    spec = json.loads(SPEC.read_text())
    paths = [ROOT / name for name in spec['sources']]
    paths += [ROOT / spec['constraints'], TB, TB_INCLUDE, RUNNER,
              ROOT / 'tools/ppu/gen_pool_corpus_tables.py', SPEC,
              ROOT / 'build/rk3588-example-captures/pooling/manifest.json']
    return paths


def fixture_inputs(case: str) -> dict:
    """Resolve and hash-check every frozen input of one corpus case."""
    entry = corpus.capture_entry(case)
    job = json.loads(corpus.resolve_file(case, 'job.json').read_text())
    files = {name: corpus.resolve_file(case, name)
             for name in ('job.json', 'regcmd.bin', 'in.bin', 'out_init.bin',
                          'expected.bin')}
    qwords = job['tasks'][0]['regcmd_words']
    reloc = {}
    for patch in job['patches']:
        if patch['kind'] != 'value32':
            raise ValueError(f'{case}: unexpected patch kind')
        reloc[patch['buffer']] = patch['regcmd_index']
    if set(reloc) != {'in', 'out'}:
        raise ValueError(f'{case}: relocations must be for in and out')
    raw = bytearray(files['regcmd.bin'].read_bytes())
    if len(raw) != qwords * 8:
        raise ValueError(f'{case}: regcmd is not {qwords} QWORDs')
    for buffer_name, base in (('out', OUT_BASE), ('in', IN_BASE)):
        offset = reloc[buffer_name] * 8
        raw[offset + 2:offset + 6] = base.to_bytes(4, 'little')
    layout = entry['layout']
    dtype = entry['ppu']['dtype']
    method = entry['ppu']['method']
    tolerance = float(entry.get('oracle', {}).get('tolerance', 0.0))
    value_bytes = int(layout['output'].get('value_bytes',
                                           layout['output']['logical_bytes']))
    index_bytes = int(layout['output'].get('index_bytes', 0))
    index_en = bool(layout['output'].get('index_en', False))
    index_offset = int(layout['output'].get('index_offset') or 0)
    # FP16 average captures carry a declared absolute tolerance; everything
    # else is exact. Tolerance is passed to the bench in FP16 2^-24 units so the
    # comparison is exact integer arithmetic on the captured values.
    fp16_tolerance = 1 if (dtype == 'float16' and tolerance > 0.0) else 0
    tolerance_units = int(round(tolerance * (1 << 24)))
    return {
        'case': case,
        'entry': entry,
        'job': job,
        'files': files,
        'qwords': qwords,
        'patched': bytes(raw),
        'dtype': dtype,
        'method': method,
        'tolerance': tolerance,
        'fp16_tolerance': fp16_tolerance,
        'tolerance_units': tolerance_units,
        'value_bytes': value_bytes,
        'index_bytes': index_bytes,
        'index_en': index_en,
        'index_offset': index_offset,
    }


def byte_hex(payload: bytes, size: int) -> str:
    if len(payload) > size:
        raise ValueError('fixture payload larger than its BO window')
    padded = payload + b'\0' * (size - len(payload))
    return ''.join(f'{value:02x}\n' for value in padded)


def write_case_inputs(directory: Path, page: int, spec: dict) -> None:
    (directory / f'cmd_{page}.hex').write_text(
        byte_hex(spec['patched'], 256))
    (directory / f'in_{page}.hex').write_text(
        byte_hex(spec['files']['in.bin'].read_bytes(), BO_BYTES))
    (directory / f'out_init_{page}.hex').write_text(
        byte_hex(spec['files']['out_init.bin'].read_bytes(), BO_BYTES))
    (directory / f'expected_{page}.hex').write_text(
        byte_hex(spec['files']['expected.bin'].read_bytes(), BO_BYTES))


def plusargs(hexdir: Path, page: int, spec: dict) -> list[str]:
    return [
        f'+PAGE={page}', f'+CMD_WORDS={spec["qwords"] * 2}',
        f'+CRC32={corpus.zlib.crc32(spec["case"].encode()) & 0xFFFF_FFFF}',
        f'+DTYPE={spec["fp16_tolerance"]}',
        f'+TOL_UNITS={spec["tolerance_units"]}',
        f'+VALUE_BYTES={spec["value_bytes"]}',
        f'+INDEX_EN={1 if spec["index_en"] else 0}',
        f'+INDEX_OFFSET={spec["index_offset"]}',
        f'+INDEX_BYTES={spec["index_bytes"]}',
        f'+CMD_HEX={hexdir / f"cmd_{page}.hex"}',
        f'+IN_HEX={hexdir / f"in_{page}.hex"}',
        f'+INIT_HEX={hexdir / f"out_init_{page}.hex"}',
        f'+EXPECTED_HEX={hexdir / f"expected_{page}.hex"}',
    ]


def build_arguments(simulator: str, outdir: Path,
                    sources: list[Path]) -> tuple[list[str], list[str]]:
    compiler = shutil.which(simulator)
    if not compiler:
        raise RuntimeError(f'{simulator} is not installed')
    if simulator == 'iverilog':
        if not shutil.which('vvp'):
            raise RuntimeError('vvp is not installed')
        binary = outdir / 'sim.vvp'
        argv = [compiler, '-g2012', '-Irtl', '-Itests',
                '-s', 'tb_ypcb_ppu_corpus', '-o', str(binary),
                *[str(path) for path in sources]]
        return argv, [str(binary)]
    binary = outdir / 'obj_dir'
    argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
            '-j', '2', '--timescale-override', '1ns/1ps', '-Irtl', '-Itests',
            '--top-module', 'tb_ypcb_ppu_corpus', '--Mdir', str(binary),
            '-o', 'sim', *[str(path) for path in sources]]
    return argv, [str(binary / 'sim')]


def run_simulator(simulator: str, cases: list[str], outdir: Path,
                  keep_build: bool) -> dict:
    all_cases = corpus.corpus_cases()
    pages = [all_cases.index(case) for case in cases]
    specs = {case: fixture_inputs(case) for case in cases}
    outdir.mkdir(parents=True, exist_ok=False)
    hexdir = outdir / 'cases'
    hexdir.mkdir()
    for page, case in zip(pages, cases):
        write_case_inputs(hexdir, page, specs[case])

    tracked = source_list()
    for spec in specs.values():
        tracked.extend(spec['files'].values())
        tracked.append(ROOT / 'tests/ppu_pooling/fixtures' / spec['case'] /
                       'manifest.json')
    tracked = [path for path in dict.fromkeys(tracked) if path.is_file()]
    hashes_before = {str(path.relative_to(ROOT)): sha(path) for path in tracked}

    build_dir = outdir / 'build'
    build_dir.mkdir()
    argv, run_prefix = build_arguments(simulator, build_dir, rtl_sources())
    report = {
        'status': 'RUNNING', 'mode': 'pooling-corpus-image',
        'simulator': simulator, 'started_utc': utc_now(),
        'tool_version': tool_version(
            [shutil.which(simulator), '--version' if simulator == 'verilator' else '-V']),
        'compile_command': [str(arg) for arg in argv],
        'source_hashes_before': hashes_before,
        'cases': cases, 'pages': len(cases), 'complete_bo_bytes': BO_BYTES,
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
    }
    compile_log = outdir / 'compile.log'
    build = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                           check=False, timeout=3600)
    compile_log.write_text(build.stdout + build.stderr)
    report['compile'] = {'returncode': build.returncode,
                         'log': str(compile_log.relative_to(ROOT))}
    if build.returncode:
        report.update(status='FAIL',
                      failure=(build.stdout + build.stderr)[-4000:])
        (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                       sort_keys=True) + '\n')
        return report

    run_log = outdir / 'run.log'
    results = {}
    failures = []
    started = time.monotonic()
    with run_log.open('w') as stream:
        for page, case in zip(pages, cases):
            args = run_prefix + plusargs(hexdir, page, specs[case])
            try:
                run = subprocess.run(args, cwd=ROOT, text=True,
                                     capture_output=True, check=False,
                                     timeout=1800)
            except subprocess.TimeoutExpired as error:
                failures.append(f'{case}: simulator timeout')
                stream.write(f'### {case}\nTIMEOUT {error}\n')
                continue
            output = run.stdout + run.stderr
            stream.write(f'### {case}\n{output}\n')
            match = next((PASS_RE.match(line) for line in output.splitlines()
                          if PASS_RE.match(line)), None)
            image = next((IMAGE_RE.match(line) for line in output.splitlines()
                          if IMAGE_RE.match(line)), None)
            ok = run.returncode == 0 and match is not None
            record = {'page': page, 'returncode': run.returncode,
                      'pass': ok}
            if match:
                record.update(polls=int(match.group(2)),
                              mismatches=int(match.group(3)),
                              over_tolerance=int(match.group(4)),
                              negative_code=(int(image.group(1)) if image
                                             else None))
                ok = ok and record['mismatches'] == 0 and \
                    record['over_tolerance'] == 0
            if page == 0 and image is None:
                ok = False
                record['failure'] = 'image-level refusal/negative control missing'
            record['pass'] = ok
            results[case] = record
            if not ok:
                failures.append(case)
    report['run'] = {'log': str(run_log.relative_to(ROOT)),
                     'seconds': round(time.monotonic() - started, 3)}
    report['case_results'] = results
    if failures:
        report.update(status='FAIL', failure=f'cases failed: {failures}')
    else:
        report.update(status='PASS', finished_utc=utc_now())
    hashes_after = {str(path.relative_to(ROOT)): sha(path) for path in tracked}
    report['source_hashes_after'] = hashes_after
    changed = sorted(name for name in set(hashes_before) | set(hashes_after)
                     if hashes_before.get(name) != hashes_after.get(name))
    report['source_changed_during_run'] = changed
    report['source_match'] = not changed
    report['comparison_contract'] = (
        'complete 4096-byte BO compared in hardware: exact for integer/max/min/'
        'index lanes and untouched bytes; the capture-declared absolute tolerance '
        'for FP16 average lanes, evaluated exactly in FP16 2^-24 fixed-point units')
    if changed:
        report['status'] = 'FAIL'
        report['failure'] = 'source changed during the run: ' + ', '.join(changed)
    if not keep_build:
        shutil.rmtree(build_dir)
        report['build_products_pruned'] = True
    (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                   sort_keys=True) + '\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'),
                        default='both')
    parser.add_argument('--case', action='append', default=None,
                        help='replay only these corpus cases (default: all 19)')
    parser.add_argument('--out', type=Path, default=None,
                        help='output directory for one simulator')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    cases = corpus.corpus_cases()
    selected = cases if not args.case else [case for case in cases
                                            if case in set(args.case)]
    if args.case and not selected:
        parser.error(f'no known corpus case selected: {args.case}')
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' \
        else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    failures = 0
    for simulator in simulators:
        outdir = (args.out or (ROOT / 'build/pooling-image' /
                               f'sim-{simulator}-{stamp}')).resolve()
        if outdir.exists():
            parser.error(f'output already exists: {outdir}')
        report = run_simulator(simulator, selected, outdir, args.keep_build)
        print(f"{report['status']} pooling-corpus image {simulator}: "
              f"{outdir.relative_to(ROOT)}")
        if report['status'] != 'PASS':
            failures += 1
            print(report.get('failure', '')[-2000:], file=sys.stderr)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
