#!/usr/bin/env python3
"""Full actual C32/K16 prefix DSP mapped binary replay, not physical acceptance.

All original 208 numerical/hold/tag/reset frames and a fresh first-frame
golden-bit negative. The original VERILATOR guard excludes the native-only
X fault test; no four-state/GSR, raw-board or routed FPGA claim is made.
"""
import argparse
from copy import deepcopy
import hashlib
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
import dsp_prefix_mapped_contract as mapping
import replay_dsp_prefix_board as replay
from test_fixed_mapped_array import circuit_signature, hardware_instance_aliases, negative_vectors

CMAC = mapping.CMAC
SIM_KERNEL = 'rk_cmac_fp16_cell_dsp_prefix_xc7'
BLOCK = SIM_KERNEL + '_b'
BENCH = 'tb_cmac_fp16_dsp_prefix_mapped'
SOURCE_BENCH = ROOT / 'tests/cmac/tb_cmac_fp16_array.sv'
EXPECTED = (replay.native.EXPECTED.replace('PASS sized FP16 CMAC', 'PASS binary mapped prefix DSP FP16 CMAC')
    .replace('faults=1', 'faults=0'))


def simulation_partition(design):
    original, kernel, counts = mapping.partition(design)
    assert not any(n for k, n in counts.items() if k.startswith('FD')), 'Combinational mapped kernel required'
    ports = original['modules'][kernel]['ports']
    assert {n: (p['direction'], len(p['bits'])) for n, p in ports.items()} == {
        'data': ('input', 512), 'weight': ('input', 512), 'data_mask': ('input', 32),
        'weight_mask': ('input', 32), 'result': ('output', 44), 'invalid': ('output', 1)}
    renamed = deepcopy(original)
    assert SIM_KERNEL not in renamed['modules']
    renamed['modules'][SIM_KERNEL] = renamed['modules'].pop(kernel)
    for cell in renamed['modules'][CMAC]['cells'].values():
        if cell['type'] == kernel: cell['type'] = SIM_KERNEL
    restored = deepcopy(renamed)
    restored['modules'][kernel] = restored['modules'].pop(SIM_KERNEL)
    for cell in restored['modules'][CMAC]['cells'].values():
        if cell['type'] == SIM_KERNEL: cell['type'] = kernel
    assert restored == original, 'Aliasing changed actual circuit'
    assert counts['DSP48E1'] == 32
    return renamed, counts


def mapped_bench(text):
    changes = [('module tb_cmac_fp16_array #(', 'module ' + BENCH + ' #('),
        ('rk_cmac_fp16_array #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);',
            CMAC + ' dut(.*); // Actual mapped C32/K16/TAG35 ports, no parameter override.'),
        ('        if(!$value$plusargs("VECTORS=%s",path)',
            '        #200; // Functional-model startup, not UNISIM GSR or routed timing.\n'
            '        if(!$value$plusargs("VECTORS=%s",path)'),
        ('$display("PASS sized FP16 CMAC', '$display("PASS binary mapped prefix DSP FP16 CMAC')]
    for before, after in changes:
        assert text.count(before) == 1 and after not in text
        text = text.replace(before, after)
    return text


def export_interface(design):
    """Separate already-resolved module defaults from actual primitive settings.

    Yosys structural Verilog export omits resolved module parameter declarations. The concrete port
    bits and every primitive parameter remain checked by circuit_signature;
    the admitted C32/K16/TAG35 declarations are preserved separately, with an
    exact reversible metadata-only removal before official export.
    """
    expected = {CMAC: {'ATOMIC_C': 32, 'ATOMIC_K': 16, 'TAG_WIDTH': 35},
        SIM_KERNEL: {'ATOMIC_C': 32}}
    assert set(design['modules']) == set(expected)
    interfaces = {}
    for name, values in expected.items():
        body = design['modules'][name]
        assert 'parameter_default_values' in body
        defaults = body['parameter_default_values']
        assert {key: int(value, 2) for key, value in defaults.items()} == values
        interfaces[name] = deepcopy(defaults)
        for cell in body['cells'].values():
            if cell['type'] in expected:
                assert cell.get('parameters', {}) == {}, 'Unresolved instance parameter override'
    exported = deepcopy(design)
    for name in interfaces: exported['modules'][name].pop('parameter_default_values')
    restored = deepcopy(exported)
    for name, values in interfaces.items(): restored['modules'][name]['parameter_default_values'] = values
    assert restored == design, 'Export interface separation changed actual circuit'
    return exported, interfaces


