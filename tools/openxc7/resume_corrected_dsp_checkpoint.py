#!/usr/bin/env python3
"""Fresh reload/negative/route of the literal corrected DSP control placement.

The previous overall FAIL is preserved. Reuse only its completed, content-bound
native placement, never its verification logs as new execution evidence. The
pinned JSON reader drops ports with zero connection bits; restore only those
empty input declarations in a comparison view, not in any execution artifact.
Connected pins, explicit directions, parameters, attributes and BELs remain
strict. No full placement transfer, bitstream or physical signoff is admitted.
"""
from collections import Counter
from copy import deepcopy
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
import probe_corrected_dsp_checkpoint as first
from place_prefix_board import bind_report, verify_bindings
from verify_corrected_native_evidence import verify_corrected_evidence

ROOT = first.ROOT
PARENT = ROOT / 'build/openxc7/corrected-dsp-checkpoint-control-1791417172851071744/report.json'
CONTROL = ROOT / 'tests/cmac/test_corrected_checkpoint_resume_control.py'
FRONTEND = Path('/home/fedora/tiny-gpu/build/ypcb/nextpnr-himbaechel/frontend/frontend_base.h')
JSON_FRONTEND = FRONTEND.parent / 'json_frontend.cc'
PASS = 'PASS_CORRECTED_DSP_BRAM_PLACED_RELOAD_AND_ROUTE_WITH_EXACT_EMPTY_INPUT_METADATA_VIEW_NOT_FULL_TRANSFER_OR_SIGNOFF'


def empty_input_view(original, exported, include_luts=True):
    """No endpoints are added; only declared [] inputs may be represented."""
    assert set(original['cells']) == set(exported['cells']), 'Changed hardware instance membership'
    cells, restored = {}, Counter()
    for name, source in original['cells'].items():
        cell = exported['cells'][name]
        assert cell['type'] == source['type'], 'Changed primitive type'
        assert set(source['connections']) == set(source['port_directions'])
        assert set(cell['connections']) == set(cell['port_directions'])
        if cell['type'] == 'SLICE_LUTX' and not include_luts:
            cells[name] = cell  # Existing logical-LUT permutation comparison remains mandatory.
            continue
        assert set(cell['connections']) <= set(source['connections']), 'Extra checkpoint pin'
        for pin, direction in cell['port_directions'].items():
            assert direction == source['port_directions'][pin], 'Explicit checkpoint pin direction changed'
        missing = set(source['connections']) - set(cell['connections'])
        if missing:
            assert cell['type'] in ('DSP48E1_DSP48E1', 'RAMB36E1_RAMB36E1', 'SLICE_LUTX'), 'Unmodeled empty-input primitive'
            connections, directions = dict(cell['connections']), dict(cell['port_directions'])
            for pin in missing:
                assert source['connections'][pin] == [] and source['port_directions'][pin] == 'input', 'Missing connected or non-input checkpoint pin'
                connections[pin], directions[pin] = [], 'input'
                restored[cell['type']] += 1
            cell = dict(cell, connections=connections, port_directions=directions)
        cells[name] = cell
    return dict(exported, cells=cells), dict(
        contract='PINNED_GENERIC_FRONTEND_IMPORT_LEAF_CELL_CREATES_PORTS_ONLY_FOR_EXISTING_VECTOR_BITS',
        restored_empty_inputs_by_type=dict(restored), original_and_exported_artifacts_modified=False,
        connected_endpoints_added_removed_or_rewritten=False, comparison_view_used_for_execution=False,
        LUT_input_permutations_compared_separately=not include_luts)


