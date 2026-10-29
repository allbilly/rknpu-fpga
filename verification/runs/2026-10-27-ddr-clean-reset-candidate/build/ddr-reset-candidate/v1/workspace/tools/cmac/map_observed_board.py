#!/usr/bin/env python3
"""Fresh XC7 mapping with exact original raw-board observations retained.

Use only a completed source-bound pre-mapping preparation. Reuse the original
complete-board mapping stages, not arithmetic substitutes or guessed taps.
This gate does not execute the raw-board bench or establish physical fit.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from prepare_observed_board import TOP, KERNEL, MARKER, BENCH, verify_observations, verify_implementation_boundary
from test_fixed_array_board import verify_manifest
from map_fixed_board import count_shell
from xc7_primitive_counts import primitive_counts

FLAGS = f'-family xc7 -top {TOP} -flatten -noiopad -noclkbuf'
STAGES = [MARKER, 'techmap -map +/cmp2lut.v -map +/cmp2lcu.v -D LUT_WIDTH=6;',
    'alumacc;', 'opt;', 'memory -nomap;', 'opt_clean;',
    f'synth_xilinx {FLAGS} -run map_memory:;', 'check -assert;']


def verify_prepared_report(report):
    assert report['status'] == 'PREPARED_ORIGINAL_RAW_BOARD_OBSERVABILITY_ONLY', 'Completed observability preparation required'
    assert report['stage'] == 'complete'
    assert (report['channels'], report['kernels'], report['parallel_products']) == (32, 16, 512)
    assert len(report['bindings']) == 22
    assert report['imported_kernel_circuit_identity'] == 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
    assert len(report['commands']) == 2
    assert all(c['status'] == 'PASS' and c['returncode'] == 0 for c in report['commands'])
    for flag in ('numerical_netlist_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[flag] is False


def mapping_script(original, premap, original_directory, destination):
    assert original.count(MARKER) == 1
    suffix = MARKER + original.split(MARKER)[1]
    commands = [line.strip() for line in suffix.splitlines() if line.strip()]
    expected = STAGES + ['write_json ' + json.dumps(str(original_directory / 'mapped_hierarchy.json')) + ';',
                        'write_verilog -noattr ' + json.dumps(str(original_directory / 'mapped.v'))]
    assert commands == expected, 'Changed complete-board mapping stage sequence'
    prefix = ('read_verilog -lib +/xilinx/cells_sim.v;\nread_json ' + json.dumps(str(premap)) + ';\n'
        f'hierarchy -check -top {TOP};\nselect -assert-mod-count 1 A:hdlname={KERNEL};\n'
        'select -assert-mod-count 1 A:keep_hierarchy=1;\n')
    outputs = ['write_json ' + json.dumps(str(destination / 'mapped_hierarchy.json')) + ';',
               'write_verilog -noattr ' + json.dumps(str(destination / 'mapped.v'))]
    return prefix + '\n'.join(STAGES + outputs) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation-report', required=True, type=Path)
    args = parser.parse_args()
    prep_path = args.preparation_report.resolve()
    assert prep_path.is_relative_to(ROOT)
    prep = json.loads(prep_path.read_text())
    verify_prepared_report(prep)
    verify_manifest(prep['source']); verify_manifest(prep['artifacts'])
    parent_path = (ROOT / prep['parent_report']).resolve()
    assert parent_path.is_relative_to(ROOT)
    parent = json.loads(parent_path.read_text())
    assert parent['status'] == 'PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY'
    assert parent['source']['sha256'] == prep['parent_source_sha256']
    verify_manifest(parent['source']); verify_manifest(parent['artifacts'])
    premap = prep_path.parent / 'observable_premap.json'
    original_script = parent_path.parent / 'mapping.ys'
    partition_path = parent_path.parent / 'cmac_partition.json'
    assert str(premap.relative_to(ROOT)) in prep['artifacts']['files']
    kernel = parent['preserved_kernel']
    original = json.loads(partition_path.read_text())
    prepared = json.loads(premap.read_text())
    verify_implementation_boundary(prepared, original, kernel)
    verify_observations(prepared['modules'][TOP], BENCH.read_text())
    out = ROOT / f'build/rknpu-observable-board-mapping/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    script = out / 'mapping.ys'
    script.write_text(mapping_script(original_script.read_text(), premap, parent_path.parent, out))
    tracked = [prep_path, parent_path, premap, original_script, partition_path, script, BENCH, Path(__file__).resolve(),
        *(ROOT / name for name in prep['source']['files'])]
    tracked.extend(Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
    report = dict(status='RUNNING', stage='mapping', started_utc=timestamp(), source=fingerprint(tracked),
        supervisor_pid=os.getpid(), commands=[], preparation_report=str(prep_path.relative_to(ROOT)),
        parent_report=str(parent_path.relative_to(ROOT)), channels=32, kernels=16, parallel_products=512,
        preserved_kernel=kernel, intended_part=parent['intended_part'], intended_clock_period_ns=parent['intended_clock_period_ns'],
        numerical_netlist_acceptance=False, physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Fresh complete raw C32/K16 board mapping with the original 22 verification observations retained and native four-bit controller state. Original mapping stages and actual 16-kernel hardware preserved. Not raw-board numerical/fault/reset execution, packed fit, timing/DRC/electrical or bitstream acceptance.')

    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)

    def run(argv, label):
        log_path = out / (label + '.log')
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str(log_path.relative_to(ROOT)))
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with log_path.open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code
            log = log_path.read_text()
            assert code == 0 and not re.search(r'(?im)\berror:|\bwarning:', log), log[-6000:]
            step['status'] = 'PASS'; return log
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3); save()

    save()
    try:
        for path in set(tracked):
            if path.suffix == '.json' and path.stat().st_size > 1024 * 1024: continue
            dest = out / 'snapshot' / path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(path.read_bytes())
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        assert report['tool_version'] == prep['tool_version'] == parent['tool_version']
        # Bind the exact executable and installed FPGA library used for the
        # run. Mapping reads the unchanged installed library, not a stub.
        datadir = Path(run(['yosys-config', '--datdir'], 'datadir').strip())
        external = [Path(shutil.which('yosys')), datadir / 'xilinx/cells_sim.v']
        external_before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in external}
        report['external_mapping_inputs'] = external_before; save()
        log = run(['yosys', '-Q', '-T', '-s', script], 'mapping')
        assert 'Executing SHARE pass' not in log
        mapped = out / 'mapped_hierarchy.json'
        design = json.loads(mapped.read_text())
        modules = design['modules']
        implementation = {'modules': {name: modules[name] for name in (TOP, kernel)}}
        verify_implementation_boundary(implementation, original, kernel)
        report['bindings'] = verify_observations(modules[TOP], BENCH.read_text())
        report['imported_kernel_circuit_identity'] = 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
        shell = count_shell(modules, TOP, kernel)
        kernel_counts = primitive_counts(modules, kernel)
        counts = Counter(shell)
        for _ in range(16): counts.update(kernel_counts)
        assert shell['RAMB18E1'] + shell['RAMB36E1'] > 0, 'No inferred board RAM'
        for name, direction, width in (('SYS_CLK', 'input', 1), ('SYS_RSTN', 'input', 1), ('led_3bits_tri_o', 'output', 3)):
            port = modules[TOP]['ports'][name]
            assert port['direction'] == direction and len(port['bits']) == width
            assert all(type(bit) is int for bit in port['bits']), 'Constant or missing board I/O'
        estimates = re.findall(r'Estimated number of LCs:\s+(\d+)', log)
        assert estimates and fingerprint(tracked) == report['source'], 'Changed mapping inputs'
        assert {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in external} == external_before
        verify_manifest(prep['source']); verify_manifest(prep['artifacts'])
        report.update(status='PASS_OBSERVABLE_RAW_BOARD_PARTITIONED_XC7_MAPPING_ONLY', stage='complete',
            mapped_kernel_instances=16, cells=dict(counts), shell_cells=dict(shell), reused_kernel_cells=dict(kernel_counts),
            lut_count=sum(n for kind, n in counts.items() if kind.startswith('LUT')),
            ff_count=sum(n for kind, n in counts.items() if kind.startswith('FD')), dsp_count=counts['DSP48E1'],
            estimated_logic_cells=int(estimates[-1]),
            artifacts=fingerprint([script, mapped, out / 'mapped.v', *(ROOT / c['log'] for c in report['commands'])]))
    except BaseException as exc:
        report.update(status='FAIL', reason=str(exc) or repr(exc)); raise
    finally:
        report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
    print(report['status'], report['lut_count'], 'LUT primitives; numerical and physical acceptance pending')


if __name__ == '__main__': main()
