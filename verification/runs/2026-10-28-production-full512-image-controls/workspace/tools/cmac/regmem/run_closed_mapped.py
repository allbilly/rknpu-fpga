#!/usr/bin/env python3
"""Replay the actual closed full512 synthesis netlist without boundary mocks.

Observes the built-in raw K65 numerical scoreboard through the physical top
ports. This is binary functional simulation, not SDF, routed timing, pad voltage,
clock measurement, hardware execution or a general RK3588 equivalence test.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.evidence import timestamp
from tools.cmac.regmem import prove_fast_lut


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--preparation', type=Path, required=True)
    ap.add_argument('--export-report', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--address-space-gib', type=int, choices=(24, 32), default=24)
    ap.add_argument('--validated-lut-model-report', type=Path)
    args = ap.parse_args()
    prep, export_path, out = args.preparation.resolve(), args.export_report.resolve(), args.out.resolve()
    prepared, exported = read(prep/'report.json'), read(export_path)
    require(prepared['status'] == 'PREPARED_UNEXECUTED_CLOSED_MAPPED_STARTUP_DIAGNOSTIC' and
            exported['status'] == 'PASS_READ_ONLY_CLOSED_EXPORT' and exported['exit_code'] == 0,
            'Incomplete or wrong closed export')
    package_report = Path(prepared['package_report'])
    package = package_report.parent
    profile = read(package_report)
    require(profile['status'] == 'PREPARED_REGISTERED_BRAM_FULL512_PIPELINE_SOURCE_ONLY' and
            (profile['channels'], profile['kernels'], profile['parallel_products'], profile['clock_period_ns'])
            == (32, 16, 512, 20), 'Wrong full512 profile')
    require(profile['source']['sha256'] == exported['package_source_sha256'] and
            sha(package_report) == prepared['package_report_sha256'] == exported['package_report_sha256'],
            'Changed source package')
    checkpoint = ROOT/exported['checkpoint']
    require(checkpoint.resolve() == Path(prepared['source_dcp']).resolve() and
            sha(checkpoint) == exported['checkpoint_sha256'], 'Changed synthesis checkpoint')
    for name, expected in profile['source']['files'].items():
        require(sha(package/'source'/name) == expected, 'Changed frozen source '+name)
    net, bench = prep/'closed.v', prep/'tb_closed.sv'
    for name, expected in prepared['files'].items():
        require(sha(prep/name) == expected, 'Changed prepared mapped fixture '+name)
    require(sha(prep/'export.tcl') == exported['export_tcl_sha256'], 'Changed export script')
    require(sha(net) == exported['closed_v_sha256'] ==
            '91d13f62ee3f9260d8c99f831ca1ccb239fc60f9c6dabd9c918f4728c7d6768b',
            'Requires the exact independently reviewed closed export')
    require('module mapped_closed' in net.read_text(), 'Missing actual closed physical top')
    proof_files = []
    proof_binding = None
    if args.validated_lut_model_report is not None:
        proof_path = args.validated_lut_model_report.resolve()
        proof = read(proof_path)
        require(proof['status'] == 'PASS_ALL_CONFIGURED_LUTS_EXHAUSTIVE_4STATE' and
                proof['original_netlist_sha256'] == sha(net), 'Missing exact configured LUT proof')
        for name, expected in proof['inputs'].items():
            require(sha(name) == expected, 'Changed LUT proof source/image '+name)
        for name, expected in proof['artifacts'].items():
            require(sha(proof_path.parent/name) == expected, 'Changed LUT proof artifact '+name)
        transformed, _, _, inventory = prove_fast_lut.derive(net.read_text())
        require(read(proof_path.parent/'inventory.json') ==
                {str(n): [f'{v:x}' for v in vs] for n, vs in inventory.items()}, 'Incomplete LUT INIT coverage')
        total = sum(len(values)*4**n for n, values in inventory.items())
        require(proof['comparisons'] == total == 3419904 and
                proof['configurations'] == {str(n): len(values) for n, values in inventory.items()},
                'Incomplete configured four-state coverage')
        expected_names = ['iverilog_version', 'vvp_version', 'compile', 'wrong_output_control', 'actual']
        require([c['name'] for c in proof['commands']] == expected_names, 'Changed proof command sequence')
        for command in proof['commands']:
            require(command['status'] == 'PASS' and
                    ((command['returncode'] != 0) if command['name'] == 'wrong_output_control'
                     else (command['returncode'] == 0)), 'LUT proof command did not pass')
            require(sha(proof_path.parent/(command['name']+'.log')) == command['log_sha256'], 'Proof log changed')
        marker = 'PASS exact_configured_LUT_4state configs=1224 comparisons=3419904 initial_event=1'
        require(proof['result'] == marker and
                [line for line in (proof_path.parent/'actual.log').read_text().splitlines()
                 if line.startswith('PASS ')] == [marker], 'Proof result differs')
        require('fast LUT mismatch case=0 pattern=0' in
                (proof_path.parent/'wrong_output_control.log').read_text(), 'Missing wrong-output control')
        replacement = Path(proof['derived_netlist'])
        require(replacement.read_text() == transformed and sha(replacement) == proof['derived_netlist_sha256'],
                'Derived simulation netlist changes more than the proved LUT bodies')
        proof_files = [proof_path, Path(prove_fast_lut.__file__), net]
        proof_files += [Path(name) for name in proof['inputs']]
        proof_files += [proof_path.parent/name for name in proof['artifacts']]
        proof_binding = dict(report=str(proof_path), sha256=sha(proof_path),
            original_netlist_sha256=sha(net), derived_netlist_sha256=sha(replacement),
            configurations=proof['configurations'], comparisons=total,
            scope='Only LUT4/5/6 behavioral bodies have exhaustive configured four-state equivalence; all other mapped text/models unchanged')
        net = replacement
    harness = ROOT/'build/regmem-closed-mapped-harness-controls/report.json'
    controls = read(harness)
    require(controls['status'] == 'PASS_SIX_CLOSED_TOP_HARNESS_CONTROLS_ONLY' and
            controls['inputs'][str(bench)] == sha(bench), 'Missing current bench controls')
    for command in controls['commands']:
        require(command['status'] == 'PASS_CONTROL' and
                (command['returncode'] == 0) == command['expected_zero'] and
                sha(harness.parent/(command['name']+'.log')) == command['log_sha256'],
                'Harness control/log changed')
    require(out.is_relative_to(ROOT/'build') and not out.exists(), 'Fresh build output required')
    memory = {line.split(':')[0]: int(line.split()[1])*1024
              for line in Path('/proc/meminfo').read_text().splitlines()}
    ceiling = args.address_space_gib*1024**3
    require(memory['MemAvailable']+memory['SwapFree'] >= ceiling+4*1024**3,
            'Insufficient available memory/swap plus 4-GiB reserve for requested compile profile')
    out.mkdir(parents=True)
    # Preserve the exact producer even after later source work. The live file
    # also stays bound throughout this run, so an in-flight edit cannot pass.
    producer = out/'producer-source.py'
    shutil.copyfile(Path(__file__), producer)
    compiler, runtime = shutil.which('iverilog'), shutil.which('vvp')
    require(compiler is not None and runtime is not None, 'Icarus tools unavailable')
    files = [Path(__file__), producer, ROOT/'tools/evidence.py', prep/'report.json',
             export_path, prep/'export.tcl', package_report, checkpoint, net, bench,
             harness, Path(compiler).resolve(), Path(runtime).resolve(), *proof_files]
    inputs = {str(path): sha(path) for path in files}
    report = dict(status='RUNNING_ACTUAL_CLOSED_FULL512_MAPPED_REPLAY', started_utc=timestamp(),
        scope=__doc__, source_sha256=profile['source']['sha256'], inputs=inputs,
        channels=32, kernels=16, parallel_products=512, clock_period_ns=20,
        simulator='iverilog', compile_address_space_limit_bytes=ceiling,
        resource_admission=dict(memory_available_bytes=memory['MemAvailable'], swap_free_bytes=memory['SwapFree'],
                                reserve_bytes=4*1024**3, requested_address_space_gib=args.address_space_gib),
        compile_timeout_seconds=1800, simulation_timeout_seconds=7200,
        delay_selection='Explicit -Ttyp preserves default typical functional-model delays; no SDF',
        seed='No PRNG; frozen raw K65/4096-halfword ROM workload',
        checker_control='Deliberately inverted PASS predicate; not DUT/ROM corruption injection',
        validated_lut_model=proof_binding,
        commands=[], bitstream_emitted=False, hardware_accessed=False, image_admission=False)

    def save():
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')

    def execute(name, argv, limit):
        require(all(sha(p) == expected for p, expected in inputs.items()), 'Mapped input changed')
        entry = dict(name=name, argv=list(map(str, argv)), status='RUNNING', started_utc=timestamp())
        report['commands'].append(entry)
        child = None
        start = time.monotonic()
        save()
        try:
            with (out/(name+'.log')).open('w') as log:
                old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
                try:
                    child = subprocess.Popen(entry['argv'], cwd=out, stdout=log, stderr=subprocess.STDOUT,
                        start_new_session=True, preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, old))
                finally:
                    signal.pthread_sigmask(signal.SIG_SETMASK, old)
                entry['pid'] = child.pid
                save()
                code = child.wait(timeout=limit)
            entry.update(returncode=code, status='FINISHED')
            require(all(sha(p) == expected for p, expected in inputs.items()), 'Mapped input changed during execution')
            return code, (out/(name+'.log')).read_text()
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
            entry.update(seconds=time.monotonic()-start, finished_utc=timestamp())
            entry['log_sha256'] = sha(out/(name+'.log'))
            save()

    def interrupt(signum, frame):
        raise InterruptedError('Closed mapped replay interrupted '+str(signum))

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupt)
    resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    save()
    try:
        for label, tool in [('compiler', compiler), ('runtime', runtime)]:
            code, text = execute(label+'_version', [tool, '-V'], 30)
            require(code == 0, 'Missing mapped tool version')
            report[label+'_version'] = text.splitlines()[0]
            report['commands'][-1]['status'] = 'PASS'
        image = out/'sim.vvp'
        code, text = execute('compile', [compiler, '-g2012', '-Ttyp', '-s', 'tb_closed', '-s', 'glbl',
            '-o', image, net, bench], 1800)
        require(code == 0 and not re.search(r'(?mi)warning:|error:|sorry:', text), 'Closed mapped compile failed/diagnostics')
        report['commands'][-1]['status'] = 'PASS'
        report['compiled_image'] = dict(path=str(image), sha256=sha(image))
        inputs[str(image)] = sha(image)
        for label, negative in [('actual', 0), ('inverted_checker', 1)]:
            code, text = execute(label, [runtime, image, '+NEGATIVE='+str(negative)], 7200)
            if negative:
                require(code != 0 and 'deliberately inverted closed-top checker rejects PASS' in text and
                        not re.search(r'(?m)^PASS ', text), 'Closed checker control did not reject')
            else:
                lines = [line for line in text.splitlines() if line.startswith('PASS ')]
                require(code == 0 and len(lines) == 1 and
                        re.fullmatch(r'PASS closed_mapped_full512_startup pad_pass=1 pad_fail=0 stable_cycles=32 observed_cycles=[0-9]+', lines[0])
                        and not re.search(r'(?mi)FATAL:|ERROR:|WARNING:', text), 'Closed mapped startup result differs')
                report['result'] = lines[0]
            report['commands'][-1]['status'] = 'PASS'
            save()
        report.update(status=('PASS_ACTUAL_CLOSED_FULL512_MAPPED_STARTUP_WITH_PROVEN_LUT_MODEL_ONLY'
                              if proof_binding else 'PASS_ACTUAL_CLOSED_FULL512_MAPPED_STARTUP_ONLY'),
                      finished_utc=timestamp())
    except BaseException as error:
        report.update(status='FAIL', error=str(error), finished_utc=timestamp())
        if report['commands'] and report['commands'][-1]['status'] == 'FINISHED':
            report['commands'][-1].update(status='FAIL', error=str(error))
        raise
    finally:
        report['artifacts'] = {path.name: sha(path) for path in out.iterdir()
                               if path.is_file() and path.name != 'report.json'}
        save()
    print(out/'report.json')


if __name__ == '__main__':
    main()
