#!/usr/bin/env python3
"""Fresh full C32/K16 prefix-board mapping with the original bench retained.

Read only the completed process-lowered observation-preserving frontend. Keep
all sixteen actual mapped kernels/512 products, the original four-bit state
and 22 observation/force signals. Recompute safe RAM normalization from this
run's actual before/after graphs; unknown diagnostics fail. This is mapping
and structure evidence, not numerical replay, physical fit/timing/DRC or a
test-ready FPGA bitstream. No production RTL or bench expectation is changed.
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

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, fingerprint, timestamp
import prepare_dsp_prefix_observed_board as preparation

admission = preparation.admission
ram = admission.ram
mapper = admission.mapper
TOP, BENCH = preparation.TOP, preparation.BENCH
PARENT = 'build/rknpu-dsp-prefix-observed-board-preparation/1791307426641654447/report.json'
STATUS = 'PASS_FULL_C32K16_PREFIX_OBSERVABLE_BOARD_PARTITIONED_XC7_MAPPING_ONLY'
HELP_COMMAND = 'help flatten; help synth_xilinx'


def verify_prepared_metadata(report):
    assert report['status'] == 'PREPARED_FULL_C32K16_PREFIX_ORIGINAL_OBSERVATION_RETENTION_ONLY'
    assert report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'], report['mapped_kernel_instances'],
            report['retained_cmac_dsps'], report['intended_part'], report['intended_clock_period_ns']) == (
                32, 16, 512, 16, 512, 'xc7k480tffg1156-2', 20)
    assert set(report['bindings']) == set(preparation.WIDTHS)
    assert report['original_four_bit_state_preserved'] is True and report['original_bench_unchanged'] is True
    assert report['imported_kernel_circuit_identity'] == 'PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE'
    assert [Path(step['log']).stem for step in report['commands']] == ['version', 'frontend']
    assert all(step['returncode'] == 0 and step['status'] == 'PASS_FRONTEND_ONLY' for step in report['commands'])
    for flag in ('full_board_mapping_acceptance', 'numerical_netlist_acceptance',
                 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[flag] is False


def mapping_script(frontend, out, kernel, coarse):
    assert coarse == [command.replace('LUT_WIDTH=[46]', 'LUT_WIDTH=6')
                      for command in mapper.array.COARSE if command != 'share']
    flags = ram.FLAGS
    commands = ['read_verilog -lib +/xilinx/cells_sim.v', 'read_json ' + json.dumps(str(frontend)),
                f'hierarchy -check -top {TOP}', f'select -assert-mod-count 1 A:hdlname={mapper.KERNEL}',
                'select -assert-mod-count 1 A:keep_hierarchy=1',
                f'select -assert-count 16 */t:*{mapper.KERNEL}*',
                f'synth_xilinx {flags} -run begin:coarse',
                f'select -assert-count 32 *{mapper.KERNEL}*/t:DSP48E1', 'select -clear', *coarse,
                f'synth_xilinx {flags} -run map_memory:check',
                'design -save rk_observed_prefix_ram_capture', 'blackbox =A:whitebox',
                'write_json ' + json.dumps(str(out / 'before.json')),
                'design -load rk_observed_prefix_ram_capture',
                f'synth_xilinx {flags} -run check:', 'check -assert',
                'write_json ' + json.dumps(str(out / 'mapped_hierarchy.json')),
                'write_verilog -noattr -noexpr -norename ' + json.dumps(str(out / 'mapped.v'))]
    assert kernel.endswith('ATOMIC_C=32\'00000000000000000000000000100000'), 'Changed actual C32 partition'
    return ';\n'.join(commands) + '\n'


def audit_mapping_log(text, kernel, proved_resizes):
    """The processed JSON import has no native memory-lowering diagnostics."""
    assert not re.search(r'(?im)ERROR:|FATAL:|sorry:', text)
    assert 'Executing SHARE pass' not in text and text.count('Executing XILINX_DSP pass') == 1
    assert not admission.cones.capture.driver_notices(text), 'Driver warning in cleaned observed frontend'
    assert ram.resize_notices(text, TOP) == proved_resizes
    allowed = Counter({mapper.array.ABC_NOTICE: 1})
    allowed.update(f'Warning: Resizing cell port {TOP}.{cell}.{pin} from {widths[0]} bits to {widths[1]} bits.'
                   for (cell, pin), widths in proved_resizes.items())
    actual = Counter(line for line in text.splitlines() if re.search(r'(?i)\bwarning:', line))
    assert actual == allowed, ('Unknown or repeated observed-board diagnostic', dict(actual))
    blocks = re.split(r"(?m)^\d+(?:\.\d+)*\. Extracting gate netlist of module `(.+?)' to .*?$", text)
    assert blocks[1::2] == [kernel, '\\' + TOP], 'Unexpected observed-board ABC extraction'
    assert mapper.array.ABC_NOTICE not in blocks[0]
    frozen, shell = blocks[2::2]
    assert mapper.array.ABC_NOTICE not in frozen and 'ABC: YOSYS_ABC_DONE ' not in frozen
    assert 'Extracted 0 gates and 0 wires to a netlist network with 0 inputs and 0 outputs.' in frozen
    assert "Don't call ABC as there is nothing to map." in frozen
    assert shell.count(mapper.array.ABC_NOTICE) == shell.count(mapper.array.ABC_CONTEXT + '\n') == 1
    assert shell.splitlines().count('ABC: YOSYS_ABC_DONE ') == 1 and shell.count('Re-integrating ABC results.') == 1
    cuts = re.findall(r'(?m)^Extracted ([1-9]\d*) gates and ([1-9]\d*) wires to a netlist network '
                      r'with ([1-9]\d*) inputs and ([1-9]\d*) outputs\.$', shell)
    assert len(cuts) == 1
    checks = [int(value) for value in re.findall(r'Found and reported (\d+) problems\.', text)]
    assert checks == [0, 0, 0, 0], ('Changed or nonzero observed-board CHECK results', checks)
    return dict(exact_current_ram_resize_notices=len(proved_resizes), no_initial_driver_notices=True,
                all_check_problem_counts=checks, frozen_kernel_abc_gates=0,
                shell_abc_module='\\' + TOP,
                shell_abc_network=dict(zip(('gates', 'wires', 'inputs', 'outputs'), map(int, cuts[0]))))


def external_manifest(datadir):
    files = {Path(shutil.which(name)).resolve() for name in ('yosys', 'yosys-abc')}
    files.update(path.resolve() for path in datadir.rglob('*') if path.is_file())
    assert datadir.is_dir() and (datadir / 'xilinx/cells_sim.v').is_file()
    values = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}
    manifest = ''.join(f'{sha}  {name}\n' for name, sha in values.items())
    return dict(sha256=hashlib.sha256(manifest.encode()).hexdigest(), files=values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation-report', type=Path, default=Path(PARENT))
    args = parser.parse_args()
    pp = mapper.replay.workspace_path(args.preparation_report)
    prepared = json.loads(pp.read_text())
    verify_prepared_metadata(prepared)
    for group in ('source', 'artifacts'):
        assert fingerprint([ROOT / name for name in prepared[group]['files']]) == prepared[group]
    ap = ROOT / prepared['parent_report']
    parent = json.loads(ap.read_text())
    assert parent['status'] == admission.STATUS and parent['source']['sha256'] == prepared['parent_source_sha256']
    assert fingerprint([ROOT / name for name in parent['source']['files']]) == parent['source']
    op = ROOT / prepared['original_mapping_report']
    assert parent['parent_reports']['original'] == str(op.relative_to(ROOT))
    original = json.loads(op.read_text())
    kernel = original['preserved_kernel']
    assert prepared['preserved_kernel'] == kernel
    spec, _ = mapper.inputs()
    area, raw, _ = mapper.verify_area(ROOT / original['parent_reports']['area'])
    _, numerical_paths, _ = mapper.verify_board(ROOT / original['parent_reports']['board'], spec)
    mapper.validate_shared_prerequisites(area, numerical_paths)
    frozen, area_kernel, kernel_counts = mapper.partition(raw)
    assert area_kernel == kernel and kernel_counts['DSP48E1'] == 32
    original_body = frozen['modules'][kernel]
    frontend = pp.parent / 'observable_frontend.json'
    partition_path = op.parent / 'cmac_partition.json'
    design = json.loads(frontend.read_text())
    preparation.observations.verify_implementation_boundary(design, json.loads(partition_path.read_text()), kernel)
    assert preparation.observations.verify_observations(design['modules'][TOP], BENCH.read_text()) == prepared['bindings']
    del design, frozen, raw
    out = ROOT / f'build/rknpu-dsp-prefix-observed-board-mapping/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    paths = {pp, ap, op, frontend, partition_path, BENCH, Path(__file__).resolve(),
             *(ROOT / name for name in prepared['source']['files']),
             *(ROOT / name for name in prepared['artifacts']['files'])}
    imported = {Path(module.__file__).resolve() for module in list(sys.modules.values())
                if getattr(module, '__file__', None) and Path(module.__file__).resolve().is_relative_to(ROOT / 'tools')}
    paths.update(imported)
    source = fingerprint(paths)
    report = dict(status='RUNNING', stage='source_preparation', started_utc=timestamp(), source=source,
                  supervisor_pid=os.getpid(), commands=[], preparation_report=str(pp.relative_to(ROOT)),
                  parent_source_sha256=prepared['source']['sha256'], preserved_kernel=kernel,
                  channels=32, kernels=16, parallel_products=512, intended_part='xc7k480tffg1156-2',
                  intended_clock_period_ns=20, numerical_netlist_acceptance=False, physical_fit_verified=False,
                  bitstream_emitted=False, hardware_programmed=False, scope=__doc__)
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label):
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
                        code = process.wait(timeout=14400)
                    except BaseException:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
                        raise
            step['returncode'] = code
            text = (ROOT / step['log']).read_text()
            assert code == 0 and not re.search(r'(?im)ERROR:|FATAL:|sorry:', text), text[-4000:]
            if label != 'mapping':
                assert not re.search(r'(?im)\bwarning:', text)
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
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
        # Snapshot executed project code before any tool runs. Large immutable
        # graph/report parents stay directly bound, not relabeled fresh runs.
        for path in sorted(paths):
            if path.suffix in ('.py', '.sv', '.v', '.vlib', '.ys'):
                target = out / 'snapshot' / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        assert report['tool_version'] == prepared['tool_version']
        help_text = run(['yosys', '-Q', '-T', '-p', HELP_COMMAND], 'help')
        coarse = mapper.array.unshared_coarse(help_text)
        assert 'check:\n        hierarchy -check' in help_text
        datadir = Path(run(['yosys-config', '--datdir'], 'datadir').strip()).resolve()
        external = external_manifest(datadir)
        report['external_mapping_inputs'] = external
        script = out / 'mapping.ys'
        script.write_text(mapping_script(frontend, out, kernel, coarse))
        report['compile_inputs'] = fingerprint([frontend, script])
        report['executed_coarse_stage'] = coarse
        report['stage'] = 'full_mapping'
        save()
        text = run(['yosys', '-Q', '-T', '-s', script], 'mapping')
        assert fingerprint([frontend, script]) == report['compile_inputs']
        report['stage'] = 'actual_ram_and_observation_gates'
        save()
        before = json.loads((out / 'before.json').read_text())
        mapped = json.loads((out / 'mapped_hierarchy.json').read_text())
        resizes = ram.resize_notices(text, TOP)
        report['normalization_audit'] = ram.audit_normalization(before, mapped, TOP, resizes)
        report['mapping_diagnostics'] = audit_mapping_log(text, kernel, resizes)
        implementation = dict(modules={name: mapped['modules'][name] for name in (TOP, kernel)})
        preparation.observations.verify_implementation_boundary(implementation, json.loads(partition_path.read_text()), kernel)
        report['bindings'] = preparation.observations.verify_observations(mapped['modules'][TOP], BENCH.read_text())
        counts, shell, qualifiers = mapper.validate_mapped(mapped, TOP, kernel, original_body, kernel_counts)
        estimates = re.findall(r'Estimated number of LCs:\s+(\d+)', text)
        assert estimates
        assert fingerprint(paths) == source and external_manifest(datadir) == external
        for group in ('source', 'artifacts'):
            assert fingerprint([ROOT / name for name in prepared[group]['files']]) == prepared[group]
        mapper.array.validate_sources()
        report.update(status=STATUS, stage='complete', mapped_kernel_instances=16, retained_cmac_dsps=512,
                      original_four_bit_state_preserved=True, original_bench_unchanged=True,
                      imported_kernel_circuit_identity='PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE',
                      mapping_diagnostics_accepted=True, actual_ram_port_resizes=len(report['normalization_audit']),
                      logged_ram_port_resizes=len(resizes), cells=dict(counts), shell_cells=dict(shell),
                      reused_kernel_cells=dict(kernel_counts), timing_qualifier_counter_audit=qualifiers,
                      lut_count=sum(value for kind, value in counts.items() if kind.startswith('LUT')),
                      ff_count=sum(value for kind, value in counts.items() if kind.startswith('FD')),
                      dsp_count=counts['DSP48E1'], estimated_logic_cells=int(estimates[-1]))
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([path for path in out.rglob('*') if path.is_file() and path.name != 'report.json'])
        save()


if __name__ == '__main__':
    main()
