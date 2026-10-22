#!/usr/bin/env python3
"""Map the full raw C32/K16 prefix DSP board after independent numerical gates.

Reuse the actual mapped kernel sixteen times, with exact primitive/wiring
identity. Map every surrounding DMA/CACC/output/BRAM/reset/LED component.
Area/structure only: never physical fit, timing, DRC or bitstream acceptance.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
import dsp_prefix_mapped_contract as array_contract
array = array_contract.array
replay = array_contract.replay
from lane_dsp_library import timing_only_view
from map_fixed_board import count_shell
from test_fixed_mapped_array import circuit_signature
from vivado_array import inputs

CMAC = array.TOP
KERNEL = array.CELL
MAPPED_CMAC = CMAC + '_xc7'


def frontend_diagnostics(text):
    """Exact source-bound donor and strict command-profile memory lowering."""
    donor = array.SOURCES[0]
    expected = Counter({
        f'Warning: Replacing memory \\temp_array with list of registers. See {donor}:41, {donor}:33': 1,
        f'Warning: Replacing memory \\input_array with list of registers. See {donor}:33, {donor}:28': 1,
        'Warning: Replacing memory \\regs with list of registers. See ' +
        str(ROOT / 'rtl/rk_cmac_profile.sv') + ':154': 1})
    found = Counter(s for s in text.splitlines() if re.search(r'(?i)\bwarning:', s))
    assert found == expected, ('Unknown whole-board source diagnostics', dict(found))
    assert not re.search(r'(?im)ERROR:|FATAL:|sorry:', text)
    return dict(found)


def audit_board_mapping_log(text, top, kernel):
    """Unexecuted full-map contract: frozen primitive kernel plus one shell cut.

    Any differing warning/module/step/count is a failure requiring review.
    This does not import the full-array mapper's two native-kernel notices.
    """
    assert 'Executing SHARE pass' not in text
    assert text.count('Executing XILINX_DSP pass') == 1
    lines = text.splitlines()
    assert lines.count(array.ABC_NOTICE) == 1, 'Only the native shell has an ABC combinational cut'
    native = frontend_diagnostics('\n'.join(s for s in lines if s != array.ABC_NOTICE))
    blocks = re.split(r"(?m)^\d+(?:\.\d+)*\. Extracting gate netlist of module `(.+?)' to .*?$", text)
    assert blocks[1::2] == [kernel, '\\' + top], 'Unexpected whole-board ABC extraction'
    assert array.ABC_NOTICE not in blocks[0]
    frozen, shell = blocks[2::2]
    assert array.ABC_NOTICE not in frozen and 'ABC: YOSYS_ABC_DONE ' not in frozen
    assert 'Extracted 0 gates and 0 wires to a netlist network with 0 inputs and 0 outputs.' in frozen
    assert "Don't call ABC as there is nothing to map." in frozen
    assert shell.count(array.ABC_NOTICE) == shell.count(array.ABC_CONTEXT + '\n') == 1
    assert shell.splitlines().count('ABC: YOSYS_ABC_DONE ') == 1
    assert shell.count('Re-integrating ABC results.') == 1
    networks = re.findall(r'(?m)^Extracted ([1-9]\d*) gates and ([1-9]\d*) wires to a netlist network '
        r'with ([1-9]\d*) inputs and ([1-9]\d*) outputs\.$', shell)
    assert len(networks) == 1
    return dict(native_lowering_notices=native, frozen_kernel_abc_gates=0, shell_abc_module='\\' + top,
        shell_abc_network=dict(zip(('gates', 'wires', 'inputs', 'outputs'), map(int, networks[0]))))


validate_area_metadata = array_contract.validate_area_metadata
verify_area = array_contract.verify_area


def validate_board_metadata(report):
    assert report['status'] == 'PASS_FULL_C32K16_DSP_PREFIX_RAW_BOARD_FOUR_STATE_FIXTURES_ONLY'
    assert report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products']) == (32, 16, 512)
    assert report['modes'] == list(range(9)) and report['four_state_mode_not_run'] is None
    assert report['inherited_compile_only'] is True
    assert report['native_array_fixture_acceptance'] is True
    assert report['source_bound_composed_lane_acceptance'] is True and report['raw_board_numerical_acceptance'] is True
    assert report['compiled_hierarchy'] == {'rk_cmac_fp16_array_dsp_prefix': 1, 'rk_cmac_fp16_cell_dsp_prefix': 16,
        'rk_cmac_fp16_lane_dsp_prefix': 512, 'rk_cmac_fp16_discarded_carry': 512}
    certificate = report['prefix_composition_certificate']
    assert certificate['kind'] == 'BINARY_SOURCE_BOUND_DONOR_TO_COMPENSATED_TO_PREFIX_TRANSITIVITY'
    assert (certificate['relevant_binary_input_bits'], certificate['compared_binary_output_bits'],
        certificate['comparator_free_binary_inputs']) == (37, 40, 67)
    for field in ('new_positive_monolithic_sat_proof', 'all_x_equivalence', 'full_array_numerical_acceptance',
        'raw_board_numerical_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert certificate[field] is False
    for field in replay.UNPROVEN: assert report[field] is False
    replay.validate_suite(report['tests'])
    replay.command_contract(report, ('rom_check', 'iverilog_version', 'vvp_version',
        *(f'mode_{mode}' for mode in range(9))))


def verify_board(path, spec):
    report = json.loads(path.read_text()); validate_board_metadata(report); replay.verify_evidence(report)
    assert set(report['parent_reports']) == set(report['parent_source_sha256']) == {'native', 'prepared', 'composed', 'prefix'}
    paths = {n: replay.workspace_path(p) for n, p in report['parent_reports'].items()}
    native = replay.verify_native(paths['native'])
    prepared, binary, sources = replay.verify_prepared(paths['prepared'], spec)
    composed = replay.verify_composed(paths['composed'])
    assert prepared['lane_report'] == native['lane_report'], 'Different compiled/native prefix leaves'
    leaf_path = replay.workspace_path(native['lane_report'])
    certificate, prefix_path, prefix = replay.verify_prefix_composition(leaf_path, composed)
    assert paths['prefix'] == prefix_path and report['prefix_composition_certificate'] == certificate
    assert str(leaf_path.relative_to(ROOT)) in report['source']['files'], 'Unbound mapped prefix leaf'
    for name, parent in (('native', native), ('prepared', prepared), ('composed', composed), ('prefix', prefix)):
        assert report['parent_source_sha256'][name] == parent['source']['sha256']
        assert str(paths[name].relative_to(ROOT)) in report['source']['files']
    assert report['tool_version'] == native['tool_version'] == prepared['tool_version']
    assert report['runtime_version'] == native['runtime_version']
    assert report['simulation_sources'] == prepared['simulation_sources']
    assert report['compile_inputs'] == prepared['compile_inputs'] and report['execution_inputs'] == fingerprint([binary])
    assert report['stimulus_inputs'] == fingerprint(sorted((ROOT / 'tests/cmac/array_data').iterdir()))
    for mode, step, test in zip(range(9), report['commands'][3:], report['tests']):
        assert step['argv'] == ['vvp', str(binary), f'+MODE={mode}'] and test['log'] == step['log']
        assert replay.validate_board_result(replay.workspace_path(step['log']).read_text(), step['returncode'], mode) == test['result']
    return report, paths, sources


def partition(design):
    value, kernel, counts = array_contract.partition(design)
    ports = value['modules'][kernel]['ports']
    assert {n: (p['direction'], len(p['bits'])) for n, p in ports.items()} == {
        'data': ('input', 512), 'weight': ('input', 512), 'data_mask': ('input', 32),
        'weight_mask': ('input', 32), 'result': ('output', 44), 'invalid': ('output', 1)}
    assert not any(n for k, n in counts.items() if k.startswith('FD')), 'Actual mapped kernel must remain combinational'
    return value, kernel, counts


def validate_shared_prerequisites(area, paths):
    native = json.loads(paths['native'].read_text())
    replay.validate_native_metadata(native)
    array_contract.validate_shared_leaf(area, native)


def parameter_binding(design, source):
    assert CMAC in design['modules'] and len(design['modules']) == 2
    kernel = next(n for n in design['modules'] if n != CMAC)
    assert design['modules'][kernel]['attributes']['hdlname'] == KERNEL
    marker = '    wire [ATOMIC_K*44-1:0] groups;'
    assert source.count(marker) == 1
    header = source.split(marker)[0]
    assert header.count('module ' + CMAC + ' #(') == 1 and header.rstrip().endswith(');')
    value = dict(design, modules={MAPPED_CMAC if n == CMAC else n: body for n, body in design['modules'].items()})
    shim = header.replace('output logic', 'output wire')
    shim += ('    initial if(ATOMIC_C!=32 || ATOMIC_K!=16 || TAG_WIDTH!=35)\n'
        '        $fatal(1,"XC7 DSP partition requires C32 K16 TAG35");\n'
        f'    {MAPPED_CMAC} actual_partition(.*);\nendmodule\n')
    return value, shim


def kernel_identity(body, name):
    signature = circuit_signature(dict(modules={name: body}))[name]
    # read_json discards the parameter interface. The admitted fixed geometry
    # and checked wire-only wrapper supply it; every real primitive parameter,
    # port bit and pin incidence still has to remain identical.
    return {n: signature[n] for n in ('ports', 'cells', 'wire_incidence')}


def synthesis_sources(spec, join, shim):
    names = spec['synthesis']
    assert len(names) == len(set(names))
    assert all(names.count(n) == 1 for n in (replay.preparation.ORIGINAL_CELL,
        replay.preparation.ORIGINAL_ARRAY, replay.preparation.JOIN))
    excluded = {replay.preparation.ORIGINAL_CELL, replay.preparation.ORIGINAL_ARRAY}
    sources = [join if n == replay.preparation.JOIN else ROOT / n for n in names if n not in excluded]
    sources.append(shim)
    assert len(sources) == len(set(sources)) == len(names) - 1
    assert not {array.DSP_CELL, array.DSP_ARRAY, *array.SOURCES[:-1]} & set(sources) - {
        ROOT / n for n in names if n not in excluded}
    return sources


def mapping_script(spec, sources, partition_path, out, coarse):
    assert coarse == [s.replace('LUT_WIDTH=[46]', 'LUT_WIDTH=6') for s in array.COARSE if s != 'share']
    top = spec['top']; flags = f'-family xc7 -top {top} -flatten -noiopad -noclkbuf'
    commands = ['read_verilog -lib +/xilinx/cells_sim.v', 'read_json ' + json.dumps(str(partition_path)),
        'read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST ' +
        ' '.join('-I' + json.dumps(str(ROOT / n)) for n in spec['include_dirs']) + ' ' +
        ' '.join(json.dumps(str(p)) for p in sources), f'hierarchy -check -top {top}',
        f'select -assert-mod-count 1 A:hdlname={KERNEL}', 'select -assert-mod-count 1 A:keep_hierarchy=1',
        f'select -assert-count 16 */t:*{KERNEL}*', f'synth_xilinx {flags} -run begin:coarse',
        f'select -assert-count 32 *{KERNEL}*/t:DSP48E1', 'select -clear', *coarse,
        f'synth_xilinx {flags} -run map_memory:', 'check -assert',
        'write_json ' + json.dumps(str(out / 'mapped_hierarchy.json')),
        'write_verilog -noattr -noexpr -norename ' + json.dumps(str(out / 'mapped.v'))]
    return ';\n'.join(commands) + '\n'


def validate_mapped(design, top, kernel, original_body, kernel_counts):
    modules, audit = timing_only_view(design['modules'])
    assert [c['type'] for c in modules[top]['cells'].values() if KERNEL in c['type']] == [kernel] * 16
    assert int(modules[kernel]['attributes']['keep_hierarchy'], 2) == 1
    assert kernel_identity(modules[kernel], kernel) == kernel_identity(original_body, kernel), 'Changed actual mapped kernel circuit'
    assert array.primitive_counts(modules, kernel) == kernel_counts and kernel_counts['DSP48E1'] == 32
    shell = count_shell(modules, top, kernel); counts = Counter(shell)
    for _ in range(16): counts.update(kernel_counts)
    assert shell['RAMB18E1'] + shell['RAMB36E1'] > 0, 'Full-board block RAM required'
    assert counts['DSP48E1'] == 512 + shell['DSP48E1']
    assert set(modules[top]['ports']) == {'SYS_CLK', 'SYS_RSTN', 'led_3bits_tri_o'}
    for name, direction, width in (('SYS_CLK', 'input', 1), ('SYS_RSTN', 'input', 1), ('led_3bits_tri_o', 'output', 3)):
        port = modules[top]['ports'][name]
        assert port['direction'] == direction and len(port['bits']) == width and all(type(b) is int for b in port['bits'])
    return counts, shell, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--area-report', type=Path, required=True)
    parser.add_argument('--board-report', type=Path, required=True)
    args = parser.parse_args(); ap, bp = map(replay.workspace_path, (args.area_report, args.board_report))
    spec, base_sources = inputs(); area, raw, hierarchy = verify_area(ap)
    board, board_parents, _ = verify_board(bp, spec)
    validate_shared_prerequisites(area, board_parents)
    frozen, kernel, kernel_counts = partition(raw); original_body = frozen['modules'][kernel]
    frozen, shim_text = parameter_binding(frozen, array.DSP_ARRAY.read_text())
    out = ROOT / f'build/rknpu-dsp-prefix-board-area/{time.time_ns()}'; out.mkdir(parents=True, exist_ok=False)
    join, shim, part = out / Path(replay.preparation.JOIN).name, out / 'mapped_cmac_parameter_binding.sv', out / 'cmac_partition.json'
    join.write_text(replay.preparation.dsp_join((ROOT / replay.preparation.JOIN).read_text()))
    shim.write_text(shim_text); part.write_text(json.dumps(frozen) + '\n')
    sources = synthesis_sources(spec, join, shim)
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = {*base_sources, *sources, part, ap, bp, hierarchy, *board_parents.values(), *imported, Path(__file__).resolve()}
    for parent in (area, board): tracked.update(ROOT / n for n in parent['source']['files'])
    before = fingerprint(tracked); generated = [join, shim, part]
    report = dict(status='RUNNING', stage='preparation', started_utc=timestamp(), source=before,
        supervisor_pid=os.getpid(), python_version=sys.version, commands=[], channels=32, kernels=16,
        parallel_products=512, intended_part=spec['part'], intended_clock_period_ns=spec['clock_period_ns'],
        parent_reports={'area': str(ap.relative_to(ROOT)), 'board': str(bp.relative_to(ROOT))},
        parent_source_sha256={'area': area['source']['sha256'], 'board': board['source']['sha256']},
        preserved_kernel=kernel, mapped_cmac=MAPPED_CMAC, synthesis_sources=[str(p.relative_to(ROOT)) for p in sources],
        numerical_netlist_acceptance=False, physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope=__doc__)
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            assert code == 0 and 'ERROR:' not in text, text[-3000:]
            if label == 'mapping': report['source_bound_lowering_notices'] = audit_board_mapping_log(text, spec['top'], kernel)
            else: assert not re.search(r'(?im)\b(?:warning|error):|sorry:', text)
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - start, 3); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save()
    try:
        for path in sorted(tracked):
            if path.suffix in ('.json', '.vvp') and str(path.relative_to(ROOT)).startswith('build/') and path not in {ap, bp, part}:
                continue  # Large originals stay directly hash-bound; no fake new compilation.
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); generated.append(target)
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        assert report['tool_version'] == area['tool_version']
        run([sys.executable, ROOT / 'tools/cmac/gen_array_board.py', '--check'], 'rom_check')
        help_text = run(['yosys', '-Q', '-T', '-p', 'help flatten; help synth_xilinx'], 'help')
        coarse = array.unshared_coarse(help_text); script = out / 'mapping.ys'
        script.write_text(mapping_script(spec, sources, part, out, coarse)); generated.append(script)
        report['compile_inputs'] = fingerprint([*sources, part, script]); report['stage'] = 'mapping'; save()
        mapped = out / 'mapped_hierarchy.json'; generated += [mapped, out / 'mapped.v']
        log = run(['yosys', '-Q', '-T', '-s', script], 'mapping')
        assert fingerprint([*sources, part, script]) == report['compile_inputs']
        counts, shell, audit = validate_mapped(json.loads(mapped.read_text()), spec['top'], kernel, original_body, kernel_counts)
        estimates = re.findall(r'Estimated number of LCs:\s+(\d+)', log); assert estimates
        assert fingerprint(tracked) == before
        fresh_area, _, _ = verify_area(ap); _, fresh_paths, _ = verify_board(bp, spec)
        validate_shared_prerequisites(fresh_area, fresh_paths); array.validate_sources()
        report.update(status='PASS_FULL_C32K16_DSP_PREFIX_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY', stage='complete', finished_utc=timestamp(),
            mapped_kernel_instances=16, cells=dict(counts), shell_cells=dict(shell), reused_kernel_cells=dict(kernel_counts),
            kernel_circuit_identity='PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE',
            timing_qualifier_counter_audit=audit, dsp_count=counts['DSP48E1'], retained_cmac_dsps=512,
            lut_count=sum(v for k, v in counts.items() if k.startswith('LUT')), ff_count=sum(v for k, v in counts.items() if k.startswith('FD')),
            estimated_logic_cells=int(estimates[-1]), artifacts=fingerprint([*generated, *out.glob('*.log')]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [*generated, *out.glob('*.log')] if p.is_file()])); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
