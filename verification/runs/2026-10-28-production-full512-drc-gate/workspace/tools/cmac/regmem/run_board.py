#!/usr/bin/env python3
"""Fresh raw K65 startup regression for a frozen registered-BRAM package.

Preserves the original startup bench, counters, error expectations and modes.
No Vivado, bitstream or hardware operation is performed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.cmac.startup import qualification as q
from tools.cmac.regmem.warnings import reviewed_warnings
from tools.evidence import timestamp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator'), required=True)
    parser.add_argument('--polarity', type=int, choices=(0, 1), default=0)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    package = args.package.resolve()
    record = json.loads((package/'report.json').read_text())
    q.require(record['status'] == 'PREPARED_REGISTERED_BRAM_FULL512_PIPELINE_SOURCE_ONLY', 'Wrong package')
    q.require((record['channels'], record['kernels'], record['parallel_products'], record['clock_period_ns'])
              == (32, 16, 512, 20), 'Wrong full target')
    snapshot = package/'source'
    for name, sha in record['source']['files'].items():
        q.require(q.digest(q.safe(snapshot, name)) == sha, 'Changed snapshot: '+name)
    bench = q.safe(snapshot, q.BENCH)
    original_bench=(ROOT/q.BENCH).read_text()
    q.require(original_bench.count('ypcb_cmac_array_startup_top #')==1,'Original bench changed')
    q.require(bench.read_text()==original_bench.replace('ypcb_cmac_array_startup_top #','ypcb_cmac_array_regmem_top #'),
              'Changed numeric/fault/startup assertions in the derived board bench')
    out = args.out.resolve()
    q.require(out.is_relative_to(ROOT/'build') and not out.exists(), 'Fresh build output required')
    out.mkdir(parents=True)
    selected = [n for n in record['synthesis_sources'] if n.endswith(('.sv', '.v'))]
    selected += ['rtl/vendor/nvdla/compat/nv_assert_never.v',
                 'rtl/vendor/nvdla/compat/nv_assert_no_x.v']
    q.require(len(selected) == len(set(selected)), 'Duplicate source definitions')
    inputs = {str(package/'source'/n): q.digest(snapshot/n) for n in selected+[q.BENCH]}
    inputs.update({str(snapshot/n): sha for n, sha in record['source']['files'].items()
                   if n.startswith('tests/cmac/array_data/')})
    inputs[str(ROOT/'tools/cmac/startup/qualification.py')] = q.digest(q.__file__)
    inputs[str(ROOT/'tools/cmac/regmem/warnings.py')] = q.digest(ROOT/'tools/cmac/regmem/warnings.py')
    inputs[str(Path(__file__).resolve())] = q.digest(__file__)
    report = dict(status='RUNNING', started_utc=timestamp(),
        profile='full512-registered-bram-startup-native', simulator=args.simulator,
        polarity=args.polarity, package=str(package), package_report_sha256=q.digest(package/'report.json'),
        channels=32, kernels=16, parallel_products=512, inputs=inputs,
        scope='Original raw K65/whole4096-halfword startup/fault/abort bench on frozen registered-BRAM-control source; configuration model only',
        commands=[], tests=[], hardware_programmed=False, mapped_startup_verified=False)

    def save():
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')

    def execute(name, argv, timeout=900):
        q.require(all(q.digest(p) == h for p, h in inputs.items()), 'Startup input changed')
        entry = dict(name=name, argv=list(map(str, argv)), status='RUNNING', started_utc=timestamp())
        report['commands'].append(entry)
        save()
        child = None
        begin = time.monotonic()
        try:
            with (out/(name+'.log')).open('w') as log:
                blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
                previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
                try:
                    child = subprocess.Popen(entry['argv'], cwd=snapshot, stdout=log,
                        stderr=subprocess.STDOUT, start_new_session=True,
                        preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, previous))
                finally:
                    signal.pthread_sigmask(signal.SIG_SETMASK, previous)
                entry['pid'] = child.pid
                save()
                code = child.wait(timeout=timeout)
            entry['returncode'] = code
            q.require(code == 0, name+' failed')
            text = (out/(name+'.log')).read_text()
            q.require(all(q.digest(p) == h for p, h in inputs.items()), 'Startup source changed during execution')
            entry['status'] = 'PASS'
            return text
        except BaseException as error:
            entry.update(status='FAIL', error=str(error))
            if child is not None and child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            raise
        finally:
            entry.update(finished_utc=timestamp(), seconds=time.monotonic()-begin)
            log = out/(name+'.log')
            if log.exists():
                entry['log_sha256'] = q.digest(log)
            save()

    def interrupt(signum, frame):
        raise InterruptedError('Startup qualification interrupted: '+str(signum))

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, interrupt)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        compiler = args.simulator
        report['tool_version'] = execute('version', [compiler,
            '-V' if compiler == 'iverilog' else '--version'], 30).splitlines()[0]
        files = [str(snapshot/n) for n in selected]+[str(bench)]
        defines = ['-DDESIGNWARE_NOEXIST', '-DASSERT_ON', '-I'+str(snapshot/'rtl/vendor/nvdla')]
        expected = {'rk_cmac_fp16_array_dsp_prefix_pipe': 1,
                    'rk_cmac_fp16_cell_dsp_prefix_pipe': 16,
                    'rk_cmac_fp16_lane_dsp_prefix': 512, 'rk_cmac_fp16_discarded_carry': 512}
        # Reuse the established hierarchy parser, with the two explicitly
        # selected candidate module names. Product/lane counts are unchanged.
        q.EXPECTED_HIERARCHY = expected
        if compiler == 'iverilog':
            image = out/'sim.vvp'
            report['runtime_version'] = execute('runtime_version', ['vvp', '-V'], 30).splitlines()[0]
            text = execute('compile', [compiler, '-g2012', *defines, '-s', 'tb_array_startup',
                '-Ptb_array_startup.LED_ACTIVE_LOW='+str(args.polarity), '-o', str(image), *files], 1200)
            q.require(not re.search(r'(?mi)\b(?:warning|error):|sorry:', text), 'Unadmitted Icarus diagnostic')
            report['hierarchy'] = q.hierarchy_vvp(image.read_text())
            launch = ['vvp', str(image)]
        else:
            flags = ['--timing', '--assert', '-Wall', '-Wno-fatal', '--timescale-override', '1ns/1ps',
                *defines, '--top-module', 'tb_array_startup', '-GLED_ACTIVE_LOW='+str(args.polarity)]
            tree = out/'hierarchy.tree.json'
            text = execute('hierarchy', [compiler, '--json-only', *flags, '--Mdir', str(out/'obj'),
                '--json-only-output', str(tree), '--json-only-meta-output', str(out/'hierarchy.meta.json'), *files], 300)
            report['hierarchy_warning_locations'] = reviewed_warnings(text, snapshot, compilation=False)
            report['hierarchy'] = q.hierarchy_json(tree)
            text = execute('compile', [compiler, '--binary', *flags, '-j', '1', '--Mdir', str(out/'obj'),
                '-o', 'sim', *files], 1200)
            report['compile_warning_locations'] = reviewed_warnings(text, snapshot, compilation=True)
            image = out/'obj/sim'
            launch = [str(image)]
        binding = dict(path=str(image), sha256=q.digest(image))
        report['compiled_image'] = binding
        for spec in [s for s in q.specs(args.simulator) if s['polarity'] == args.polarity]:
            q.require(q.digest(image) == binding['sha256'], 'Compiled image changed')
            text = execute(spec['name'], launch+['+MODE='+str(spec['mode'])])
            result = q.validate_result(text, spec)
            q.require(q.digest(image) == binding['sha256'], 'Run image changed')
            report['tests'].append(dict(spec=spec, status='PASS', result=result))
            print(result, flush=True)
            save()
        report.update(status='PASS_REGISTERED_BRAM_FULL512_STARTUP_NATIVE_ONLY', finished_utc=timestamp())
    except BaseException as error:
        report.update(status='FAIL', error=str(error), finished_utc=timestamp())
        raise
    finally:
        report['artifacts'] = {str(p.relative_to(out)): q.digest(p) for p in out.iterdir()
                               if p.is_file() and p.name != 'report.json'}
        save()
    print(out/'report.json')


if __name__ == '__main__':
    main()
