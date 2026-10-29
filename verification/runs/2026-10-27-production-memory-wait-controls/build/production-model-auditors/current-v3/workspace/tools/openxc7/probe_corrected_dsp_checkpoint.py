#!/usr/bin/env python3
"""Fresh corrected four-DSP/six-BRAM place, reload and routed-FASM control.

Use the already checked literal encoder fixture, not expected feature vectors.
Require native duplicate-BEL rejection and exact checkpoint wiring/BEL/tie
identity. Comparison-only port/LUT views are never execution inputs. This
does not admit old full placement transfer, full routing or physical signoff.
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
from pack_prefix_board import ROOT, TOP, DATABASE, CONSTIDS, digest, timestamp, packing_xdc, native_export_module
from place_prefix_board import verify_placed_module, verify_bindings
from verify_corrected_native_evidence import NATIVE, IDENTITY, verify_corrected_evidence
from probe_prefix_route_resume import checkpoint_annotation_view, resume_argv, duplicate_bel_rejection, ROUTER_SYMBOL, CHECK_SYMBOL, ROUTER_OBJECT
from prepare_prefix_pack_input import assert_circuit_identity
from route_prefix_board import proof_module, physical_footprint, verify_routed_footprint
from check_corrected_dsp_features import verify_corrected_packed, compare_corrected_dsp
from check_prefix_native_features import compare_bram
from probe_prefix_native_config import SELECTED, parse_native_features
from himbaechel_site_bels import SiteBELMap
from evidence import source_revision

CONTROL = ROOT / 'tests/cmac/test_corrected_dsp_checkpoint_control.py'
ADMISSION_CONTROL = ROOT / 'tests/cmac/test_corrected_native_evidence_control.py'


def verify_checkpoint(original, reloaded, selected, origins, version):
    parent, _ = native_export_module(original, version)
    view, annotations = checkpoint_annotation_view(reloaded, original, version)
    module, _ = native_export_module(view, version)
    counts = dict(Counter(cell['type'] for cell in parent['cells'].values()))
    assert counts['DSP48E1_DSP48E1'] == 4 and counts['RAMB36E1_RAMB36E1'] == 6 and len(parent['cells']) == 286
    verify_placed_module(module, counts)
    identity = assert_circuit_identity(original, view)
    for name, cell in parent['cells'].items():
        assert cell['attributes']['NEXTPNR_BEL'] == module['cells'][name]['attributes']['NEXTPNR_BEL'], 'Changed checkpoint BEL'
    for name, source in origins.items():
        assert parent['cells'][name]['attributes'] == module['cells'][name]['attributes'], 'Changed DSP/BRAM checkpoint attributes'
        if selected[source]['type'] == 'DSP48E1':
            verify_corrected_packed(selected[source], module['cells'][name])
    return dict(exact_all_cell_bel_reload_identity=True, actual_DSP_BRAM_attributes_preserved=True,
                original_circuit_identity=identity, checkpoint_port_annotation_translation=annotations)


def native_placement_argv(executable, fixture, xdc, output):
    return list(map(str, [executable, '--chipdb', DATABASE, '--device', 'xc7k480tffg1156-2',
        '--top', TOP, '--json', fixture, '-o', 'xdc=' + str(xdc), '--placer', 'static', '--no-route',
        '--freq', '50', '--seed', '3588', '--Werror', '--verbose', '--write', output]))


def main():
    out = ROOT / f'build/openxc7/corrected-dsp-checkpoint-control-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(), commands=[],
        scope=__doc__, native_qualification_report=str(NATIVE), full_packed_identity_report=str(IDENTITY),
        full_target_parallel_products=512, control_primitive_counts=dict(DSP48E1=4, RAMB36E1=6),
        old_full_placement_transfer_admitted=False, full_board_native_placement_executed=False,
        full_board_native_routing_executed=False, full_board_numerical_acceptance=False,
        expected_feature_vectors_used_for_execution=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        production_source_before=source_revision())
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
            assert code == expected
            if expected: duplicate_bel_rejection(code, text)
            else:
                assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text), text[-3500:]
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
        for path in (Path(__file__), CONTROL, ADMISSION_CONTROL, ROOT / 'fpga/ypcb.xdc', Path(sys.executable).resolve(strict=True)):
            before[str(path.resolve())] = digest(path)
        for module in list(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if filename and Path(filename).resolve().is_relative_to(ROOT / 'tools'):
                before[str(Path(filename).resolve())] = digest(filename)
        verify_bindings(before)
        report.update(source=before, executable=q['executable'], native_version=q['native_version'])
        run('admission_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', ADMISSION_CONTROL.name, '-v'], timeout=120)
        run('checkpoint_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        executable = q['executable']['path']
        assert run('version', [executable, '--version'], timeout=60).strip() == q['native_version']
        assembly = run('linked_router_check', ['objdump', '-d', '--disassemble=' + ROUTER_SYMBOL, executable], timeout=120)
        assert re.search(r'\bcall\s+[0-9a-f]+ <' + CHECK_SYMBOL + r'>', assembly), 'Absent native routed-connectivity check'
        assert str(ROUTER_OBJECT) in before
        report['router_connectivity_check'] = dict(actual_linked_call_present=True, caller=ROUTER_SYMBOL, callee=CHECK_SYMBOL,
            router_object_sha256=before[str(ROUTER_OBJECT)], executable_sha256=q['executable']['sha256'])
        fixture = ROOT / q['execution_input']
        selected = json.loads(SELECTED.read_text())
        origins = q['control_origins']
        text, constraints = packing_xdc((ROOT / 'fpga/ypcb.xdc').read_text())
        xdc = out / 'literal.xdc'
        xdc.write_text(text)
        report.update(constraint_translation=constraints, control_origins=origins, execution_input=str(fixture), stage='native_placement')
        placed_path = out / 'placed.json'
        log = run('native_placement', native_placement_argv(executable, fixture, xdc, placed_path))
        for marker in ('Running Static placer...', 'Running simulated annealing placer for refinement.',
                       'Running post-placement legalisation...', 'Program finished normally.'):
            assert marker in log
        assert 'Static refinement iteration limit:' not in log
        design = json.loads(placed_path.read_text())
        parent, translation = native_export_module(design, q['native_version'])
        expected = dict(Counter(cell['type'] for cell in parent['cells'].values()))
        verify_placed_module(parent, expected)
        assert len(parent['cells']) == 286 and expected['DSP48E1_DSP48E1'] == 4 and expected['RAMB36E1_RAMB36E1'] == 6
        original_bels = {name: cell['attributes']['NEXTPNR_BEL'] for name, cell in parent['cells'].items()}
        for name, source in origins.items():
            if selected[source]['type'] == 'DSP48E1': verify_corrected_packed(selected[source], parent['cells'][name])
        report.update(checkpoint_label_translation=translation, stage='reload')
        label = translation['emitted_context_label']
        reloaded_path = out / 'reloaded.json'
        run('reload', resume_argv(executable, placed_path, label, xdc, reloaded_path), timeout=600)
        report['checkpoint_comparison'] = verify_checkpoint(design, json.loads(reloaded_path.read_text()), selected, origins, q['native_version'])
        bad = deepcopy(design)
        cells = next(iter(bad['modules'].values()))['cells']
        first, second = [name for name, cell in cells.items() if cell['type'] == 'DSP48E1_DSP48E1'][:2]
        cells[second]['attributes']['NEXTPNR_BEL'] = cells[first]['attributes']['NEXTPNR_BEL']
        negative_path = out / 'duplicate-DSP-bel.json'
        negative_path.write_text(json.dumps(bad, indent=2, sort_keys=True) + '\n')
        report['stage'] = 'negative'
        run('duplicate_DSP_bel_rejection', resume_argv(executable, negative_path, label, xdc, out / 'invalid.json'),
            expected=-signal.SIGABRT, timeout=600)
        assert not (out / 'invalid.json').exists()
        report.update(duplicate_DSP_bel_native_rejection=True, stage='route_FASM')
        routed, fasm, placements = (out / name for name in ('routed.json', 'control.fasm', 'placement.json'))
        argv = resume_argv(executable, placed_path, label, xdc, routed, route=True)
        argv += ['-o', 'fasm=' + str(fasm), '-o', 'placement=' + str(placements)]
        log = run('route_FASM', argv)
        for marker in ('Running router1 to check that route is legal...', 'Routing complete.', 'Program finished normally.'):
            assert marker in log
        output = json.loads(routed.read_text())
        native = next(iter(output['modules'].values()))
        with SiteBELMap(DATABASE, CONSTIDS) as database:
            footprint = physical_footprint(parent, database)
            report['routed_footprint'] = verify_routed_footprint(native, footprint, {})
        report['routed_logical_identity'] = assert_circuit_identity(proof_module(parent), proof_module(native, parent['ports']))
        features, repeated = parse_native_features(fasm.read_text())
        placed = json.loads(placements.read_text())
        report['DSP_feature_comparison'] = {name: compare_corrected_dsp(features, placed[name], selected[source], native['cells'][name])
            for name, source in origins.items() if selected[source]['type'] == 'DSP48E1'}
        report['BRAM_feature_comparison'] = {name: compare_bram(features, placed[name], selected[source])
            for name, source in origins.items() if selected[source]['type'] == 'RAMB36E1'}
        report.update(native_FASM_features=len(features), native_FASM_repeated_idempotent_STEPDOWN_lines=repeated,
            exact_all_cell_bel_route_identity=True, control_cell_counts=expected,
            post_route_export_not_admitted_as_generic_checkpoint=True)
        verify_bindings(before)
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='PASS_CORRECTED_DSP_BRAM_NATIVE_PLACED_RELOAD_AND_ROUTE_FASM_CONTROL_NOT_FULL_TRANSFER_OR_SIGNOFF', stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(path.relative_to(ROOT)): digest(path) for path in out.iterdir() if path.is_file() and path.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
