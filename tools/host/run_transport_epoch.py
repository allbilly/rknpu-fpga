#!/usr/bin/env python3
"""Run strict standalone retained-UI PCIe epoch guard controls in Icarus and Verilator."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.owned_process import run_owned
RTL = ROOT / 'rtl/host/rk_transport_epoch_guard.sv'
BENCH = ROOT / 'tests/host/frame_epoch/tb_transport_epoch_guard.sv'
WARNING_RE = re.compile(r'(?im)(?:%Warning(?:-|:)|\bwarning:|\bsorry:)')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = (args.out if args.out else ROOT / 'build/frame-epoch-controls-v1' / stamp).resolve()
    out.mkdir(parents=True, exist_ok=False)
    owned_helper = ROOT / 'tools/owned_process.py'
    sources = [RTL, BENCH, Path(__file__).resolve(), owned_helper]
    before = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()
    dirty = bool(subprocess.run(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT,
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout)
    report = {
        'status': 'RUNNING', 'started_utc': datetime.now(timezone.utc).isoformat(),
        'source_revision': revision, 'workspace_dirty': dirty,
        'source_hashes_before': before, 'source_hashes_after': None,
        'scope': 'Standalone retained-UI transport epoch guard and dummy independent-JTAG progress only; no CDC, PCIe IP, physical shell, board or hardware qualification.',
        'stimulus': 'Directed deterministic values and exact edge counts; no PRNG or random seed.',
        'seed': None, 'hardware_accessed': False, 'network_accessed': False,
        'vivado_executed': False, 'ram_caps_imposed': False,
        'commands': [], 'tools': {}, 'positive_runs': [], 'invalid_parameter_runs': [],
    }
    report_path = out / 'report.json'

    def save():
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(name, argv, cwd=out, timeout=120):
        log = out / (name + '.log')
        started = time.monotonic()
        with log.open('xb') as stream:
            try:
                result = run_owned(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                   timeout=timeout)
            except BaseException as error:
                cleanup = getattr(error, 'owned_process_cleanup', {})
                row = {'name': name, 'argv': list(map(str, argv)), 'returncode': None,
                       'timed_out': False, 'status': 'EXCEPTION', 'timeout_seconds': timeout,
                       'seconds': time.monotonic() - started, 'log': str(log),
                       'log_sha256': sha(log), 'pid': cleanup.get('pid'), 'pgid': cleanup.get('pgid'),
                       'live_before_cleanup': cleanup.get('live_before_cleanup'),
                       'live_after_cleanup': cleanup.get('live_after_cleanup'), 'exception': repr(error)}
                report['commands'].append(row)
                save()
                raise
        text = log.read_text(errors='replace')
        row = {'name': name, 'argv': list(map(str, argv)), 'returncode': result.returncode,
               'timed_out': result.timed_out,
               'status': 'PASS' if result.returncode == 0 and not result.timed_out else 'NONZERO_EXIT',
               'timeout_seconds': timeout,
               'seconds': time.monotonic() - started, 'log': str(log),
               'log_sha256': sha(log), 'pid': result.pid, 'pgid': result.pid,
               'live_before_cleanup': list(result.live_before_cleanup),
               'live_after_cleanup': list(result.live_after_cleanup)}
        report['commands'].append(row)
        save()
        need(not result.timed_out and not result.live_before_cleanup and not result.live_after_cleanup,
             name + ' timed out or left an owned process-group descendant')
        return row, text

    def compile_one(sim, tool, tag, fresh):
        if sim == 'iverilog':
            image = out / (tag + '.vvp')
            argv = [tool, '-g2012', '-Wall', '-s', 'tb_transport_epoch_guard',
                    f'-Ptb_transport_epoch_guard.FRESH_CYCLES={fresh}', '-o', str(image),
                    str(RTL), str(BENCH)]
        else:
            image_dir = out / (tag + '_obj')
            image = image_dir / (tag + '_sim')
            argv = [tool, '--binary', '--timing', '--assert', '-Wall', '-j', '2',
                    '--top-module', 'tb_transport_epoch_guard', '--Mdir', str(image_dir),
                    '-o', tag + '_sim', f'-GFRESH_CYCLES={fresh}', str(RTL), str(BENCH)]
        row, text = run(tag + '_compile', argv, timeout=180)
        need(row['returncode'] == 0 and not row['timed_out'], tag + ' compile failed')
        need(not WARNING_RE.search(text), tag + ' compile emitted a warning/unsupported diagnostic')
        need(image.is_file(), tag + ' compile did not create image')
        row['image'] = str(image)
        row['image_sha256'] = sha(image)
        return image, row

    def execute_positive(sim, tool, vvp, fresh):
        tag = f'{sim}_fresh{fresh}'
        image, compile_row = compile_one(sim, tool, tag, fresh)
        argv = [vvp, str(image)] if sim == 'iverilog' else [str(image)]
        row, text = run(tag + '_run', argv, timeout=30)
        need(row['returncode'] == 0 and not row['timed_out'], tag + ' simulation failed')
        markers = re.findall(r'^PASS_TRANSPORT_EPOCH_GUARD fresh=(\d+) checks=(\d+) z_four_state=(\d+) stimulus=directed_no_prng$', text, re.M)
        need(len(markers) == 1 and markers[0][0] == str(fresh) and markers[0][2] == ('1' if sim == 'iverilog' else '0'), tag + ' missing exact completion marker/four-state scope')
        need(sha(image) == compile_row['image_sha256'], tag + ' simulator image changed during run')
        report['positive_runs'].append({'simulator': sim, 'fresh_cycles': fresh,
            'checks': int(markers[0][1]), 'z_four_state_tested': markers[0][2] == '1', 'compile_log_sha256': compile_row['log_sha256'],
            'run_log_sha256': row['log_sha256'], 'image': str(image),
            'image_sha256': compile_row['image_sha256'], 'completion_marker': text.splitlines()[0]})
        save()

    def execute_invalid(sim, tool, vvp, fresh):
        tag = f'{sim}_invalid_fresh{fresh}'
        image, compile_row = compile_one(sim, tool, tag, fresh)
        argv = [vvp, str(image)] if sim == 'iverilog' else [str(image)]
        row, text = run(tag + '_run', argv, timeout=15)
        expected = 'Invalid transport epoch freshness parameter'
        need(row['returncode'] != 0 and not row['timed_out'], tag + ' did not fail as intended')
        need(expected in text and 'INVALID_PARAMETER_DUT_DID_NOT_FAIL' not in text and
             'GLOBAL_TEST_TIMEOUT' not in text, tag + ' did not fail at the DUT invalid-parameter gate')
        row['status'] = 'EXPECTED_FAILURE'
        save()
        report['invalid_parameter_runs'].append({'simulator': sim, 'fresh_cycles': fresh,
            'compile_log_sha256': compile_row['log_sha256'], 'run_log_sha256': row['log_sha256'],
            'expected_diagnostic': expected, 'returncode': row['returncode']})
        save()

    save()
    try:
        for sim in ('iverilog', 'verilator'):
            tool = shutil.which(sim)
            need(tool is not None, 'UNAVAILABLE: ' + sim)
            version_args = ['-V'] if sim == 'iverilog' else ['--version']
            version_row, version_text = run(sim + '_version', [tool, *version_args], timeout=30)
            need(version_row['returncode'] == 0, sim + ' version query failed')
            info = {'path': tool, 'binary_sha256': sha(Path(tool).resolve()),
                    'version': version_text.splitlines()[0]}
            if sim == 'iverilog':
                vvp = shutil.which('vvp')
                need(vvp is not None, 'UNAVAILABLE: vvp')
                vr, vt = run('vvp_version', [vvp, '-V'], timeout=30)
                need(vr['returncode'] == 0, 'vvp version query failed')
                info['vvp'] = {'path': vvp, 'binary_sha256': sha(Path(vvp).resolve()),
                               'version': vt.splitlines()[0]}
            else:
                vvp = None
            report['tools'][sim] = info
            for fresh in (4, 2):
                execute_positive(sim, tool, vvp, fresh)
            for fresh in (0, 1, 65537):
                execute_invalid(sim, tool, vvp, fresh)
        after = {str(path.relative_to(ROOT)): sha(path) for path in sources}
        need(after == before, 'Bound source changed during guard controls')
        need(len(report['positive_runs']) == 4 and len(report['invalid_parameter_runs']) == 6,
             'Incomplete two-simulator freshness/invalid-parameter matrix')
        report.update(status='PASS_TRANSPORT_EPOCH_GUARD_STANDALONE_NATIVE_ONLY',
                      source_hashes_after=after, finished_utc=datetime.now(timezone.utc).isoformat())
    except BaseException as error:
        report.update(status='FAIL_TRANSPORT_EPOCH_GUARD_STANDALONE_NATIVE_ONLY', error=repr(error),
                      finished_utc=datetime.now(timezone.utc).isoformat())
        save()
        raise
    save()
    print(json.dumps({'status': report['status'], 'report': str(report_path),
                      'positive_runs': len(report['positive_runs']),
                      'invalid_parameter_runs': len(report['invalid_parameter_runs'])}, sort_keys=True))


if __name__ == '__main__':
    main()
