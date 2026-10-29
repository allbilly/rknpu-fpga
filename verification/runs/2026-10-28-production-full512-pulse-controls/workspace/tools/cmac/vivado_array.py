#!/usr/bin/env python3
"""Prepare or run a source-gated C32/K16 Vivado checkpoint build; never program."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

SPEC = ROOT / 'fpga/cmac/array_sources.json'
TEMPLATE = ROOT / 'fpga/cmac/build_array.tcl.in'

def validate_full_vivado_version(output):
    """Accept the actual full-tool banner while rejecting Lab and partial installs."""
    assert re.search(r'(?im)^\s*vivado\s+v\d+\.\d+(?:\.\d+)?\b', output), \
        f'Unexpected full Vivado version banner: {output!r}'
    assert not re.search(r'\bvivado\s+lab\b', output, re.IGNORECASE), \
        'Vivado Lab is not the full synthesis/implementation tool'

def tcl_path(path):
    value = str(path)
    if any(char in value for char in '{}\\\n\r'):
        raise ValueError('Unsupported Tcl path characters')
    return '{'+value+'}'

def inputs():
    spec = json.loads(SPEC.read_text())
    assert (spec['top'], spec['part'], spec['clock_period_ns'], spec['constraints']) == (
        'ypcb_cmac_array_top', 'xc7k480tffg1156-2', 20, 'fpga/ypcb.xdc')
    paths = [(ROOT / name).resolve() for name in spec['synthesis']]
    assert all(path.is_relative_to(ROOT) and path.is_file() for path in paths)
    paths += [ROOT / spec['constraints'], ROOT / spec['rom']]
    paths += sorted((ROOT / 'tests/cmac/array_data').iterdir())
    paths += [SPEC, TEMPLATE, Path(__file__).resolve(), ROOT / 'tools/cmac/gen_array_board.py', ROOT / 'tools/evidence.py']
    return spec, paths

def render(spec, out, source_sha):
    assert re.fullmatch('[0-9a-f]{64}', source_sha)
    values = {
        '@ROOT@': tcl_path(ROOT), '@OUT@': tcl_path(out), '@SOURCE_SHA@': source_sha,
        '@INCLUDE_DIRS@': ' '.join(tcl_path(ROOT / name) for name in spec['include_dirs']),
        '@READ_SOURCES@': '\n'.join('read_verilog -sv '+tcl_path(ROOT / name) for name in spec['synthesis'])}
    text = TEMPLATE.read_text()
    for token, value in values.items():
        assert text.count(token) == 1, token
        text = text.replace(token, value)
    assert not re.search(r'@[A-Z_]+@', text)
    assert not re.search(r'^\s*(write_bitstream|open_hw|program_hw|set_false_path|set_clock_groups)\b', text, re.M)
    return text

def verify_full_board(path, spec):
    report = json.loads(path.read_text())
    assert report['status'] == 'PASS_RAW_ARRAY_BOARD_FULL_RTL_ONLY', 'A completed FULL board RTL report is required'
    assert report['suite'] == 'full'
    assert len(report['tests']) == 9 and {test['mode'] for test in report['tests']} == set(range(9))
    assert all(test['status'] == 'PASS' for test in report['tests'])
    assert report['commands'] and all(step['status'] == 'PASS' and step['returncode'] == 0 for step in report['commands'])
    assert report['artifacts']['files'], 'Missing board simulation artifacts'
    assert report['tool_version'].startswith('Icarus Verilog '), 'Unexpected board simulator provenance'
    covered = report['source']['files']
    for name in spec['synthesis']+[spec['rom'], spec['constraints'], spec['bench'], str(SPEC.relative_to(ROOT))]:
        assert name in covered, f'Untested build input: {name}'
    for manifest in (report['source'], report['artifacts']):
        for name, sha in manifest['files'].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, f'Stale board evidence: {name}'
    return report

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('prepare', 'run'))
    p.add_argument('--board-report', type=Path)
    p.add_argument('--vivado', default='vivado')
    a = p.parse_args()
    spec, tracked = inputs()
    out = ROOT / f'build/rknpu-array-vivado/{a.action}-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', started_utc=timestamp(), action=a.action, source=fingerprint(tracked), commands=[],
                  bitstream_emitted=False, hardware_programmed=False,
                  implementation_settings={key: os.environ.get(key) for key in
                                           ('RK_CONFIRM_BOARD', 'RK_CONFIG_VOLTAGE', 'RK_CFGBVS', 'RK_LED_ACTIVE_LOW')},
                  scope='Prepared source list or checkpoint-only Vivado implementation, never board validation or automatic signoff. Physical board facts, unconstrained paths and pulse-width review remain mandatory.')
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
    def run(argv, name, env=None):
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name+'.log')).relative_to(ROOT)))
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                proc = subprocess.run(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, env=env, check=False)
            step['returncode'] = proc.returncode
            text = (ROOT / step['log']).read_text()
            assert proc.returncode == 0, text[-6000:]
            step['status'] = 'PASS'
            return text
        except Exception:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic()-started, 3); save()
    save()
    try:
        run([sys.executable, ROOT / 'tools/cmac/gen_array_board.py', '--check'], 'rom_check')
        script = out / 'build.tcl'
        script.write_text(render(spec, out, report['source']['sha256']))
        for path in tracked:
            snapshot = out / 'snapshot' / path.relative_to(ROOT)
            snapshot.parent.mkdir(parents=True, exist_ok=True); snapshot.write_bytes(path.read_bytes())
        if a.action == 'prepare':
            report.update(status='PREPARED_ARRAY_VIVADO_ONLY',
                          prerequisites='No implementation executed. run still requires current full board RTL evidence, full Vivado with exact-part support, and explicit board confirmation.')
        else:
            assert a.board_report is not None, '--board-report is required'
            parent = verify_full_board(a.board_report.resolve(), spec)
            report['board_report'] = parent
            assert os.environ.get('RK_CONFIRM_BOARD') == 'YPCB_00338_1P1', 'Explicit RK_CONFIRM_BOARD required'
            executable = shutil.which(a.vivado)
            assert executable and Path(executable).name == 'vivado', 'UNAVAILABLE: full vivado executable, not Vivado Lab, required'
            report['tool_version'] = run([executable, '-version'], 'version')
            validate_full_vivado_version(report['tool_version'])
            env = dict(os.environ, RK_ARRAY_SOURCE_SHA=report['source']['sha256'])
            run([executable, '-mode', 'batch', '-source', script, '-log', out / 'vivado.log', '-journal', out / 'vivado.jou'], 'implementation', env)
            assert (out / 'routed.dcp').is_file() and not list(out.glob('*.bit'))
            report['status'] = 'ROUTED_ARRAY_CHECKPOINT_REVIEW_REQUIRED'
            verify_full_board(a.board_report.resolve(), spec)
        assert fingerprint(tracked) == report['source'], 'Build inputs changed during run'
        report['artifacts'] = fingerprint([script]+[path for path in out.iterdir() if path.suffix in ('.log', '.jou', '.dcp', '.rpt')])
    except Exception as exc:
        report.update(status='FAIL', reason=str(exc))
        raise
    finally:
        report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
    print(report['status'])

if __name__ == '__main__':
    main()
