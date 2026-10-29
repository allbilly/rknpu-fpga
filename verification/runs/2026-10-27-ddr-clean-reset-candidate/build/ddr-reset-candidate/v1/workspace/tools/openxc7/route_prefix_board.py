#!/usr/bin/env python3
"""Full C32/K16 native routing characterization, never bitstream signoff.

Requires a completed source-bound full placement and retains every physical
BEL. Source-defined LUT input permutations are compared through original
logical pin mappings, not silently ignored. The proof view is never an input
to hardware execution. Full native FASM is emitted and its source-defined
DSP/BRAM configurations are compared. Missing DSP/-2 timing/electrical/DRC,
physical USE_MULT defaults and startup independence remain open.
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
from place_prefix_board import (ROOT, PLACED, QUALIFICATION, DATABASE, CONSTIDS,
    ABSENT_ACCEPTANCE, timestamp, digest, audit, packing_xdc, native_export_module,
    bind_report, verify_bindings, verify_packed_metadata, verify_prepared_metadata,
    verify_placed_module, verify_native_tool_transition)
from probe_prefix_route_resume import resume_argv, ROUTER_SYMBOL, CHECK_SYMBOL
from prepare_prefix_pack_input import assert_circuit_identity
from himbaechel_site_bels import SiteBELMap
from probe_prefix_native_config import SELECTED
from check_full_native_features import (FEATURE_CONTROL, verify_feature_control_metadata, verify_full_features)

ROUTED = 'ROUTED_FULL_C32K16_NATIVE_CONNECTIVITY_CHARACTERIZATION_NOT_TIMING_ELECTRICAL_DRC_SIGNOFF'
SMALL_ROUTE = ROOT / 'build/openxc7/prefix-route-resume-small-control-1791398005736380470/report.json'


def verify_precision_transition_metadata(transition):
    """Metadata admission only; the actual native evidence is checked later."""
    assert (transition['changed_exponential_calls'], transition['fresh_native_positive_placements'],
            transition['fresh_lut_output_comparisons']) == (2, 3, 1024)
    for key in ('only_static_placer_object_replaced', 'parent_relink_byte_identical',
                'assertions_objective_clock_and_full_geometry_unchanged', 'packing_routing_timing_objects_unchanged'):
        assert transition[key] is True, 'Invalid native transition: ' + key
    assert transition['global_donor_pointer_changed'] is False
    for key in ('original_qualification', 'selected_qualification'):
        assert Path(transition[key]).is_absolute()
    assert transition['original_qualification'] != transition['selected_qualification']
    for key in ('original_executable', 'selected_executable'):
        executable = transition[key]
        assert set(executable) == {'path', 'sha256'} and Path(executable['path']).is_absolute()
        assert re.fullmatch('[0-9a-f]{64}', executable['sha256'])
    assert transition['original_executable'] != transition['selected_executable']


def verify_small_route_metadata(report):
    assert report['status'] == 'PASS_SMALL_NATIVE_PLACED_RELOAD_AND_ROUTE_CONTROL_NOT_FULL_BOARD_OR_SIGNOFF'
    assert report['stage'] == 'complete' and report['finished_utc']
    for key in ('small_native_reload_executed', 'small_native_routing_executed',
                'exact_all_cell_bel_reload_identity', 'duplicate_bel_native_rejection'):
        assert report[key] is True, 'Missing small native execution: ' + key
    for key in ('full_board_native_routing_executed', 'full_board_numerical_acceptance',
                'physical_fit_verified', 'timing_signoff', 'electrical_verified',
                'bitstream_emitted', 'hardware_programmed'):
        assert report[key] is False, 'Unsupported small-route acceptance: ' + key
    verify_precision_transition_metadata(report['native_tool_transition'])
    assert report['router_connectivity_check']['actual_linked_call_present'] is True
    assert report['router_connectivity_check']['executable_sha256'] == report['native_tool_transition']['selected_executable']['sha256']
    assert [c['label'] for c in report['commands']] == ['software_controls', 'generated_check', 'version',
        'linked_router_check', 'reload', 'duplicate_bel_rejection', 'route']
    for command in report['commands']:
        expected = -signal.SIGABRT if command['label'] == 'duplicate_bel_rejection' else 0
        assert command['returncode'] == command['expected_returncode'] == expected
        assert command['status'] == ('PASS_EXPECTED_REJECTION_ONLY' if expected else 'PASS_TOOL_EXECUTION_ONLY')


def verify_placed_metadata(report):
    assert report['status'] == PLACED and report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'],
            report['retained_cmac_dsps'], report['retained_shell_dsps'], report['intended_part'],
            report['intended_clock_period_ns'], report['seed']) == (32, 16, 512, 512, 3, 'xc7k480tffg1156-2', 20, 3588)
    assert report['native_packing_executed'] is True and report['native_placement_executed'] is True
    assert all(report[key] is False for key in ABSENT_ACCEPTANCE)
    assert report['original_prepared_input_repacked'] is True and report['packed_context_reloaded'] is False
    checks = report['placement_checks']
    assert len(checks['retained_kernel_dsps']) == 16 and set(checks['retained_kernel_dsps'].values()) == {32}
    assert checks['primitive_counts']['DSP48E1_DSP48E1'] == 515 and checks['primitive_counts']['RAMB36E1_RAMB36E1'] == 6
    assert checks['bound_cells'] == checks['unique_bel_slots'] == sum(checks['primitive_counts'].values())
    assert checks['full_placed_numerical_acceptance'] is False
    assert [Path(step['log']).stem for step in report['commands']] == ['version', 'help', 'native_place']
    assert all(step['status'] == 'PASS_TOOL_EXECUTION_ONLY' and step['returncode'] == 0 for step in report['commands'])
    assert report['constraint_translation']['target_period_ns'] == 20
    assert report['constraint_translation']['signoff_constraint_profile'] is False
    verify_precision_transition_metadata(report['native_tool_transition'])


def logical_lut(cell):
    """Pinned fixup_routing/fasm get_lut_init mapping, LUT1..6 only.

    Every original logical input and output (including a disconnected output)
    must remain. Unmapped physical
    inputs are ignored only in this proof view: the source-defined FASM INIT
    expansion is independent of them. Extra/disconnected outputs cannot hide
    live logic. No memories/SRLs or unmodeled logical LUT kinds are admitted.
    """
    assert cell['type'] == 'SLICE_LUTX'
    attributes = cell['attributes']
    kind = attributes['X_ORIG_TYPE']
    match = re.fullmatch(r'LUT([1-6])', kind)
    assert match, 'Unsupported routed LUT logical type: ' + kind
    width = int(match[1])
    assert set(cell['parameters']) == {'INIT'}, 'Unexpected logical LUT parameters'
    # Native Property export may retain a 32-bit integer representation for
    # a LUT1..5 INIT (e.g. packer's generated feed-through LUTs). fasm.cc
    # extracts/pads to 64 bits and indexes only the original logical inputs.
    # Keep the complete literal parameter for the later identity comparison;
    # this is not a parameter truncation or truth-table rewrite.
    assert isinstance(cell['parameters']['INIT'], str) and re.fullmatch('[01]{1,64}', cell['parameters']['INIT']), 'Changed LUT INIT width/encoding'
    assert set(cell['connections']) == set(cell['port_directions'])
    # pack_carry.cc converts non-chain XORCY -> LUT2; xform_cell records
    # I0=CI/I1=LI/O=O, and the later LUT -> SLICE_LUTX transformation does not
    # erase those intermediate annotations. FASM consumes only A1..A6.
    # Admit this exact evidenced chain, retaining all legacy attributes in
    # the physical-footprint check. Unknown stale pin annotations still fail.
    legacy = {key: value for key, value in attributes.items()
              if key in ('X_ORIG_PORT_I0', 'X_ORIG_PORT_I1', 'X_ORIG_PORT_O')}
    if legacy:
        assert kind == 'LUT2' and cell['parameters']['INIT'] == format(0x6, '032b'), 'Unsupported intermediate LUT transformation'
        assert legacy == dict(X_ORIG_PORT_I0='CI', X_ORIG_PORT_I1='LI', X_ORIG_PORT_O='O'), 'Changed XORCY transformation metadata'
    mapped_ports = {key.removeprefix('X_ORIG_PORT_') for key in attributes
                    if key.startswith('X_ORIG_PORT_') and key not in legacy}
    assert mapped_ports <= set(cell['connections']), 'Mapping for absent physical LUT pin'
    assert all(isinstance(attributes['X_ORIG_PORT_' + port], str) and attributes['X_ORIG_PORT_' + port]
               for port in mapped_ports), 'Empty/non-string physical LUT mapping'
    connections, directions = {}, {}
    for port, bits in cell['connections'].items():
        mapping = attributes.get('X_ORIG_PORT_' + port, '')
        if re.fullmatch(r'A[1-6]', port):
            assert cell['port_directions'][port] == 'input' and len(bits) <= 1
            if not mapping:
                continue  # FASM's original logical INIT is independent of this physical input.
            assert len(bits) == 1, 'Disconnected mapped logical LUT input'
            labels = mapping.split(' ')
            assert len(labels) == len(set(labels)) and all(re.fullmatch(r'I[0-' + str(width - 1) + ']', label) for label in labels)
            for label in labels:
                assert label not in connections, 'Duplicated logical LUT input mapping'
                connections[label], directions[label] = bits, 'input'
        else:
            assert port in ('O5', 'O6') and cell['port_directions'][port] == 'output', 'Unknown physical LUT port'
            if not bits and not mapping:
                continue
            # The native writer retains declared but disconnected outputs;
            # preserve the empty logical O pin rather than deleting the cell.
            assert len(bits) <= 1 and mapping == 'O' and 'O' not in connections, 'Changed logical LUT output'
            connections['O'], directions['O'] = bits, 'output'
    assert set(connections) == {'O', *(f'I{i}' for i in range(width))}, 'Missing logical LUT pins'
    return dict(type=cell['type'], parameters=cell['parameters'], connections=connections,
                port_directions=directions)


def proof_module(module, parent_ports=None):
    """A comparison-only original-pin view; never alter a hardware input."""
    if parent_ports is None:
        ports = module['ports']
    else:
        assert module['ports'] == {}, 'Unexpected checkpoint port annotation contract'
        ports = {}
        for name, spec in parent_ports.items():
            labels = [name] if len(spec['bits']) == 1 else [f'{name}[{i}]' for i in range(len(spec['bits']))]
            bits = []
            for label in labels:
                net = module['netnames'][label]['bits']
                assert len(net) == 1 and type(net[0]) is int and net[0] >= 2
                assert module['cells'][label]['type'] == 'PAD'
                assert module['cells'][label]['connections'] == {'PAD': net}, 'Changed external pad incidence'
                bits.extend(net)
            ports[name] = dict(spec, bits=bits)
    cells = {}
    for name, cell in module['cells'].items():
        cells[name] = logical_lut(cell) if cell['type'] == 'SLICE_LUTX' else {
            key: cell[key] for key in ('type', 'parameters', 'connections', 'port_directions')}
    return dict(modules={'logical_board': dict(ports=ports, cells=cells)})


def physical_footprint(module, database):
    result = {}
    for name, cell in module['cells'].items():
        attributes = cell['attributes']
        result[name] = dict(type=cell['type'], global_bel=database.global_label(attributes['NEXTPNR_BEL']),
            # Only the exact source-defined physical input mapping keys may
            # change. All other LUT and non-LUT properties must survive.
            attributes=stable_attributes(cell))
    assert len({item['global_bel'] for item in result.values()}) == len(result), 'Duplicate physical BEL slots'
    return result


def stable_attributes(cell):
    ignored = {'NEXTPNR_BEL'}
    if cell['type'] == 'SLICE_LUTX':
        ignored.update('X_ORIG_PORT_A' + str(i) for i in range(1, 7))
    return {key: value for key, value in cell['attributes'].items() if key not in ignored}


def verify_routed_footprint(module, footprint, groups):
    assert module['ports'] == {}, 'Unexpected routed checkpoint port annotations'
    for key in ('pack', 'place', 'route'):
        assert re.fullmatch('[01]{32}', module['settings'][key]) and int(module['settings'][key], 2) == 1
    assert float(module['settings']['target_freq']) == 50_000_000
    assert set(module['cells']) == set(footprint), 'Changed full routed cell membership'
    bels = []
    for name, cell in module['cells'].items():
        expected = footprint[name]
        assert cell['type'] == expected['type'], 'Changed routed primitive type'
        assert cell['attributes']['NEXTPNR_BEL'] == expected['global_bel'], 'Changed physical BEL: ' + name
        assert stable_attributes(cell) == expected['attributes'], 'Changed resource properties: ' + name
        bels.append(expected['global_bel'])
    assert len(set(bels)) == len(bels)
    actual = {group: sum(cell['type'] == 'DSP48E1_DSP48E1' for name, cell in module['cells'].items()
        if name.startswith(group + '.')) for group in groups}
    assert actual == groups, 'Changed full routed kernel DSP membership'
    return dict(retained_kernel_dsps=actual, unchanged_physical_bel_assignments=len(bels))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placed', type=Path, required=True)
    parser.add_argument('--small-route', type=Path, required=True,
                        help='Fresh source-bound reload/routing qualification for the selected precision engine')
    parser.add_argument('--native-feature-control', type=Path, default=FEATURE_CONTROL,
                        help='Completed actual DSP/BRAM FASM encoder control for the same native engine')
    args = parser.parse_args()
    placed_path = (ROOT / args.placed).resolve(strict=True)
    assert placed_path.is_relative_to(ROOT / 'build/openxc7')
    out = ROOT / f'build/openxc7/full-prefix-native-route-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__), out / 'executed_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        commands=[], channels=32, kernels=16, parallel_products=512, retained_cmac_dsps=512, retained_shell_dsps=3,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588,
        native_routing_executed=False, numerical_netlist_acceptance=False, physical_fit_verified=False,
        full_native_FASM_emitted=False, full_DSP_BRAM_source_defined_features_compared=False,
        timing_signoff=False, electrical_verified=False, drc_signoff=False, bitstream_emitted=False,
        hardware_programmed=False, proof_view_used_for_hardware_execution=False, scope=__doc__)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, timeout=21600):
        log = out / (label + '.log')
        step = dict(label=label, argv=list(map(str, argv)), status='RUNNING', cwd=str(ROOT),
                    log=str(log.relative_to(ROOT)), timeout_seconds=timeout)
        report['commands'].append(step)
        start = time.monotonic()
        save()
        try:
            with log.open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream,
                    stderr=subprocess.STDOUT, start_new_session=True,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0))) as proc:
                step['pid'] = proc.pid
                save()
                try: code = proc.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = log.read_text()
            assert code == 0, text[-3000:]
            assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text), text[-3000:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    save()
    print(out / 'report.json', flush=True)
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        placed = json.loads(placed_path.read_text())
        verify_placed_metadata(placed)
        before = {}
        bind_report(placed_path, placed, before)
        packed_path, prepared_path = [(ROOT / placed[key]).resolve(strict=True) for key in ('packed_report', 'prepared_report')]
        for path, verifier in ((packed_path, verify_packed_metadata), (prepared_path, verify_prepared_metadata)):
            assert str(path) in before and path.is_relative_to(ROOT / 'build/openxc7')
            parent = json.loads(path.read_text())
            verifier(parent)
            bind_report(path, parent, before)
        report.update(source=before, placed_report=str(placed_path.relative_to(ROOT)))
        verify_bindings(before)
        qualification_path = Path(placed['native_tool_transition']['selected_qualification']).resolve(strict=True)
        assert str(qualification_path) in before, 'Unbound placement engine qualification'
        inventory, candidate, transition = verify_native_tool_transition(qualification_path)
        assert transition == placed['native_tool_transition'], 'Changed selected placement engine'
        report.update(timing_inventory=inventory, native_tool_transition=transition)
        before.update(candidate['inputs'])
        small_path = (ROOT / args.small_route).resolve(strict=True)
        assert small_path.is_relative_to(ROOT / 'build/openxc7')
        small = json.loads(small_path.read_text())
        verify_small_route_metadata(small)
        assert small['native_tool_transition'] == transition, 'Small routing control used a different native engine'
        bind_report(small_path, small, before)
        report['small_route_control_report'] = str(small_path.relative_to(ROOT))
        feature_path = (ROOT / args.native_feature_control).resolve(strict=True)
        assert feature_path.is_relative_to(ROOT / 'build/openxc7')
        feature_control = json.loads(feature_path.read_text())
        verify_feature_control_metadata(feature_control, transition)
        bind_report(feature_path, feature_control, before)
        assert str(SELECTED.resolve()) in before, 'Unbound full original DSP/BRAM inventory'
        report['native_feature_control_report'] = str(feature_path.relative_to(ROOT))
        executable = Path(candidate['executable']['path'])
        for path in (QUALIFICATION, qualification_path, DATABASE, CONSTIDS, executable, Path(__file__)):
            before[str(path.resolve())] = digest(path)
        for module in list(sys.modules.values()):
            if getattr(module, '__file__', None):
                path = Path(module.__file__).resolve()
                if path.is_relative_to(ROOT / 'tools'):
                    before[str(path)] = digest(path)
        verify_bindings(before)
        version = run('version', [executable, '--version'], 60).strip()
        assert version == placed['native_version']
        report['native_version'] = version
        assembly = run('linked_router_check', ['objdump', '-d', '--disassemble=' + ROUTER_SYMBOL, executable], 60)
        assert re.search(r'\bcall\s+[0-9a-f]+ <' + CHECK_SYMBOL + '>', assembly)
        report['actual_linked_connectivity_check_call_present'] = True
        design_path = (ROOT / placed['placed_design']).resolve(strict=True)
        assert design_path.is_relative_to(placed_path.parent) and str(design_path) in before
        design = json.loads(design_path.read_text())
        module, labels = native_export_module(design, version)
        verify_placed_module(module, placed['placement_checks']['primitive_counts'], placed['placement_checks']['retained_kernel_dsps'])
        external_ports = module['ports']
        with SiteBELMap(DATABASE, CONSTIDS) as database:
            footprint = physical_footprint(module, database)
        footprint_path = out / 'physical-footprint.json'
        footprint_path.write_text(json.dumps(footprint, separators=(',', ':')))
        proof_path = out / 'comparison-only-logical-input.json'
        proof_path.write_text(json.dumps(proof_module(module), separators=(',', ':')))
        report['comparison_artifact_bindings'] = {str(path.relative_to(ROOT)): digest(path)
                                                 for path in (footprint_path, proof_path)}
        del design, module, footprint
        text, translation = packing_xdc((ROOT / 'fpga/ypcb.xdc').read_text())
        assert translation == placed['constraint_translation']
        xdc = out / 'ypcb.route-only.literal.xdc'
        xdc.write_text(text)
        output = out / 'routed.json'
        fasm, placement_output = out / 'full-board.fasm', out / 'native-placement.json'
        report.update(stage='native_route', native_routing_executed=True,
            hardware_execution_input=str(design_path.relative_to(ROOT)), checkpoint_label_translation=labels,
            constraint_translation=translation, native_repacking_executed=False, native_replacement_executed=False)
        route_argv = resume_argv(executable, design_path, labels['emitted_context_label'], xdc, output, True)
        route_argv += ['-o', 'fasm=' + str(fasm), '-o', 'placement=' + str(placement_output)]
        log = run('native_route', route_argv)
        for marker in ('Running router1 to check that route is legal...', 'Routing complete.',
                       'Running post-routing legalisation...', 'Program finished normally.'):
            assert marker in log
        design = json.loads(output.read_text())
        assert all(digest(ROOT / name) == sha for name, sha in report['comparison_artifact_bindings'].items()), 'Changed comparison-only artifact'
        assert design['creator'] == labels['producer'] and list(design['modules']) == [labels['emitted_context_label']]
        module = next(iter(design['modules'].values()))
        footprint = json.loads(footprint_path.read_text())
        report['physical_resource_checks'] = verify_routed_footprint(module, footprint, placed['placement_checks']['retained_kernel_dsps'])
        del footprint
        canonical = proof_module(module, external_ports)
        del design, module
        report['original_logical_circuit_identity'] = assert_circuit_identity(json.loads(proof_path.read_text()), canonical)
        del canonical
        report['circuit_comparison_scope'] = 'UNCHANGED_PRIMITIVE_PARAMETERS_AND_ORIGINAL_LOGICAL_PIN_WIRE_INCIDENCE_WITH_SOURCE_DEFINED_LUT_PIN_PERMUTATIONS'
        report['stage'] = 'full_native_FASM_configuration_comparison'
        save()
        selected = json.loads(SELECTED.read_text())
        report['full_DSP_BRAM_FASM_feature_comparison'] = verify_full_features(
            fasm, placement_output, output, selected, placed['placement_checks']['retained_kernel_dsps'])
        verify_bindings(before)
        report.update(status=ROUTED, stage='complete', routed_design=str(output.relative_to(ROOT)),
            full_native_FASM_emitted=True, full_DSP_BRAM_source_defined_features_compared=True,
            native_FASM=str(fasm.relative_to(ROOT)), native_placement=str(placement_output.relative_to(ROOT)))
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.iterdir()
                               if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
