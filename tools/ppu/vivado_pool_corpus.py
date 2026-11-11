#!/usr/bin/env python3
"""Render or run the source-gated pooling-corpus FPGA image. Never programs.

The explicit profile lives in ``fpga/ppu/corpus_sources.json``; this tool
refuses a profile whose part, clock, top, constraints, CDC file, page count or
generated case RTL differs, then:

* ``render`` writes a fresh ``build.tcl`` from the template (no Vivado),
* ``synth`` runs synthesis only (no place/route/bitstream) and records the
  post-synthesis utilisation, for the fit estimate,
* ``run`` re-validates and launches full Vivado batch synthesis and
  implementation.

No hardware is opened and no bitstream is emitted unless
``RK_EMIT_BITSTREAM=1`` is passed through, which the Tcl itself requires a
board-verified ``CONFIG_VOLTAGE``/``CFGBVS`` pair for. Source hashes are taken
before and after the run; a file that changes while the build runs makes the
receipt fail closed instead of being attributable to the wrong source state.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / 'fpga/ppu/corpus_sources.json'
TEMPLATE = ROOT / 'fpga/ppu/build_pool_corpus.tcl.in'
PART = 'xc7k480tffg1156-2'
TOP = 'ypcb_ppu_corpus_jtag_top'
CLOCK_NS = 20.0
CONSTRAINTS = 'fpga/ypcb_ppu_corpus.xdc'
CDC = 'fpga/host/mailbox_cdc.tcl'
GENERATED = 'rtl/ppu/rk_ppu_pool_corpus_case.sv'
GENERATOR = 'tools/ppu/gen_pool_corpus_tables.py'
BITSTREAM = 'rk_ppu_corpus.bit'
EXPECTED_PAGES = 19


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tcl_path(path: Path) -> str:
    value = str(path)
    if any(char in value for char in '{}\\\n\r'):
        raise ValueError(f'Unsupported Tcl path characters: {value}')
    return '{' + value + '}'


def load_spec() -> dict:
    spec = json.loads(SPEC.read_text())
    if spec.get('top') != TOP or spec.get('part') != PART:
        raise ValueError('pooling corpus profile top/part changed')
    if float(spec.get('clock_period_ns', 0)) != CLOCK_NS:
        raise ValueError('pooling corpus profile must keep the 50 MHz clock')
    if spec.get('constraints') != CONSTRAINTS:
        raise ValueError('pooling corpus constraints changed')
    if spec.get('cdc') != CDC:
        raise ValueError('pooling corpus CDC file changed')
    if spec.get('pages') != EXPECTED_PAGES:
        raise ValueError('pooling corpus page count changed')
    sources = spec.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ValueError('pooling corpus profile has no sources')
    if len(sources) != len(set(sources)):
        raise ValueError('pooling corpus profile lists a source twice')
    for name in sources + [spec['constraints'], spec['cdc']]:
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'Missing or unsafe pooling corpus input: {name}')
    generated = spec.get('generated', [])
    if len(generated) != 1:
        raise ValueError('pooling corpus profile must bind exactly its generated case RTL')
    if generated[0].get('path') != GENERATED or generated[0].get('generator') != GENERATOR:
        raise ValueError('generated pooling corpus binding changed')
    return spec


def verify_generated(spec: dict) -> None:
    generator = ROOT / spec['generated'][0]['generator']
    if not generator.is_file():
        raise ValueError('Missing pooling corpus generator')
    result = subprocess.run([sys.executable, str(generator), '--check'], cwd=ROOT,
                            text=True, capture_output=True, check=False, timeout=120)
    if result.returncode:
        raise ValueError(f'Generated pooling corpus case RTL is stale: '
                         f'{result.stdout}{result.stderr}')


def corpus_fixture_files() -> list[Path]:
    """Every frozen fixture file the generated gates are derived from."""
    sys.path.insert(0, str(ROOT))
    from tools.ppu.gen_pool_corpus_tables import corpus_cases  # noqa: E402
    files: list[Path] = [ROOT / 'build/rk3588-example-captures/pooling/manifest.json']
    for case in corpus_cases():
        for base in (ROOT / 'tests/ppu_pooling/fixtures' / case,
                     ROOT / 'build/rk3588-example-captures/pooling/cases' / case):
            for name in ('manifest.json', 'job.json', 'regcmd.bin', 'in.bin',
                         'out_init.bin', 'expected.bin'):
                candidate = base / name
                if candidate.is_file():
                    files.append(candidate)
    return files


def inputs(spec: dict) -> list[Path]:
    files = [ROOT / name for name in spec['sources'] +
             [spec['constraints'], spec['cdc']]]
    files += [SPEC, TEMPLATE, Path(__file__).resolve(),
              ROOT / 'fpga/ppu/build_pool_corpus_synth.tcl.in',
              ROOT / 'fpga/ppu/build_pool_corpus_impl.tcl.in',
              ROOT / spec['generated'][0]['generator']]
    files += corpus_fixture_files()
    files += [ROOT / bench for bench in spec['benches'].values()]
    return files


def render(spec: dict, out: Path, max_threads: int = 2) -> str:
    sources = '\n'.join('read_verilog -sv ' + tcl_path(ROOT / name)
                        for name in spec['sources'])
    text = TEMPLATE.read_text()
    replacements = {
        '@ROOT@': tcl_path(ROOT), '@OUT@': tcl_path(out),
        '@PART@': PART, '@TOP@': TOP, '@BITSTREAM@': BITSTREAM,
        '@N_PAGES@': str(EXPECTED_PAGES), '@MAX_THREADS@': str(max_threads),
        '@CONSTRAINTS@': tcl_path(ROOT / CONSTRAINTS),
        '@CDC@': tcl_path(ROOT / CDC),
        '@READ_SOURCES@': sources,
        '@INCLUDE_DIRS@': ' '.join(tcl_path(ROOT / name) for name in
                                   ('rtl', 'rtl/ppu',
                                    'rtl/vendor/nvidia', 'rtl/vendor/opentpu')),
    }
    allowed = {'@PART@': 2, '@N_PAGES@': 3, '@MAX_THREADS@': 1}
    for token, value in replacements.items():
        if text.count(token) != allowed.get(token, 1):
            raise ValueError(f'Unexpected pooling corpus template token count: {token}')
        text = text.replace(token, value)
    if re.search(r'@[A-Z_]+@', text):
        raise ValueError('Unexpanded Tcl token remains')
    return text


def synth_script(spec: dict, out: Path, max_threads: int = 1) -> str:
    sources = '\n'.join('read_verilog -sv ' + tcl_path(ROOT / name)
                        for name in spec['sources'])
    lines = [
        '# Rendered by tools/ppu/vivado_pool_corpus.py (synth-only fit run).',
        '# Synthesis only: no implementation, no bitstream, no hardware.',
        f'set out {tcl_path(out)}',
        f'create_project -in_memory -part {PART}',
        f'set_property include_dirs [list {tcl_path(ROOT / "rtl")} '
        f'{tcl_path(ROOT / "rtl/ppu")} {tcl_path(ROOT / "rtl/vendor/nvidia")} '
        f'{tcl_path(ROOT / "rtl/vendor/opentpu")}] [current_fileset]',
        'set_property verilog_define {DESIGNWARE_NOEXIST} [current_fileset]',
        sources,
        f'read_xdc {tcl_path(ROOT / CONSTRAINTS)}',
        # Single-threaded synthesis: on this heat-marginal host parallel synth
        # workers spike Tctl past the guard's emergency path. Thread count is a
        # build-tool setting only; it does not change synthesis/utilisation
        # results. Recorded as a run parameter in inputs.json.
        '# Lab-only build-tool setting: thread count does not change synthesis',
        '# utilisation results; it only controls the host thermal ramp.',
        f'set_param general.maxThreads {max_threads}',
        f'synth_design -top {TOP} -part {PART} -generic LED_ACTIVE_LOW=0 '
        f'-generic N_PAGES={EXPECTED_PAGES}',
        'report_utilization -file [file join $out utilization_synth.rpt]',
        'report_utilization -hierarchical -file [file join $out utilization_hier.rpt]',
        'set pages [get_cells -hierarchical -filter "NAME =~ *g_pages*pool_page*"]',
        'puts "LAB_CORPUS_PAGES [llength $pages]"',
        'write_checkpoint -force [file join $out post_synth.dcp]',
        'puts "LAB_DONE"',
    ]
    return '\n'.join(lines) + '\n'


def render_build_synth(spec: dict, out: Path, max_threads: int = 2) -> str:
    """Render the synthesis stage Tcl (checkpoint + pre-implementation gates)."""
    sources = '\n'.join('read_verilog -sv ' + tcl_path(ROOT / name)
                        for name in spec['sources'])
    text = (ROOT / 'fpga/ppu/build_pool_corpus_synth.tcl.in').read_text()
    replacements = {
        '@ROOT@': tcl_path(ROOT), '@OUT@': tcl_path(out),
        '@PART@': PART, '@TOP@': TOP, '@N_PAGES@': str(EXPECTED_PAGES),
        '@MAX_THREADS@': str(max_threads),
        '@CONSTRAINTS@': tcl_path(ROOT / CONSTRAINTS),
        '@CDC@': tcl_path(ROOT / CDC),
        '@READ_SOURCES@': sources,
        '@INCLUDE_DIRS@': ' '.join(tcl_path(ROOT / name) for name in
                                   ('rtl', 'rtl/ppu',
                                    'rtl/vendor/nvidia', 'rtl/vendor/opentpu')),
    }
    allowed = {'@PART@': 2, '@N_PAGES@': 3, '@MAX_THREADS@': 1}
    for token, value in replacements.items():
        if text.count(token) != allowed.get(token, 1):
            raise ValueError(f'Unexpected synth-stage template token count: {token}')
        text = text.replace(token, value)
    if re.search(r'@[A-Z_]+@', text):
        raise ValueError('Unexpanded synth-stage Tcl token remains')
    return text


def render_build_impl(spec: dict, out: Path, checkpoint: Path,
                      max_threads: int = 2) -> str:
    """Render the implementation stage Tcl (checkpoint -> bitstream/gates)."""
    text = (ROOT / 'fpga/ppu/build_pool_corpus_impl.tcl.in').read_text()
    replacements = {
        '@ROOT@': tcl_path(ROOT), '@OUT@': tcl_path(out),
        '@SYNTH_CHECKPOINT@': tcl_path(checkpoint),
        '@MAX_THREADS@': str(max_threads),
        '@CONSTRAINTS@': tcl_path(ROOT / CONSTRAINTS),
        '@CDC@': tcl_path(ROOT / CDC),
        '@BITSTREAM@': BITSTREAM,
    }
    allowed = {'@MAX_THREADS@': 1}
    for token, value in replacements.items():
        if text.count(token) != allowed.get(token, 1):
            raise ValueError(f'Unexpected impl-stage template token count: {token}')
        text = text.replace(token, value)
    if re.search(r'@[A-Z_]+@', text):
        raise ValueError('Unexpanded impl-stage Tcl token remains')
    return text


def _stage_record(spec: dict, mode: str, extra: dict) -> dict:
    record = new_record(spec, mode)
    record['stage'] = mode
    record['run_parameters'] = {
        'general_maxThreads': extra.get('max_threads'),
        'wrapper': 'build/verif/host_guard/safe_run.sh',
        'bench_cpus': os.environ.get('BENCH_CPUS'),
        'bench_cpu_quota': os.environ.get('BENCH_CPU_QUOTA'),
        'note': 'Staged build: synth stage then implementation stage, with a '
                'cooldown gap between them on the heat-marginal host. Thread '
                'count is a build-tool setting and changes no result or gate.',
    }
    if extra.get('checkpoint') is not None:
        checkpoint = extra['checkpoint']
        record['synth_checkpoint'] = str(checkpoint.relative_to(ROOT))
        if checkpoint.is_file():
            record['synth_checkpoint_sha256'] = sha(checkpoint)
    record['source_hashes_before'] = {str(p.relative_to(ROOT)): sha(p)
                                      for p in inputs(spec)}
    record['source_hashes'] = record['source_hashes_before']
    return record


def run_build_synth(out: Path, vivado: str, max_threads: int,
                    render_only: bool) -> int:
    spec = load_spec()
    verify_generated(spec)
    if out.exists():
        raise ValueError('Output already exists; preserve earlier evidence')
    out.mkdir(parents=True, exist_ok=False)
    script = out / 'build_synth.tcl'
    script.write_text(render_build_synth(spec, out, max_threads))
    record = _stage_record(spec, 'build-synth', {'max_threads': max_threads})
    record['synth_thread_setting'] = f'general.maxThreads={max_threads}'
    write_record(out, record)
    if render_only:
        record['status'] = 'RENDERED'
        record['rendered_tcl'] = str(script.relative_to(ROOT))
        write_record(out, record)
        print(script)
        return 0
    argv = [vivado, '-mode', 'batch', '-source', str(script),
            '-log', str(out / 'vivado.log'), '-journal', str(out / 'vivado.jou')]
    started = time.monotonic()
    result = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, check=False)
    (out / 'vivado-stdout.log').write_text(result.stdout)
    record['commands'] = [{'argv': argv, 'returncode': result.returncode,
                           'seconds': round(time.monotonic() - started, 3)}]
    record['vivado_executed'] = True
    failed = result.returncode != 0
    if failed:
        record['failure'] = result.stdout[-4000:]
    else:
        try:
            record['reports'] = parse_synth(out)
            checkpoint = out / 'post_synth.dcp'
            if not checkpoint.is_file():
                raise ValueError('synth stage did not write post_synth.dcp')
            record['post_synth_checkpoint'] = str(checkpoint.relative_to(ROOT))
            record['post_synth_checkpoint_sha256'] = sha(checkpoint)
        except ValueError as error:
            failed = True
            record['failure'] = str(error)
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    failed = finish_source_hashes(record, spec, failed)
    record['status'] = 'FAIL' if failed else 'PASS'
    write_record(out, record)
    return 1 if failed else 0


def run_build_impl(out: Path, vivado: str, checkpoint: Path, max_threads: int,
                   render_only: bool) -> int:
    spec = load_spec()
    verify_generated(spec)
    if not render_only and not checkpoint.is_file():
        raise ValueError(f'missing synth checkpoint: {checkpoint}')
    if out.exists():
        raise ValueError('Output already exists; preserve earlier evidence')
    out.mkdir(parents=True, exist_ok=False)
    script = out / 'build_impl.tcl'
    script.write_text(render_build_impl(spec, out, checkpoint, max_threads))
    record = _stage_record(spec, 'impl', {'max_threads': max_threads,
                                          'checkpoint': checkpoint})
    # The checkpoint must belong to the current image sources: compare with the
    # synth-stage receipt when it sits next to the checkpoint.
    synth_receipt = checkpoint.parent / 'inputs.json'
    if (not render_only) and synth_receipt.is_file():
        synth_record = json.loads(synth_receipt.read_text())
        synth_hashes = synth_record.get('source_hashes_before') or {}
        if synth_hashes and synth_hashes != record['source_hashes_before']:
            raise ValueError('image sources changed between the synth and impl '
                             'stages; rebuild the synth checkpoint')
        record['stage_hashes_match_synth'] = True
    write_record(out, record)
    if render_only:
        record['status'] = 'RENDERED'
        record['rendered_tcl'] = str(script.relative_to(ROOT))
        write_record(out, record)
        print(script)
        return 0
    argv = [vivado, '-mode', 'batch', '-source', str(script),
            '-log', str(out / 'vivado.log'), '-journal', str(out / 'vivado.jou')]
    started = time.monotonic()
    result = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, check=False)
    (out / 'vivado-stdout.log').write_text(result.stdout)
    record['commands'] = [{'argv': argv, 'returncode': result.returncode,
                           'seconds': round(time.monotonic() - started, 3)}]
    record['vivado_executed'] = True
    record['bitstream_emitted'] = (out / BITSTREAM).is_file()
    failed = result.returncode != 0
    if failed:
        record['failure'] = result.stdout[-4000:]
    else:
        try:
            record['reports'] = parse_reports(out)
            if not report_gate_ok(record['reports'], record['bitstream_emitted']):
                failed = True
                record['failure'] = 'Implementation reports failed the physical gate'
        except ValueError as error:
            failed = True
            record['failure'] = str(error)
    if record['bitstream_emitted']:
        record['bitstream_sha256'] = sha(out / BITSTREAM)
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    failed = finish_source_hashes(record, spec, failed)
    record['status'] = 'FAIL' if failed else 'PASS'
    write_record(out, record)
    return 1 if failed else 0


def parse_synth(out: Path) -> dict:
    report = out / 'utilization_synth.rpt'
    if not report.is_file():
        raise ValueError('Missing synthesis utilisation report')
    text = report.read_text()
    luts = re.search(r'\| Slice LUTs\*?\s*\|\s*(\d+)', text)
    regs = re.search(r'\| Slice Registers\s*\|\s*(\d+)', text)
    brams = re.search(r'\| Block RAM Tile\s*\|\s*([0-9.]+)', text)
    return {
        'slice_luts_synth': int(luts.group(1)) if luts else None,
        'slice_registers_synth': int(regs.group(1)) if regs else None,
        'block_ram_tiles_synth': float(brams.group(1)) if brams else None,
    }


def parse_reports(directory: Path) -> dict:
    for name in ('timing.rpt', 'drc.rpt', 'utilization.rpt', 'routed.dcp'):
        if not (directory / name).is_file():
            raise ValueError(f'Missing required implementation report: {name}')
    lines = (directory / 'timing.rpt').read_text().splitlines()
    wns = whs = None
    for index, line in enumerate(lines):
        if line.strip().startswith('WNS(ns)'):
            for row in lines[index + 1:index + 6]:
                columns = row.split()
                if len(columns) >= 6:
                    try:
                        wns, whs = float(columns[0]), float(columns[4])
                    except ValueError:
                        continue
                    break
            break
    if wns is None or whs is None:
        raise ValueError('Could not read WNS/WHS from timing.rpt')
    drc_rows = [line.strip() for line in (directory / 'drc.rpt').read_text().splitlines()
                if re.match(r'^\|\s*[A-Z][A-Z0-9_]+-\d+\s*\|', line)]
    brams = 0
    luts = None
    for line in (directory / 'utilization.rpt').read_text().splitlines():
        if 'RAMB36E1 only' in line:
            brams = int(line.split('|')[2].strip())
        if luts is None:
            match = re.search(r'\| Slice LUTs\*?\s*\|\s*(\d+)', line)
            if match:
                luts = int(match.group(1))
    return {'wns_ns': wns, 'whs_ns': whs, 'drc_rows': drc_rows,
            'ramb36e1': brams, 'slice_luts': luts,
            'timing_met': wns >= 0 and whs >= 0}


def report_gate_ok(reports: dict, bitstream: bool) -> bool:
    if not reports.get('timing_met') or reports.get('ramb36e1', 0) < 1:
        return False
    if reports.get('slice_luts') is None:
        return False
    rows = reports.get('drc_rows', [])
    if any('| Error' in row for row in rows):
        return False
    if bitstream and any('CFGBVS-1' in row for row in rows):
        return False
    return True


def new_record(spec: dict, mode: str) -> dict:
    return {
        'schema': 1, 'status': 'RUNNING', 'mode': mode,
        'profile': spec['profile'], 'top': TOP, 'part': PART,
        'clock_period_ns': CLOCK_NS, 'bitstream': BITSTREAM,
        'pages': EXPECTED_PAGES,
        'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'vivado_executed': False, 'hardware_accessed': False,
        'bitstream_emitted': False,
        'scope': ('Pooling-corpus host-drivable image: USER2 JTAG mailbox frames '
                  'drive an AXI slave with one page per frozen pooling fixture '
                  '(19 READY capture-manifest cases). Synthesis and '
                  'implementation only; no board run, not the complete framework.'),
        'commands': [],
    }


def write_record(out: Path, record: dict) -> None:
    (out / 'inputs.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')


def finish_source_hashes(record: dict, spec: dict, failed: bool) -> bool:
    before = record['source_hashes_before']
    after = {str(p.relative_to(ROOT)): sha(p) for p in inputs(spec)}
    record['source_hashes_after'] = after
    changed = sorted(name for name in set(before) | set(after)
                     if before.get(name) != after.get(name))
    if changed:
        failed = True
        record['source_changed_during_build'] = changed
        record['source_match'] = False
        record['failure'] = ('Source changed during the build, so the image is not '
                             'attributable to the recorded source state: ' +
                             ', '.join(changed))
    else:
        record['source_match'] = True
    return failed


def run_synth(out: Path, vivado: str, max_threads: int = 1) -> int:
    spec = load_spec()
    verify_generated(spec)
    if out.exists():
        raise ValueError('Output already exists; preserve earlier evidence')
    out.mkdir(parents=True, exist_ok=False)
    script = out / 'synth.tcl'
    script.write_text(synth_script(spec, out, max_threads))
    record = new_record(spec, 'synth')
    record['run_parameters'] = {
        'general_maxThreads': max_threads,
        'wrapper': 'build/verif/host_guard/safe_run.sh',
        'bench_cpus': os.environ.get('BENCH_CPUS'),
        'bench_cpu_quota': os.environ.get('BENCH_CPU_QUOTA'),
        'note': 'Lab synth thread count only; it does not change synthesis '
                'utilisation results.',
    }
    record['source_hashes_before'] = {str(p.relative_to(ROOT)): sha(p) for p in inputs(spec)}
    record['source_hashes'] = record['source_hashes_before']
    write_record(out, record)
    argv = [vivado, '-mode', 'batch', '-source', str(script),
            '-log', str(out / 'vivado.log'), '-journal', str(out / 'vivado.jou')]
    started = time.monotonic()
    result = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, check=False)
    (out / 'vivado-stdout.log').write_text(result.stdout)
    record['commands'].append({'argv': argv, 'returncode': result.returncode,
                               'seconds': round(time.monotonic() - started, 3)})
    record['vivado_executed'] = True
    failed = result.returncode != 0
    if failed:
        record['failure'] = result.stdout[-4000:]
    else:
        try:
            record['reports'] = parse_synth(out)
        except ValueError as error:
            failed = True
            record['failure'] = str(error)
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    failed = finish_source_hashes(record, spec, failed)
    record['status'] = 'FAIL' if failed else 'PASS'
    write_record(out, record)
    return 1 if failed else 0


def run_with_vivado(out: Path, vivado: str, max_threads: int = 2) -> int:
    spec = load_spec()
    verify_generated(spec)
    if out.exists():
        raise ValueError('Output already exists; preserve earlier evidence')
    out.mkdir(parents=True, exist_ok=False)
    script = out / 'build.tcl'
    script.write_text(render(spec, out / 'implementation', max_threads))
    record = new_record(spec, 'full')
    record['run_parameters'] = {
        'general_maxThreads': max_threads,
        'wrapper': 'build/verif/host_guard/safe_run.sh',
        'bench_cpus': os.environ.get('BENCH_CPUS'),
        'bench_cpu_quota': os.environ.get('BENCH_CPU_QUOTA'),
        'note': 'Build-tool thread count only; timing/DRC/results unchanged.',
    }
    record['source_hashes_before'] = {str(p.relative_to(ROOT)): sha(p) for p in inputs(spec)}
    record['source_hashes'] = record['source_hashes_before']
    write_record(out, record)
    argv = [vivado, '-mode', 'batch', '-source', str(script),
            '-log', str(out / 'vivado.log'), '-journal', str(out / 'vivado.jou')]
    started = time.monotonic()
    result = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, check=False)
    (out / 'vivado-stdout.log').write_text(result.stdout)
    record['commands'].append({'argv': argv, 'returncode': result.returncode,
                               'seconds': round(time.monotonic() - started, 3)})
    record['vivado_executed'] = True
    record['bitstream_emitted'] = (out / 'implementation' / BITSTREAM).is_file()
    failed = result.returncode != 0
    if failed:
        record['failure'] = result.stdout[-4000:]
    else:
        try:
            record['reports'] = parse_reports(out / 'implementation')
            if not report_gate_ok(record['reports'], record['bitstream_emitted']):
                failed = True
                record['failure'] = 'Implementation reports failed the physical gate'
        except ValueError as error:
            failed = True
            record['failure'] = str(error)
    if record['bitstream_emitted']:
        bit = out / 'implementation' / BITSTREAM
        record['bitstream_sha256'] = sha(bit)
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    failed = finish_source_hashes(record, spec, failed)
    record['status'] = 'FAIL' if failed else 'PASS'
    write_record(out, record)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('render', 'synth', 'run',
                                    'build-synth', 'impl'))
    parser.add_argument('--out', type=Path)
    parser.add_argument('--checkpoint', type=Path,
                        help='post_synth.dcp for the impl stage')
    parser.add_argument('--vivado', default=shutil.which('vivado') or 'vivado')
    parser.add_argument('--render-only', action='store_true',
                        help='render the stage Tcl and receipt without running Vivado')
    parser.add_argument('--max-threads', type=int, default=1,
                        help='Vivado general.maxThreads (thread count does not '
                             'change synthesis/implementation results)')
    args = parser.parse_args()
    out = (args.out or ROOT / 'build/pooling-image' /
           time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())).resolve()
    if not out.is_relative_to(ROOT / 'build'):
        parser.exit(2, 'Output must be below build/\n')
    try:
        spec = load_spec()
        verify_generated(spec)
        if args.action == 'render':
            if out.exists():
                raise ValueError('Output already exists; preserve earlier evidence')
            out.mkdir(parents=True, exist_ok=False)
            script = out / 'build.tcl'
            script.write_text(render(spec, out / 'implementation',
                                     args.max_threads))
            write_record(out, {
                'schema': 1, 'profile': spec['profile'], 'top': TOP,
                'part': PART, 'clock_period_ns': CLOCK_NS,
                'bitstream': BITSTREAM, 'pages': EXPECTED_PAGES,
                'source_hashes': {str(p.relative_to(ROOT)): sha(p) for p in inputs(spec)},
                'vivado_executed': False, 'hardware_accessed': False,
                'bitstream_emitted': False,
            })
            print(script)
            return 0
        if args.action == 'synth':
            return run_synth(out, args.vivado, args.max_threads)
        if args.action == 'build-synth':
            return run_build_synth(out, args.vivado, args.max_threads,
                                   args.render_only)
        if args.action == 'impl':
            if args.checkpoint is None:
                raise ValueError('impl stage needs --checkpoint <synth>/post_synth.dcp')
            return run_build_impl(out, args.vivado, args.checkpoint.resolve(),
                                  args.max_threads, args.render_only)
        return run_with_vivado(out, args.vivado, args.max_threads)
    except ValueError as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
