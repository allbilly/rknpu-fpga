#!/usr/bin/env python3
"""Actual small old-placement -> exact DSP correction -> corrected route.

Use a fresh old-engine placement of the same literal encoder-control input,
not a routed export or software-constructed placement. Preserve all BELs and
the complete graph except the eight qualified DSP tile-only pins. The native
reload is an identity check, not an architecture-validity rescan. Corrected
preRoute initializes tags before real routing and feature comparisons.
This does not admit pending full placement, signoff, or bitstream emission.
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
import probe_corrected_dsp_checkpoint as checkpoint
from correct_placed_dsp_constants import correct_placement
from resume_corrected_dsp_checkpoint import empty_input_view
from verify_corrected_native_evidence import verify_corrected_evidence
from place_prefix_board import bind_report, verify_bindings
from check_full_native_features import FEATURE_CONTROL, verify_feature_control_metadata
from check_full_corrected_native_features import compare_selected

ROOT = checkpoint.ROOT
CONTROL = ROOT / 'tests/cmac/test_corrected_placement_transfer_control.py'
PASS = 'PASS_SMALL_NATIVE_OLD_PLACEMENT_EXACT_DSP_CORRECTION_RELOAD_AND_ROUTE_NOT_FULL_TRANSFER_OR_SIGNOFF'


def main():
    out = ROOT / f'build/openxc7/corrected-placement-transfer-control-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    shutil.copyfile(CONTROL, out / 'executed_control_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=checkpoint.timestamp(), supervisor_pid=os.getpid(),
        scope=__doc__, source={}, commands=[], full_target_parallel_products=512,
        control_primitive_counts={'DSP48E1': 4, 'RAMB36E1': 6}, fresh_old_native_placement_executed=False,
        exact_DSP_correction_prepared=False, fresh_corrected_native_reload_executed=False,
        reload_is_architecture_validity_rescan=False, fresh_corrected_native_route_executed=False,
        old_full_placement_transfer_admitted=False, full_board_native_routing_executed=False,
        full_board_numerical_acceptance=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        expected_feature_vectors_used_for_execution=False, comparison_views_used_for_execution=False,
        production_source_before=checkpoint.source_revision())
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, expected=0, timeout=1800):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(ROOT), expected_returncode=expected,
                    timeout_seconds=timeout, log=str(out / (label + '.log')), status='RUNNING')
        report['commands'].append(step)
        start = time.monotonic()
        save()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
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
            if expected: checkpoint.duplicate_bel_rejection(code, text)
            else: assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text), text[-3500:]
            step['status'] = 'PASS_EXPECTED_REJECTION_ONLY' if expected else 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()
    print(out / 'report.json', flush=True)
    save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        q, before = verify_corrected_evidence()
        old = json.loads(FEATURE_CONTROL.read_text())
        transition = old['native_tool_transition']
        verify_feature_control_metadata(old, transition)
        bind_report(FEATURE_CONTROL, old, before)
        built = json.loads(Path(q['candidate_build_report']).read_text())
        precision = json.loads(Path(built['parent_build_report']).read_text())
        assert precision['executable'] == transition['selected_executable'], 'Different qualified old placement engine'
        assert built['parent_precision_qualification'] == transition['selected_qualification']
        for path in (Path(__file__), CONTROL, ROOT / 'fpga/ypcb.xdc', Path(sys.executable).resolve(strict=True)):
            before[str(path.resolve())] = checkpoint.digest(path)
        for module in list(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if filename and Path(filename).resolve().is_relative_to(ROOT / 'tools'):
                path = Path(filename).resolve()
                sha = checkpoint.digest(path)
                assert str(path) not in before or before[str(path)] == sha, 'Changed accepted helper source'
                before[str(path)] = sha
        verify_bindings(before)
        old_exe, new_exe = transition['selected_executable']['path'], q['executable']['path']
        report.update(source=before, old_executable=transition['selected_executable'], corrected_executable=q['executable'],
            native_version=q['native_version'], old_encoder_control_report=str(FEATURE_CONTROL),
            corrected_native_qualification_report=str(checkpoint.NATIVE),
            software_runtime=dict(python_executable=str(Path(sys.executable).resolve(strict=True)), python_version=sys.version))
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        assert run('old_version', [old_exe, '--version'], timeout=60).strip() == q['native_version']
        assert run('corrected_version', [new_exe, '--version'], timeout=60).strip() == q['native_version']
        assembly = run('linked_router_check', ['objdump', '-d', '--disassemble=' + checkpoint.ROUTER_SYMBOL, new_exe], timeout=120)
        assert re.search(r'\bcall\s+[0-9a-f]+ <' + checkpoint.CHECK_SYMBOL + r'>', assembly)
        report['actual_linked_native_connectivity_check_call_present'] = True
        fixture = ROOT / q['execution_input']
        assert str(fixture.resolve()) in before
        selected, origins = json.loads(checkpoint.SELECTED.read_text()), q['control_origins']
        text, constraints = checkpoint.packing_xdc((ROOT / 'fpga/ypcb.xdc').read_text())
        assert constraints == q['constraint_translation'] == old['constraint_translation']
        xdc = out / 'literal.xdc'
        xdc.write_text(text)
        report.update(stage='fresh_old_native_placement', execution_input=str(fixture), control_origins=origins,
            constraint_translation=constraints, fresh_old_native_placement_executed=True)
        old_path = out / 'old-placed.json'
        log = run('old_native_placement', checkpoint.native_placement_argv(old_exe, fixture, xdc, old_path))
        for marker in ('Running Static placer...', 'Running simulated annealing placer for refinement.',
                       'Running post-placement legalisation...', 'Program finished normally.'):
            assert marker in log
        assert 'Static refinement iteration limit:' not in log
        design = json.loads(old_path.read_text())
        parent, labels = checkpoint.native_export_module(design, q['native_version'])
        counts = dict(Counter(cell['type'] for cell in parent['cells'].values()))
        assert len(parent['cells']) == 286 and counts['DSP48E1_DSP48E1'] == 4 and counts['RAMB36E1_RAMB36E1'] == 6
        checkpoint.verify_placed_module(parent, counts)
        dsps = {name: selected[source] for name, source in origins.items() if selected[source]['type'] == 'DSP48E1'}
        corrected, delta = correct_placement(parent, dsps)
        label = labels['emitted_context_label']
        transferred = dict(design, modules={label: corrected})
        transfer_path = out / 'corrected-transfer-input.json'
        transfer_path.write_text(json.dumps(transferred, indent=2, sort_keys=True) + '\n')
        report.update(stage='fresh_corrected_reload', exact_DSP_correction_prepared=True,
            correction_delta=delta, corrected_execution_input=str(transfer_path),
            hardware_input_sha256=checkpoint.digest(transfer_path), fresh_corrected_native_reload_executed=True)
        reload_path = out / 'reloaded.json'
        run('corrected_reload', checkpoint.resume_argv(new_exe, transfer_path, label, xdc, reload_path), timeout=600)
        reload = json.loads(reload_path.read_text())
        reload_label, native = next(iter(reload['modules'].items()))
        view, annotations = empty_input_view(corrected, native)
        report['reload_empty_input_annotations'] = annotations
        report['checkpoint_comparison'] = checkpoint.verify_checkpoint(transferred, dict(reload, modules={reload_label: view}),
            selected, origins, q['native_version'])
        bad = deepcopy(transferred)
        cells = bad['modules'][label]['cells']
        a, b = list(dsps)[:2]
        cells[b]['attributes']['NEXTPNR_BEL'] = cells[a]['attributes']['NEXTPNR_BEL']
        negative = out / 'duplicate-DSP-bel.json'
        negative.write_text(json.dumps(bad, indent=2, sort_keys=True) + '\n')
        report['stage'] = 'fresh_duplicate_BEL_negative'
        run('duplicate_DSP_bel_rejection', checkpoint.resume_argv(new_exe, negative, label, xdc, out / 'invalid.json'),
            expected=-signal.SIGABRT, timeout=600)
        assert not (out / 'invalid.json').exists()
        report.update(stage='fresh_corrected_route', duplicate_DSP_bel_native_rejection=True,
                      fresh_corrected_native_route_executed=True)
        routed, fasm, placements = (out / name for name in ('routed.json', 'control.fasm', 'placement.json'))
        argv = checkpoint.resume_argv(new_exe, transfer_path, label, xdc, routed, route=True)
        argv += ['-o', 'fasm=' + str(fasm), '-o', 'placement=' + str(placements)]
        log = run('corrected_route_FASM', argv)
        for marker in ('Running router1 to check that route is legal...', 'Routing complete.',
                       'Running post-routing legalisation...', 'Program finished normally.'):
            assert marker in log
        native = next(iter(json.loads(routed.read_text())['modules'].values()))
        with checkpoint.SiteBELMap(checkpoint.DATABASE, checkpoint.CONSTIDS) as database:
            report['routed_footprint'] = checkpoint.verify_routed_footprint(native, checkpoint.physical_footprint(corrected, database), {})
        view, annotations = empty_input_view(corrected, native, include_luts=False)
        report['route_non_LUT_empty_input_annotations'] = annotations
        report['routed_logical_identity'] = checkpoint.assert_circuit_identity(
            checkpoint.proof_module(corrected), checkpoint.proof_module(view, corrected['ports']))
        features, repeated = checkpoint.parse_native_features(fasm.read_text())
        originals = {name: selected[source] for name, source in origins.items()}
        placed = json.loads(placements.read_text())
        packed = {name: native['cells'][name] for name in originals}
        with checkpoint.SiteBELMap(checkpoint.DATABASE, checkpoint.CONSTIDS) as database:
            report['selected_feature_comparison'] = compare_selected(features,
                {name: placed[name] for name in originals}, originals, packed, database.global_label)
        report.update(native_FASM_features=len(features), repeated_idempotent_STEPDOWN_lines=repeated,
            source_defined_empty_input_annotations_are_comparison_only=True,
            original_placement_validity_scan_precedes_correction=True,
            post_correction_all_BEL_validity_rescan_executed=False)
        assert checkpoint.digest(transfer_path) == report['hardware_input_sha256']
        verify_bindings(before)
        report['production_source_after'] = checkpoint.source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status=PASS, stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = checkpoint.timestamp()
        report['artifacts'] = {str(path.relative_to(ROOT)): checkpoint.digest(path) for path in out.iterdir()
                               if path.is_file() and path.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
