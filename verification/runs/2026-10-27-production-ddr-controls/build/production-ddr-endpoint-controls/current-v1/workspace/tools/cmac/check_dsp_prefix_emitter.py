#!/usr/bin/env python3
"""Freeze source-bound prefix emission/admission controls; no Vivado execution."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests/cmac'))
from evidence import ROOT, fingerprint, timestamp
import emit_dsp_prefix_bitstream as emitter


def control_sources():
    pending = [emitter, importlib.import_module('test_emit_dsp_prefix_bitstream')]
    found = {}
    while pending:
        module = pending.pop(); name = getattr(module, '__file__', None)
        if not name: continue
        path = Path(name).resolve()
        if not (path.is_relative_to(ROOT / 'tools') or path.is_relative_to(ROOT / 'tests')) or path in found:
            continue
        found[path] = module
        for value in vars(module).values():
            dependency = value if isinstance(value, ModuleType) else sys.modules.get(getattr(value, '__module__', ''))
            if dependency is not None: pending.append(dependency)
    return sorted(set(found) | {emitter.TEMPLATE, ROOT / 'fpga/cmac/build_array.tcl.in',
        ROOT / 'fpga/cmac/array_sources.json', ROOT / 'fpga/ypcb.xdc', Path(__file__).resolve()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-tclsh', type=Path,
        default=ROOT / 'build/dsp_prefix_vendor_tcl86_20261006.sh')
    args = parser.parse_args()
    system = shutil.which('tclsh')
    assert system, 'UNAVAILABLE: system Tcl'
    vendor = args.vendor_tclsh.resolve()
    tracked = control_sources()
    if vendor.is_file() and vendor.is_relative_to(ROOT): tracked.append(vendor)
    tracked = sorted(set(tracked))
    before = fingerprint(tracked)
    out = ROOT / f'build/rknpu-dsp-prefix-emitter-control/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', started_utc=timestamp(), source_profile=emitter.PROFILE,
        source=before, commands=[], methods_per_interpreter=20, channels=32, kernels=16,
        parallel_products=512, all_vivado_calls_mocked=True, actual_vivado_executed=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Twenty actual Python/Tcl emission/admission-control methods per available runtime. Own-prefix report/profile separation, all four parent revalidation, source/review binding and unchanged physical template plus sixteen 32-DSP kernels. Every Vivado operation mocked; no numerical, electrical, implementation or physical board acceptance.')
    for path in tracked:
        target = out / 'snapshot' / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes())

    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    save()
    try:
        for name, candidate in (('system', Path(system)), ('vendor', vendor)):
            if not candidate.is_file():
                report[name] = 'UNAVAILABLE, not counted as passed'; save(); continue
            env = {k: v for k, v in os.environ.items() if not k.startswith(('RK_', 'MOCK_'))}
            env['RK_TEST_TCLSH'] = str(candidate)
            version = subprocess.run([str(candidate)], input='puts [info patchlevel]\n', text=True,
                capture_output=True, timeout=15, check=True).stdout.strip()
            assert re.fullmatch(r'\d+\.\d+\.\d+', version), 'Invalid Tcl version'
            log = out / (name + '.log')
            argv = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac',
                    '-p', 'test_emit_dsp_prefix_bitstream.py', '-v']
            step = dict(argv=argv, log=str(log.relative_to(ROOT)), interpreter=str(candidate),
                interpreter_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
                runtime_environment={'RK_TEST_TCLSH': str(candidate)}, version=version, status='RUNNING')
            report['commands'].append(step); save(); started = time.monotonic()
            with log.open('w') as stream:
                result = subprocess.run(argv, cwd=ROOT, env=env, stdout=stream,
                    stderr=subprocess.STDOUT, timeout=360)
            text = log.read_text()
            step.update(returncode=result.returncode, seconds=round(time.monotonic() - started, 3))
            assert result.returncode == 0 and re.findall(r'(?m)^Ran (\d+) tests in ', text) == ['20'], text[-6000:]
            assert re.findall(r'(?m)^OK$', text) == ['OK']
            assert not re.search(r'FAILED|skipped=|ERROR|FAIL:|\bskipped\b', text)
            assert 'Tcl ' + version in text and 'Vivado calls MOCKED' in text
            step.update(status='PASS', methods=20); save()
        assert fingerprint(tracked) == before, 'Control sources changed during tests'
        report.update(status='PASS_DSP_PREFIX_BITSTREAM_EMITTER_CONTROL_MOCKS_ONLY',
            artifacts=fingerprint([p for p in out.rglob('*') if p.is_file() and p.name != 'report.json']))
    except BaseException as error:
        if report['commands'] and report['commands'][-1]['status'] == 'RUNNING':
            report['commands'][-1]['status'] = 'FAIL'
        report.update(status='FAIL', reason=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp(); save(); print(out / 'report.json', flush=True)
    print(report['status'], flush=True)


if __name__ == '__main__': main()
