#!/usr/bin/env python3
"""Fresh full C32/K16 placement with qualified bounded strict-search engine.

Repack the exact prepared 512-product physical input with the corrected DSP
encoder; never reload an old incomplete placement or invent macro state.
The old six-hour timeout remains FAIL. This attempt allows twelve hours of
host computation, not a relaxed FPGA clock or waived native validity gate.
No routing, physical fit/timing/electrical/DRC signoff, bitstream or hardware
programming is claimed. No SHA256SUMS file is written.
"""
import argparse
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qualify_strict_search_rounds import verify_qualification, check_strict_log
from place_prefix_board import (PACK_PARENT, verify_packed_metadata, bind_report, verify_bindings,
                               placement_argv, verify_placed_module)
from pack_prefix_board import (ROOT, digest, timestamp, packing_xdc, native_export_module, verify_prepared_metadata)
from evidence import source_revision

FAILED = ROOT / 'build/openxc7/full-prefix-native-place-1791403059242726617/report.json'
CONTROL = ROOT / 'tests/cmac/test_strict_search_board.py'
NATIVE_TIMEOUT = 43200
PLACED = 'PLACED_FULL_C32K16_CORRECTED_DSP_BOUNDED_SEARCH_NATIVE_LEGALITY_NOT_ROUTED_FIT_OR_SIGNOFF'
FLAGS = ('native_routing_executed', 'numerical_netlist_acceptance', 'physical_fit_verified', 'timing_signoff',
         'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed', 'old_placement_reused')


def verify_previous_failure(report):
    assert report['status'] == 'FAIL' and report['stage'] == 'native_place' and report['finished_utc']
    assert report['parallel_products'] == 512 and report['channels'] == 32 and report['kernels'] == 16
    assert report['intended_part'] == 'xc7k480tffg1156-2' and report['intended_clock_period_ns'] == 20
    last = report['commands'][-1]
    assert last['status'] == 'FAIL' and last['returncode'] == -9 and last['timeout_seconds'] == 21600
    assert last['seconds'] >= 21600 and report['error'].startswith('TimeoutExpired(')
    for key in ('native_routing_executed', 'numerical_netlist_acceptance', 'physical_fit_verified', 'timing_signoff',
                'electrical_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[key] is False


def verify_full_argv(argv):
    for key, value in (('--device', 'xc7k480tffg1156-2'), ('--freq', '50'), ('--seed', '3588'), ('--placer', 'static')):
        assert argv.count(key) == 1 and argv[argv.index(key) + 1] == value
    assert '--no-route' in argv and '--Werror' in argv
    for key in ('--no-pack', '--no-place', '--force', '--timing-allow-fail', '--placer-static-refine-max-iterations'):
        assert key not in argv, 'Unadmitted shortcut: ' + key


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--qualification', type=Path, required=True)
    args = parser.parse_args(); qualification = args.qualification.resolve(strict=True)
    assert qualification.is_relative_to(ROOT / 'build/openxc7')
    out = ROOT / f'build/openxc7/full-prefix-bounded-search-place-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py'); shutil.copyfile(CONTROL, out / 'executed_control_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        scope=__doc__, source={}, commands=[], channels=32, kernels=16, parallel_products=512,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588,
        native_packing_executed=False, native_placement_executed=False, original_prepared_input_repacked=False,
        packed_context_reloaded=False, previous_failed_report=str(FAILED), previous_timeout_relabelled=False,
        qualified_engine_report=str(qualification), host_native_timeout_seconds=NATIVE_TIMEOUT,
        previous_host_timeout_seconds=21600, FPGA_clock_period_changed=False,
        production_source_before=source_revision(), **{key: False for key in FLAGS})
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, timeout):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')), cwd=str(ROOT),
            expected_returncode=0, timeout_seconds=timeout, status='RUNNING')
        report['commands'].append(step); save(); start = time.monotonic()
        def limits():
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            resource.setrlimit(resource.RLIMIT_AS, (12 * 1024 ** 3, 12 * 1024 ** 3))
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True, preexec_fn=limits) as process:
                step['pid'] = process.pid; save()
                try: code = process.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(); step['returncode'] = process.returncode; raise
            step['returncode'] = code; text = Path(step['log']).read_text()
            assert code == 0 and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text), text[-4000:]
            if label == 'native_place':
                for marker in ('Running Static placer...', 'Running simulated annealing placer for refinement.',
                               'Running post-placement legalisation...', 'Program finished normally.'):
                    assert marker in text, 'Missing normal full-placement completion: ' + marker
                assert 'Static refinement iteration limit:' not in text
                step['search_progress'] = check_strict_log(text)
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'; return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3); save()
    print(out / 'report.json', flush=True); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        candidate, before = verify_qualification(qualification)
        previous = json.loads(FAILED.read_text()); verify_previous_failure(previous)
        assert not (FAILED.parent / 'placed.json').exists(), 'Prior timed-out attempt has unexpected output'
        bind_report(FAILED, previous, before)
        packed = json.loads(PACK_PARENT.read_text()); verify_packed_metadata(packed); bind_report(PACK_PARENT, packed, before)
        prepared_path = (ROOT / packed['prepared_report']).resolve(strict=True)
        assert str(prepared_path) in before and prepared_path.is_relative_to(ROOT / 'build/openxc7')
        prepared = json.loads(prepared_path.read_text()); verify_prepared_metadata(prepared); bind_report(prepared_path, prepared, before)
        assert set(prepared['retained_kernel_instances']) == set(packed['retained_kernel_dsps'])
        files = {Path(__file__).resolve(), CONTROL, Path(sys.executable).resolve()}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
            if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for path in files:
            sha = digest(path); assert str(path) not in before or before[str(path)] == sha
            before[str(path)] = sha
        verify_bindings(before)
        assert candidate['production_source_after'] == report['production_source_before']
        executable = candidate['executable']['path']
        report.update(source=before, executable=candidate['executable'], native_version=candidate['native_version'],
            packed_report=str(PACK_PARENT), prepared_report=str(prepared_path), stage='software_controls',
            software_runtime=dict(executable=str(Path(sys.executable).resolve()), version=sys.version),
            changed_static_placer_object=1, corrected_DSP_encoder_preserved=True, native_legality_guards_preserved=True)
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], 120)
        run('generated_check', ['make', 'generated-check'], 120)
        assert run('version', [executable, '--version'], 60).strip() == candidate['native_version']
        text, translation = packing_xdc((ROOT / 'fpga/ypcb.xdc').read_text())
        assert translation == packed['constraint_translation'] and translation['target_period_ns'] == 20.0
        constraints = out / 'ypcb.place-only.literal.xdc'; constraints.write_text(text)
        input_path = (ROOT / prepared['pack_input']).resolve(strict=True)
        assert input_path.is_relative_to(prepared_path.parent) and str(input_path) in before
        output = out / 'placed.json'; argv = placement_argv(executable, input_path, constraints, output); verify_full_argv(argv)
        report.update(stage='native_place', constraint_translation=translation, native_packing_executed=True,
            native_placement_executed=True, original_prepared_input_repacked=True)
        run('native_place', argv, NATIVE_TIMEOUT)
        design = json.loads(output.read_text()); module, labels = native_export_module(design, report['native_version'])
        report['native_export_top_translation'] = labels
        report['placement_checks'] = verify_placed_module(module, packed['native_packed_cell_counts'], packed['retained_kernel_dsps'])
        del design, module
        verify_bindings(before); report['production_source_after'] = source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status=PLACED, stage='complete', retained_cmac_dsps=512, retained_shell_dsps=3,
            placed_design=str(output.relative_to(ROOT)))
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
