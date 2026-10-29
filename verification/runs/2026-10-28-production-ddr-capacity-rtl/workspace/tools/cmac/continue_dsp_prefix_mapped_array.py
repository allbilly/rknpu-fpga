#!/usr/bin/env python3
"""Source-bound full 208-frame mapped-array continuation using a closed library.

Retains the original failed compiler gate and all 16 kernels/512 products.
No recompilation or arithmetic replacement of the archived mapped kernel.
"""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
import dsp_prefix_compile_admission as admission

original = admission.runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('compile', 'inventory', 'cone', 'proof', 'verilator', 'iverilog', 'archive'):
        parser.add_argument('--' + name + '-report', type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name + '_report').resolve()
        for name in ('compile', 'inventory', 'cone', 'proof', 'verilator', 'iverilog', 'archive')}
    assert all(path.is_relative_to(ROOT) and path.is_file() for path in paths.values())
    out = ROOT / f'build/rknpu-dsp-prefix-array-mapped-continuation/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        commands=[], channels=32, kernels=16, parallel_products=512, frames=208, expected_outputs=3328,
        seed='0x35883216', parent_reports={name: str(path.relative_to(ROOT)) for name, path in paths.items()},
        original_failed_report_preserved=True, reused_compiled_library=True,
        numerical_netlist_binary_fixture_acceptance=False, four_state_x_acceptance=False,
        raw_board_numerical_acceptance=False, physical_fit_verified=False, bitstream_emitted=False,
        hardware_programmed=False, scope=__doc__)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(argv, label, negative=None):
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (label + '.log')).relative_to(ROOT)))
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                def no_core():
                    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True, preexec_fn=no_core) as proc:
                    step['pid'] = proc.pid
                    save()
                    try:
                        code = proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait()
                        raise
            step['returncode'] = code
            text = (ROOT / step['log']).read_text()
            if negative is None:
                assert code == 0
                entries = admission.validate_followup(text, admitted)
                step['exact_admitted_diagnostic_count'] = len(entries)
            else:
                result = original.validate_result(text, code, negative)
                if result:
                    report['result'] = result
            step['status'] = 'PASS'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save()
    try:
        certificate, admitted = admission.admit(*(paths[name] for name in
            ('compile', 'inventory', 'cone', 'proof', 'verilator', 'iverilog', 'archive')))
        report['compiler_admission'] = certificate
        parent = json.loads(paths['compile'].read_text())
        old = paths['compile'].parent
        area_path, native_path = [ROOT / parent['parent_reports'][name] for name in ('area', 'native')]
        area, raw, _ = original.mapping.verify_area(area_path)
        native = original.replay.verify_native(native_path)
        original.mapping.validate_shared_leaf(area, native)
        vectors_report = ROOT / native['vector_report']
        vectors = vectors_report.parent / 'vectors.hex'
        assert len(vectors.read_text().splitlines()) == 208
        bench, negative, control, model, netlist = [old / name for name in
            (original.BENCH + '.sv', 'negative_vectors.hex', 'mapped_hierarchy.vlt',
             'xilinx_functional_models.v', 'mapped_partition.v')]
        assert bench.read_text() == original.mapped_bench(original.SOURCE_BENCH.read_text())
        assert negative.read_text() == original.negative_vectors(vectors.read_text())
        wrapper = old / 'cell' / (original.BLOCK + '.sv')
        library = old / 'cell' / ('lib' + original.BLOCK + '.a')
        params = ROOT / 'tools/cmac/empty_hier_parameters.v'
        imported = [Path(module.__file__).resolve() for module in list(sys.modules.values())
            if getattr(module, '__file__', None) and Path(module.__file__).resolve().is_relative_to(ROOT / 'tools')]
        tracked = [*paths.values(), area_path, native_path, vectors_report, vectors, bench, negative, control,
            model, netlist, wrapper, library, params, original.SOURCE_BENCH, Path(__file__).resolve(),
            ROOT / 'tests/cmac/test_dsp_prefix_compile_admission_control.py', *imported]
        before = fingerprint(tracked)
        report['source'] = before
        for path in sorted(set(tracked)):
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
        report['tool_version'] = run(['verilator', '--version'], 'verilator_version').splitlines()[0]
        report['cxx_version'] = run(['c++', '--version'], 'cxx_version').splitlines()[0]
        assert report['tool_version'] == parent['tool_version'] and report['cxx_version'] == parent['cxx_version']
        obj = out / 'top'
        obj.mkdir()
        (obj / ('V' + original.BENCH + '_hier.mk')).write_text('VM_HIER_LIBS := ' + str(library) + '\n')
        flags = ['--timing', '--assert', '-Wall', '-Wno-fatal', '--timescale-override', '1ns/1ps']
        optimization = 'OPT_FAST=-O2 OPT_SLOW=-O2 OPT_GLOBAL=-O2'
        report['stage'] = 'top_generation'
        save()
        run(['verilator', '--cc', '--main', '--exe', *flags, '-GATOMIC_C=32', '-GATOMIC_K=16',
            '--top-module', original.BENCH, '--Mdir', obj, '-o', 'sim',
            '--hierarchical-block', original.SIM_KERNEL + ',' + original.BLOCK,
            '--hierarchical-params-file', params, '-LDFLAGS', library, wrapper, model, netlist, bench], 'top_generate')
        cpp = list(obj.glob('V' + original.BENCH + '*.cpp'))
        operations = {operation for path in cpp for operation in ('create', 'combo_update', 'seq_update')
            if re.search(r'\b' + original.BLOCK + '_protectlib_' + operation + r'\s*\(', path.read_text())}
        assert operations == {'create', 'combo_update'}
        assert not any('LUT' in path.name or original.SIM_KERNEL in path.name for path in cpp)
        report['library_operations'] = sorted(operations)
        report['compiled_kernel_inputs'] = fingerprint([control, model, netlist, wrapper, library])
        report['stage'] = 'top_compile'
        save()
        run(['make', '-C', obj, '-f', 'V' + original.BENCH + '.mk', '-j', '2', *optimization.split()], 'top_compile')
        binary = obj / 'sim'
        execution = fingerprint([binary, library])
        report['execution_inputs'] = execution
        report['stage'] = 'simulation'
        save()
        for label, stimulus, negative_test in (('negative_test', negative, True), ('actual_test', vectors, False)):
            binding = fingerprint([stimulus])
            report.setdefault('stimulus_inputs', {})[label] = binding
            save()
            run([binary, f'+VECTORS={stimulus}', '+COUNT=208'], label, negative_test)
            assert fingerprint([stimulus]) == binding and fingerprint([binary, library]) == execution
            assert fingerprint(tracked) == before
        assert fingerprint([ROOT / name for name in certificate['compiled_products']['files']]) == certificate['compiled_products']
        report.update(status='PASS_FULL_C32K16_DSP_PREFIX_ARRAY_MAPPED_BINARY_CONTINUATION_FIXTURES_ONLY',
            stage='complete', numerical_netlist_binary_fixture_acceptance=True)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([path for path in out.rglob('*') if path.is_file() and path != out / 'report.json'])
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