def verify_parent_metadata(parent, q):
    assert parent['status'] == 'FAIL' and parent['stage'] == 'reload' and parent['finished_utc']
    assert parent['error'] == "AssertionError('Changed pin direction')"
    assert parent['full_target_parallel_products'] == 512 and parent['control_primitive_counts'] == {'DSP48E1': 4, 'RAMB36E1': 6}
    assert parent['executable'] == q['executable'] and parent['native_version'] == q['native_version']
    assert parent['execution_input'] == str(ROOT / q['execution_input']) and parent['control_origins'] == q['control_origins']
    assert parent['constraint_translation'] == q['constraint_translation']
    assert parent['production_source_before'] == q['production_source_before']
    assert [step['label'] for step in parent['commands']] == ['admission_controls', 'checkpoint_controls',
        'generated_check', 'version', 'linked_router_check', 'native_placement', 'reload']
    for step in parent['commands']:
        assert step['status'] == 'PASS_TOOL_EXECUTION_ONLY' and step['returncode'] == step['expected_returncode'] == 0
    for key in ('old_full_placement_transfer_admitted', 'full_board_native_placement_executed', 'full_board_native_routing_executed',
                'full_board_numerical_acceptance', 'expected_feature_vectors_used_for_execution', 'physical_fit_verified',
                'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
        assert parent[key] is False, 'Unsupported failed-parent acceptance: ' + key
    assert parent['router_connectivity_check']['actual_linked_call_present'] is True
    assert parent['router_connectivity_check']['executable_sha256'] == q['executable']['sha256']


def main():
    out = ROOT / f'build/openxc7/corrected-dsp-checkpoint-resume-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=first.timestamp(), supervisor_pid=os.getpid(),
        scope=__doc__, commands=[], source={}, original_failed_report=str(PARENT), original_failure_relabelled=False,
        fresh_native_placement_executed=False, reused_completed_source_bound_native_placement=True,
        full_target_parallel_products=512, control_primitive_counts={'DSP48E1': 4, 'RAMB36E1': 6},
        old_full_placement_transfer_admitted=False, full_board_native_placement_executed=False,
        full_board_native_routing_executed=False, full_board_numerical_acceptance=False,
        expected_feature_vectors_used_for_execution=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        production_source_before=first.source_revision())
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, expected=0, timeout=1800):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(ROOT), log=str(out / (label + '.log')),
                    expected_returncode=expected, timeout_seconds=timeout, status='RUNNING')
        report['commands'].append(step)
        started = time.monotonic()
        save()
        try:
            with Path(step['log']).open('w') as log, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
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
            text = Path(step['log']).read_text()
            assert code == expected, text[-3500:]
            if expected: first.duplicate_bel_rejection(code, text)
            else: assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text), text[-3500:]
            step['status'] = 'PASS_EXPECTED_REJECTION_ONLY' if expected else 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3)
            save()
    print(out / 'report.json', flush=True)
    save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        q, before = verify_corrected_evidence()
        previous = json.loads(PARENT.read_text())
        verify_parent_metadata(previous, q)
        bind_report(PARENT, previous, before)
        for path in (Path(__file__), CONTROL, FRONTEND, JSON_FRONTEND, Path(sys.executable).resolve(strict=True)):
            path, sha = path.resolve(strict=True), first.digest(path)
            assert str(path) not in before or before[str(path)] == sha, 'Changed source evidence'
            before[str(path)] = sha
        for module in list(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if filename and Path(filename).resolve().is_relative_to(ROOT / 'tools'):
                path, sha = Path(filename).resolve(), first.digest(filename)
                assert str(path) not in before or before[str(path)] == sha, 'Changed bound helper'
                before[str(path)] = sha
        report.update(source=before, executable=q['executable'], native_version=q['native_version'])
        verify_bindings(before)
        placed_path = PARENT.parent / 'placed.json'
        step = previous['commands'][-2]
        assert step['argv'] == first.native_placement_argv(q['executable']['path'], ROOT / q['execution_input'],
                                                         PARENT.parent / 'literal.xdc', placed_path)
        log = Path(step['log']).read_text()
        for marker in ('Running Static placer...', 'Running simulated annealing placer for refinement.',
                       'Running post-placement legalisation...', 'Program finished normally.'):
            assert marker in log
        assert 'Static refinement iteration limit:' not in log
        assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):', log)
        design = json.loads(placed_path.read_text())
        parent, labels = first.native_export_module(design, q['native_version'])
        counts = dict(Counter(cell['type'] for cell in parent['cells'].values()))
        first.verify_placed_module(parent, counts)
        assert len(parent['cells']) == 286 and counts['DSP48E1_DSP48E1'] == 4 and counts['RAMB36E1_RAMB36E1'] == 6
        selected, origins = json.loads(first.SELECTED.read_text()), q['control_origins']
        for name, source in origins.items():
            if selected[source]['type'] == 'DSP48E1': first.verify_corrected_packed(selected[source], parent['cells'][name])
        report.update(hardware_execution_input=str(placed_path), control_origins=origins,
                      admitted_parent_placement_seconds=step['seconds'], checkpoint_label_translation=labels)
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        executable = q['executable']['path']
        assert run('version', [executable, '--version'], timeout=60).strip() == q['native_version']
        assembly = run('linked_router_check', ['objdump', '-d', '--disassemble=' + first.ROUTER_SYMBOL, executable], timeout=120)
        assert re.search(r'\bcall\s+[0-9a-f]+ <' + first.CHECK_SYMBOL + r'>', assembly)
        report['actual_linked_native_connectivity_check_call_present'] = True
        text, constraints = first.packing_xdc((ROOT / 'fpga/ypcb.xdc').read_text())
        assert constraints == q['constraint_translation']
        xdc = out / 'literal.xdc'
        xdc.write_text(text)
        report.update(constraint_translation=constraints, stage='fresh_reload')
        reload_path = out / 'reloaded.json'
        run('fresh_reload', first.resume_argv(executable, placed_path, labels['emitted_context_label'], xdc, reload_path), timeout=600)
        reload = json.loads(reload_path.read_text())
        label, module = next(iter(reload['modules'].items()))
        view, annotations = empty_input_view(parent, module)
        report['reload_empty_input_annotations'] = annotations
        assert sum(annotations['restored_empty_inputs_by_type'].values()) == 1108
        report['checkpoint_comparison'] = first.verify_checkpoint(design, dict(reload, modules={label: view}), selected, origins, q['native_version'])
        bad = deepcopy(design)
        cells = next(iter(bad['modules'].values()))['cells']
        a, b = [name for name, cell in cells.items() if cell['type'] == 'DSP48E1_DSP48E1'][:2]
        cells[b]['attributes']['NEXTPNR_BEL'] = cells[a]['attributes']['NEXTPNR_BEL']
        negative = out / 'duplicate-DSP-bel.json'
        negative.write_text(json.dumps(bad, indent=2, sort_keys=True) + '\n')
        report['stage'] = 'fresh_duplicate_BEL_negative'
        run('duplicate_DSP_bel_rejection', first.resume_argv(executable, negative, labels['emitted_context_label'], xdc, out / 'invalid.json'),
            expected=-signal.SIGABRT, timeout=600)
        assert not (out / 'invalid.json').exists()
        report.update(duplicate_DSP_bel_native_rejection=True, stage='fresh_route_FASM')
        routed, fasm, placement = (out / name for name in ('routed.json', 'control.fasm', 'placement.json'))
        argv = first.resume_argv(executable, placed_path, labels['emitted_context_label'], xdc, routed, route=True)
        argv += ['-o', 'fasm=' + str(fasm), '-o', 'placement=' + str(placement)]
        log = run('route_FASM', argv)
        for marker in ('Running router1 to check that route is legal...', 'Routing complete.', 'Program finished normally.'):
            assert marker in log
        native = next(iter(json.loads(routed.read_text())['modules'].values()))
        with first.SiteBELMap(first.DATABASE, first.CONSTIDS) as database:
            report['routed_footprint'] = first.verify_routed_footprint(native, first.physical_footprint(parent, database), {})
        view, annotations = empty_input_view(parent, native, include_luts=False)
        report['route_non_LUT_empty_input_annotations'] = annotations
        report['routed_logical_identity'] = first.assert_circuit_identity(first.proof_module(parent), first.proof_module(view, parent['ports']))
        features, repeated = first.parse_native_features(fasm.read_text())
        placed = json.loads(placement.read_text())
        report['DSP_feature_comparison'] = {name: first.compare_corrected_dsp(features, placed[name], selected[source], native['cells'][name])
            for name, source in origins.items() if selected[source]['type'] == 'DSP48E1'}
        report['BRAM_feature_comparison'] = {name: first.compare_bram(features, placed[name], selected[source])
            for name, source in origins.items() if selected[source]['type'] == 'RAMB36E1'}
        report.update(native_FASM_features=len(features), native_FASM_repeated_idempotent_STEPDOWN_lines=repeated,
                      exact_all_cell_bel_route_identity=True, control_cell_counts=counts,
                      post_route_export_not_admitted_as_generic_checkpoint=True)
        verify_bindings(before)
        report['production_source_after'] = first.source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status=PASS, stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = first.timestamp()
        report['artifacts'] = {str(path.relative_to(ROOT)): first.digest(path) for path in out.iterdir()
                               if path.is_file() and path.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
