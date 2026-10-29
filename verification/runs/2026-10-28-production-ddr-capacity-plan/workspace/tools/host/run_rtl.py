#!/usr/bin/env python3
"""Run the complete USER2 EW BRAM simulation profile. Never accesses hardware."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from model.dma import DMAEmulator
from model.sim import Memory
from tools.dma_fixtures import production_cases, replay
from tools.evidence import timestamp
from tools.host.qualification import (TOPS, binary_path, build_argv, digest,
                                      fingerprint, run_argv, source_revision, specs,
                                      stimulus_revision, verify_report, verify_stimuli)


def generate(out):
    class PartialMemory(Memory):
        def __init__(self):
            super().__init__()
            self.writes = 0
            self.partial = None

        def write16(self, address, value):
            super().write16(address, value)
            self.writes += 1
            if self.writes == 17:
                self.partial = copy.deepcopy(self.regions)

    def lines(regions):
        result = []
        for address, data in sorted(regions.items()):
            if address % 64 or len(data) % 64:
                raise ValueError('production BO must have whole ordinary-RAM lines')
            for off in range(0, len(data), 64):
                result.append(f'{address+off:08x} {int.from_bytes(data[off:off+64], "little"):0128x}\n')
        return ''.join(result)

    for case in production_cases():
        path = out / 'vectors' / case['name']
        path.mkdir(parents=True)
        expected, _ = replay(case)
        (path / 'upload.txt').write_text(lines(case['regions']))
        (path / 'expected.txt').write_text(lines(expected.regions))
        if case['name'] == 'capture_sub_9':
            mem = PartialMemory()
            for address, data in case['regions'].items():
                mem.map(address, data)
            DMAEmulator(mem, max_tasks=4).submit_dma(case['address'], case['amount'])
            if mem.partial is None:
                raise ValueError('reset corpus did not perform 17 writes')
            (path / 'partial.txt').write_text(lines(mem.partial))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('verilator', 'iverilog'), default='verilator')
    args = parser.parse_args()
    out = ROOT / 'build/host-jtag' / f'{args.simulator}-{time.time_ns()}'
    out.mkdir(parents=True)
    report_path = out / 'report.json'
    report = {'status': 'RUNNING', 'execution_schema': 1, 'started_utc': timestamp(),
              'scope': 'USER2 mailbox and raw EW BRAM simulation only; no BSCANE2 hardware, FPGA, DDR, PCIe or RK silicon proof',
              'execution_root': str(ROOT), 'output_directory': str(out.relative_to(ROOT)),
              'simulator': args.simulator, 'source_revision': source_revision(),
              'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'seeds': {'mailbox': '0x3588c640'}, 'commands': [], 'tests': []}
    artifacts = set()

    def save():
        report_path.write_text(json.dumps(report, indent=2) + '\n')

    def execute(name, argv, timeout=600, **extra):
        log = out / (name + '.log')
        command = {'name': name, 'argv': argv, 'status': 'RUNNING',
                   'log': str(log.relative_to(ROOT))} | extra
        report['commands'].append(command)
        save()
        start = time.monotonic()
        try:
            with log.open('w') as stream:
                result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                        check=False, timeout=timeout)
            command.update(returncode=result.returncode, status='PASS' if result.returncode == 0 else 'FAIL')
        except subprocess.TimeoutExpired:
            command['status'] = 'TIMEOUT'
            raise
        finally:
            command['seconds'] = round(time.monotonic() - start, 3)
            if log.exists():
                artifacts.add(str(log.relative_to(ROOT)))
                command['log_sha256'] = digest(log)
            save()
        text = log.read_text()
        command['warnings'] = [line for line in text.splitlines() if '%Warning' in line or 'warning:' in line.lower()]
        if result.returncode:
            raise RuntimeError(f'{name} failed ({result.returncode}); {log}')
        return text

    save()
    try:
        compiler = shutil.which(args.simulator)
        if compiler is None or (args.simulator == 'iverilog' and shutil.which('vvp') is None):
            report['status'] = 'UNAVAILABLE'
            raise FileNotFoundError(f'{args.simulator} toolchain unavailable')
        compiler = str(Path(compiler).resolve())
        report['compiler'] = {'path': compiler, 'sha256': digest(compiler)}
        report['tool_version'] = execute('version', [compiler, '--version' if args.simulator == 'verilator' else '-V']).splitlines()[0]
        if args.simulator == 'iverilog':
            runtime = str(Path(shutil.which('vvp')).resolve())
            report['runtime'] = {'path': runtime, 'sha256': digest(runtime)}
            execute('runtime_version', [runtime, '-V'])
        generate(out)
        report['stimuli'] = stimulus_revision(str(out.relative_to(ROOT)))
        artifacts.update(str(p.relative_to(ROOT)) for p in (out / 'vectors').rglob('*.txt'))
        save()
        execute('python_transport', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/host', '-p', 'test_transport.py', '-v'])
        execute('python_qualification', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/host', '-p', 'test_qualification.py', '-v'])
        for key in TOPS:
            (out / ('obj_' + key)).mkdir()
            execute('build_' + key, build_argv(args.simulator, compiler, str(ROOT), str(out.relative_to(ROOT)), key))
            binary = binary_path(args.simulator, str(out.relative_to(ROOT)), key)
            artifacts.add(binary)
            report['commands'][-1]['binary'] = {'path': binary, 'sha256': digest(ROOT / binary)}
        for spec in specs():
            binary = binary_path(args.simulator, str(out.relative_to(ROOT)), spec['build'])
            image = {'path': binary, 'sha256': digest(ROOT / binary)}
            if image != next(c['binary'] for c in report['commands'] if c['name'] == 'build_' + spec['build']):
                raise ValueError('image changed after compile')
            text = execute(spec['name'], run_argv(report, spec), binary_before=image)
            after = {'path': binary, 'sha256': digest(ROOT / binary)}
            report['commands'][-1]['binary_after'] = after
            if image != after:
                raise ValueError('image changed while executing')
            results = [line for line in text.splitlines() if line.startswith('PASS ')]
            report['tests'].append({'spec': spec, 'status': 'PASS', 'binary': image, 'results': results})
            print('\n'.join(results), flush=True)
            for p in out.glob(spec['name'] + '_observed.txt*'):
                artifacts.add(str(p.relative_to(ROOT)))
            save()
        if report['source_revision'] != source_revision():
            raise ValueError('source changed during qualification')
        if digest(compiler) != report['compiler']['sha256']:
            raise ValueError('compiler changed during qualification')
        if args.simulator == 'iverilog' and digest(report['runtime']['path']) != report['runtime']['sha256']:
            raise ValueError('runtime changed during qualification')
        verify_stimuli(report)
        report.update(status='PASS', finished_utc=timestamp(), artifacts=fingerprint(artifacts))
        save()
        verify_report(report_path)
    except Exception as exc:
        if report['status'] != 'UNAVAILABLE':
            report['status'] = 'FAIL'
        report.update(reason=str(exc), finished_utc=timestamp())
        if artifacts:
            report['artifacts'] = fingerprint(artifacts)
        save()
        print(f'{report["status"]}: {exc}; report {report_path}', file=sys.stderr)
        return 2 if report['status'] == 'UNAVAILABLE' else 1
    print(report_path, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
