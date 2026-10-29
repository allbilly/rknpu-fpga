#!/usr/bin/env python3
"""Execute pinned Xilinx DSP/CARRY models against the original complete corpus.

Exact actual-kernel parameters/constant pins, four-state Icarus comparisons,
default global startup and both wrong-golden negatives. No model source or
FPGA arithmetic is edited. Testbench-only startup settling preserves every
original vector/count/seed and assertion. Not a full mapped board/FPGA pass.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, fingerprint, timestamp
import map_dsp_prefix_observed_board as mapping
import test_dsp_prefix_primitive_models as primitive
import unisim_board_models as unisim

DSP_SHA = 'a98661443ef3a3b41a64d1d26d20326ebc4f229a84e96192c02759e6b9f8b7b5'
STARTUP = ("        wait (glbl.GSR === 1'b0);\n        #1;\n"
           "        a = 30'b1; b = 18'b1;\n        #1;\n")


def startup_bench(original):
    marker = '        edge_a[0]=0; edge_a[1]=1; edge_a[2]=2047; edge_a[3]=2048;\n'
    assert original.count(marker) == 1, 'Changed original complete-corpus startup boundary'
    result = original.replace(marker, STARTUP + marker)
    assert result.replace(STARTUP + marker, marker) == original
    return result


def model_sources():
    result = unisim.selected_models({'CARRY4'})
    result[unisim.CACHE / 'verilog/src/unisims/DSP48E1.v'] = DSP_SHA
    for path, sha in result.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha, ('Changed pinned model', path)
    return result


def validate_result(text, code, kind=None):
    assert not re.search(r'(?im)\b(?:warning|error)\s*:|sorry:', text), 'Unaccepted simulation diagnostic'
    primitive.validate_result(text, code, 'iverilog', kind)
    if kind:
        # A model that produces X also trips $fatal, but cannot demonstrate
        # detection of the deliberate one-bit wrong-golden mutation.
        marker = ('primitive DSP mismatch case=0 got=000055550000 expected=000055550001'
                  if kind == 'DSP' else
                  'primitive CARRY mismatch case=0 got=0/0 expected=1/0')
        assert kind in ('DSP', 'CARRY') and marker in text, 'Negative did not observe the exact correct first result'


def main():
    parent_path = ROOT / mapping.PARENT
    parent = json.loads(parent_path.read_text())
    mapping.verify_prepared_metadata(parent)
    for group in ('source', 'artifacts'):
        assert fingerprint([ROOT / name for name in parent[group]['files']]) == parent[group]
    graph = parent_path.parent / 'observable_frontend.json'
    raw = json.loads(graph.read_text())
    kernel = parent['preserved_kernel']
    # A name-only in-memory view lets the existing complete configuration
    # checker inspect these exact 32 actual DSP cells. No hardware is changed.
    cells = raw['modules'][kernel]
    view = {'modules': {primitive.KERNEL: cells}}
    assert primitive.validate_configuration(view, primitive.BENCH.read_text()) == 32
    models = model_sources()
    out = ROOT / f'build/rknpu-dsp-prefix-unisim-model-control/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    frozen = []
    for path in models:
        target = out / 'models' / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        frozen.append(target)
    bench = out / primitive.BENCH.name
    bench.write_text(startup_bench(primitive.BENCH.read_text()))
    paths = {parent_path, graph, primitive.BENCH, bench, Path(__file__).resolve(),
             Path(primitive.__file__).resolve(), Path(unisim.__file__).resolve(), *models, *frozen}
    source = fingerprint(paths)
    report = dict(status='RUNNING', stage='compile', started_utc=timestamp(), source=source,
                  supervisor_pid=os.getpid(), commands=[], prepared_board_report=str(parent_path.relative_to(ROOT)),
                  upstream_model_commit=unisim.COMMIT, pinned_dsp_model_sha256=DSP_SHA,
                  matched_actual_dsp_instances=32, control_dsp_instances=1, control_carry_instances=1,
                  dsp_comparisons=4259904, carry_binary_comparisons=1024, carry_four_state_comparisons=1048576,
                  seed='0x35883216', parameters=primitive.PARAMETERS, constant_pins=primitive.CONSTANTS,
                  startup_wait_and_operand_transition_only=True, unmodified_default_global_startup=True,
                  primitive_fixture_acceptance=False,
                  full_array_numerical_acceptance=False, numerical_netlist_acceptance=False,
                  physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False, scope=__doc__)
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, kind=None):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as process:
                    step['pid'] = process.pid
                    save()
                    try:
                        code = process.wait(timeout=1800)
                    except BaseException:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
                        raise
            step['returncode'] = code
            text = (ROOT / step['log']).read_text()
            if label.endswith('_test'):
                validate_result(text, code, kind)
            else:
                assert code == 0 and not re.search(r'(?im)\b(?:warning|error)\s*:|sorry:', text), text[-4000:]
            step['status'] = 'PASS'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()
    signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(SystemExit(128 + signum)))
    save()
    print(out / 'report.json', flush=True)
    try:
        assert run(['git', '-C', unisim.CACHE, 'rev-parse', 'HEAD'], 'model_commit').strip() == unisim.COMMIT
        assert run(['git', '-C', unisim.CACHE, 'status', '--porcelain', '--untracked-files=all'], 'model_clean') == ''
        report['tool_version'] = run(['iverilog', '-V'], 'version').splitlines()[0]
        report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
        binary = out / 'control.vvp'
        report['compile_inputs'] = fingerprint([bench, *frozen])
        run(['iverilog', '-g2012', '-Ttyp', '-s', primitive.TOP, '-s', 'glbl', '-o', binary,
             *[path for path in frozen if path.suffix == '.v'], bench], 'compile')
        assert fingerprint([bench, *frozen]) == report['compile_inputs']
        execution = fingerprint([binary])
        report['execution_inputs'] = execution
        for label, extra, kind in (('dsp_negative_test', ['+NEG_DSP=1'], 'DSP'),
                                   ('carry_negative_test', ['+NEG_CARRY=1'], 'CARRY'), ('positive_test', [], None)):
            report['stage'] = label
            save()
            run(['vvp', binary, *extra], label, kind)
            assert fingerprint([binary]) == execution and fingerprint(paths) == source
        assert bench.read_text() == startup_bench(primitive.BENCH.read_text())
        assert primitive.validate_configuration(view, primitive.BENCH.read_text()) == 32
        assert model_sources() == models
        report.update(status='PASS_PINNED_UNISIM_ACTUAL_PREFIX_DSP_CARRY_CORPUS_ONLY', stage='complete',
                      primitive_fixture_acceptance=True, result=primitive.expected('iverilog'))
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([path for path in out.rglob('*') if path.is_file() and path.name != 'report.json'])
        save()


if __name__ == '__main__':
    main()