def validate_result(text, code, negative=False):
    assert not re.search(r'(?im)\bwarning:|%Warning-|sorry:', text), text[-3000:]
    if negative:
        assert code != 0 and re.search(r'sized array mismatch frame=0(?:\s|$)', text)
        assert not any(s.startswith('PASS ') for s in text.splitlines())
        # Verilator's intentional $fatal is printed as %Error, followed by
        # its Verilog $stop diagnostic. Neither is an unrelated tool failure.
        for line in text.splitlines():
            if re.search(r'%Error|\berror:|FATAL:', line, re.I):
                assert re.search(r'sized array mismatch frame=0(?:\s|$)', line) or re.search(
                    r'%Error:.*Verilog \$stop\s*$', line), line
    else:
        assert code == 0 and not re.search(r'FATAL:|%Error|\berror:', text, re.I)
        assert [s for s in text.splitlines() if s.startswith('PASS ')] == [EXPECTED]
        return EXPECTED


def validate_diagnostics(text, out):
    assert not re.search(r'%Error|ERROR:|warning:|sorry:', text, re.I), text[-3000:]
    warnings = re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:', text, re.M)
    assert len(warnings) == len(re.findall(r'^%Warning-', text, re.M)), 'Unparsed diagnostic'
    for kind, name, line in warnings:
        path = Path(name)
        exported = path == out / 'mapped_partition.v'
        model = path == out / 'xilinx_functional_models.v'
        wrapper = path == out / 'cell' / (BLOCK + '.sv')
        timestamp_only = wrapper and kind == 'UNUSEDSIGNAL' and path.read_text().splitlines()[int(line) - 1].strip() == 'time last_combo_seqnum__V;'
        metadata = model and kind in ('SPECIFYIGN', 'GENUNNAMED')
        assert timestamp_only or metadata or ((exported or model) and kind in
            ('DECLFILENAME', 'UNUSEDSIGNAL', 'UNUSEDPARAM')), ('Unsupported export/model diagnostic', kind, name, line)
    return [list(w) for w in warnings]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--area-report', type=Path, required=True)
    parser.add_argument('--native-report', type=Path, required=True)
    args = parser.parse_args(); ap, np = map(replay.workspace_path, (args.area_report, args.native_report))
    area, raw, hierarchy = mapping.verify_area(ap); native = replay.verify_native(np)
    mapping.validate_shared_leaf(area, native)
    design, counts = simulation_partition(raw)
    vectors_report = replay.workspace_path(native['vector_report']); vectors = vectors_report.parent / 'vectors.hex'
    assert len(vectors.read_text().splitlines()) == 208
    out = ROOT / f'build/rknpu-dsp-prefix-array-mapped-binary/{time.time_ns()}'; out.mkdir(parents=True, exist_ok=False)
    partition, alias_path = out / 'actual_partition.json', out / 'hardware_instance_aliases.json'
    export_design, interfaces = export_interface(design)
    aliased, aliases = hardware_instance_aliases(export_design)
    partition.write_text(json.dumps(aliased) + '\n'); alias_path.write_text(json.dumps(aliases, indent=2) + '\n')
    bench, negative = out / (BENCH + '.sv'), out / 'negative_vectors.hex'
    bench.write_text(mapped_bench(SOURCE_BENCH.read_text())); negative.write_text(negative_vectors(vectors.read_text()))
    control, params = out / 'mapped_hierarchy.vlt', ROOT / 'tools/cmac/empty_hier_parameters.v'
    control.write_text('`verilator_config\nhier_block -module "' + SIM_KERNEL + '"\n')
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [Path(__file__).resolve(), ap, np, hierarchy, vectors_report, vectors,
        SOURCE_BENCH, bench, negative, partition, alias_path, control, params, *imported]
    before = fingerprint(tracked)
    generated = [partition, alias_path, bench, negative, control]
    report = dict(status='RUNNING', stage='export', started_utc=timestamp(), source=before,
        supervisor_pid=os.getpid(), python_version=sys.version, commands=[], channels=32, kernels=16,
        parallel_products=512, frames=208, expected_outputs=3328, seed='0x35883216',
        parent_reports={'area': str(ap.relative_to(ROOT)), 'native': str(np.relative_to(ROOT))},
        parent_source_sha256={'area': area['source']['sha256'], 'native': native['source']['sha256']},
        kernel_cells=dict(counts), expected_result=EXPECTED, four_state_x_acceptance=False,
        export_parameter_interfaces=interfaces,
        numerical_netlist_binary_fixture_acceptance=False, raw_board_numerical_acceptance=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope=__doc__)
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, negative_test=None):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                def no_core(): resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                    start_new_session=True, preexec_fn=no_core) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            if negative_test is not None:
                result = validate_result(text, code, negative_test)
                if result: report['result'] = result
            else:
                assert code == 0
                step['nonfunctional_export_diagnostics'] = validate_diagnostics(text, out)
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - start, 3); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save()
    try:
        report['tool_version'] = run(['verilator', '--version'], 'verilator_version').splitlines()[0]
        report['cxx_version'] = run(['c++', '--version'], 'cxx_version').splitlines()[0]
        report['export_tool_version'] = run(['yosys', '-V'], 'yosys_version').strip()
        assert report['export_tool_version'] == area['tool_version']
        installed = Path(run(['yosys-config', '--datdir'], 'datadir').strip()) / 'xilinx/cells_sim.v'
        models = out / 'xilinx_functional_models.v'; models.write_bytes(installed.read_bytes()); generated.append(models)
        model_sha = hashlib.sha256(installed.read_bytes()).hexdigest()
        leaf = json.loads(replay.workspace_path(native['lane_report']).read_text())
        assert model_sha == leaf['installed_model']['sha256']
        report['installed_model'] = dict(path=str(installed), sha256=model_sha, frozen=str(models.relative_to(ROOT)))
        netlist, export, roundtrip, check = [out / n for n in ('mapped_partition.v', 'export.ys', 'export_roundtrip.json', 'roundtrip.ys')]
        # Official exporter retains the actual DSP string parameters; no custom
        # numeric-only emitter or model-default substitution is used.
        export.write_text('read_json ' + json.dumps(str(partition)) + '\nwrite_verilog -noattr -noexpr -norename -nodec -nohex ' + json.dumps(str(netlist)) + '\n')
        binding = fingerprint([partition, export]); report['export_inputs'] = binding; save()
        run(['yosys', '-Q', '-T', '-s', export], 'export'); assert fingerprint([partition, export]) == binding
        check.write_text('read_verilog -sv ' + json.dumps(str(netlist)) + '\nwrite_json ' + json.dumps(str(roundtrip)) + '\n')
        run(['yosys', '-Q', '-T', '-s', check], 'roundtrip')
        assert circuit_signature(json.loads(roundtrip.read_text())) == circuit_signature(aliased), 'Export changed actual mapped circuit'
        report['export_circuit_identity'] = 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
        tracked += [models, netlist, export, roundtrip, check]; generated += [netlist, export, roundtrip, check]
        report['source'] = before = fingerprint(tracked)
        for path in sorted(set(tracked)):
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); generated.append(target)
        flags = ['--timing', '--assert', '-Wall', '-Wno-fatal', '--timescale-override', '1ns/1ps']
        optimization = 'OPT_FAST=-O2 OPT_SLOW=-O2 OPT_GLOBAL=-O2'
        libdir, obj = out / 'cell', out / 'top'; report['stage'] = 'compile'; save()
        run(['verilator', '--cc', '--build', '-j', '2', *flags, '-MAKEFLAGS', optimization,
            '--Mdir', libdir, '--prefix', 'V' + BLOCK, '--mod-prefix', 'V' + BLOCK,
            '--top-module-encoded', BLOCK, '--lib-create', BLOCK, '--hierarchical-child', '1',
            '--hierarchical-block', SIM_KERNEL + ',' + BLOCK, control, models, netlist], 'cell_compile')
        wrapper, library = libdir / (BLOCK + '.sv'), libdir / ('lib' + BLOCK + '.a')
        assert wrapper.is_file() and library.is_file()
        for pattern in (r'input logic \[511:0\]\s+data', r'input logic \[511:0\]\s+weight',
            r'input logic \[31:0\]\s+data_mask', r'output logic \[43:0\]\s+result'):
            assert re.search(pattern, wrapper.read_text())
        obj.mkdir(); (obj / ('V' + BENCH + '_hier.mk')).write_text('VM_HIER_LIBS := ' + str(library) + '\n')
        run(['verilator', '--cc', '--main', '--exe', *flags, '-GATOMIC_C=32', '-GATOMIC_K=16',
            '--top-module', BENCH, '--Mdir', obj, '-o', 'sim', '--hierarchical-block', SIM_KERNEL + ',' + BLOCK,
            '--hierarchical-params-file', params, '-LDFLAGS', library, wrapper, models, netlist, bench], 'top_generate')
        cpp = list(obj.glob('V' + BENCH + '*.cpp')); operations = set()
        for path in cpp:
            for operation in ('create', 'combo_update', 'seq_update'):
                if re.search(r'\b' + BLOCK + '_protectlib_' + operation + r'\s*\(', path.read_text()): operations.add(operation)
        assert operations == {'create', 'combo_update'}
        assert not any('LUT' in p.name or SIM_KERNEL in p.name for p in cpp), 'Embedded arithmetic bypasses mapped library'
        report['library_operations'] = sorted(operations)
        report['compiled_kernel_inputs'] = fingerprint([control, models, netlist, wrapper, library]); save()
        run(['make', '-C', obj, '-f', 'V' + BENCH + '.mk', '-j', '2', *optimization.split()], 'top_compile')
        binary = obj / 'sim'; execution = fingerprint([binary, library]); report['execution_inputs'] = execution
        report['stage'] = 'simulation'; save()
        for label, stimulus, is_negative in (('negative_test', negative, True), ('actual_test', vectors, False)):
            report.setdefault('stimulus_inputs', {})[label] = fingerprint([stimulus]); save()
            run([binary, f'+VECTORS={stimulus}', '+COUNT=208'], label, is_negative)
            assert fingerprint([stimulus]) == report['stimulus_inputs'][label]
            assert fingerprint([binary, library]) == execution
            assert fingerprint([control, models, netlist, wrapper, library]) == report['compiled_kernel_inputs']
        assert fingerprint(tracked) == before and hashlib.sha256(installed.read_bytes()).hexdigest() == model_sha
        fresh_area, _, _ = mapping.verify_area(ap); fresh_native = replay.verify_native(np)
        mapping.validate_shared_leaf(fresh_area, fresh_native)
        assert bench.read_text() == mapped_bench(SOURCE_BENCH.read_text())
        products = [p for d in (libdir, obj) for p in d.rglob('*') if p.is_file()]
        report.update(status='PASS_FULL_C32K16_DSP_PREFIX_ARRAY_MAPPED_BINARY_FIXTURES_ONLY', stage='complete',
            finished_utc=timestamp(), numerical_netlist_binary_fixture_acceptance=True,
            artifacts=fingerprint([*products, *generated, *out.glob('*.log')]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [*generated, *out.glob('*.log')] if p.is_file()])); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
