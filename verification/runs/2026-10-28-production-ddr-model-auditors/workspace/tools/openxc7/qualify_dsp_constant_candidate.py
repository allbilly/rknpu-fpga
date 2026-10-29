#!/usr/bin/env python3
"""Fresh native qualification of the isolated DSP tile-constant correction.

Execute the unchanged illegal/valid LUT controls, fresh full-size native pack
and a four-DSP/six-BRAM P&R/FASM control. The full pack checks all 515 actual
DSP configurations, not full circuit equivalence, placement or routing. The
small circuit is a test-only encoder input, not an NPU execution image.
Old full placement transfer is not admitted. Physical signoff remains open.
"""
from collections import Counter
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
from build_dsp_constant_candidate import BUILT, GAP, QUALIFICATION, UPSTREAM, UPSTREAM_DIGESTS
from pack_prefix_board import ROOT, TOP, DATABASE, digest, timestamp, packing_xdc
from place_prefix_board import verify_bindings, verify_packed_metadata
from qualify_static_exp_candidate import LABELS, probe_argv, check_log, validate_placed
from probe_prefix_native_config import SELECTED, config_fixture, parse_native_features, verify_clock_admission
from check_corrected_dsp_features import compare_corrected_dsp, verify_corrected_packed
from check_prefix_native_features import compare_bram
from check_full_native_features import full_inventory, routed_primitives
from evidence import source_revision

PACK_REPORT = ROOT / 'build/openxc7/full-prefix-native-pack-1791394643587130253/report.json'
PACK_INPUT = ROOT / 'build/openxc7/full-prefix-pack-input-1791392677842220299/pack_input.json'
QUALIFIED = 'PASS_ISOLATED_CORRECTED_DSP_NATIVE_PACK_AND_SMALL_LEGAL_PNR_FASM_CONTROLS_NOT_FULL_ROUTE_OR_SIGNOFF'
COMMANDS = ['qualification_controls', 'corrected_feature_controls', 'old_feature_controls', 'old_fixture_controls', 'generated_check', 'version',
            *LABELS, 'full_native_pack', 'native_clock_admission', 'small_native_PNR_FASM']


def verify_build_metadata(built):
    assert built['status'] == BUILT and built['stage'] == 'complete' and built['finished_utc']
    assert built['part'] == 'xc7k480tffg1156-2' and built['full_parallel_products'] == 512
    assert built['upstream_DSP_revision'] == UPSTREAM and built['changed_source_files'] == list(UPSTREAM_DIGESTS)
    assert built['changed_link_objects'] == 2 and built['parent_relink_byte_identical'] is True
    assert built['non_DSP_source_byte_identical'] is True
    for key in ('assertion_removal', 'native_requalification_executed', 'native_placement_executed', 'native_routing_executed',
                'old_full_placement_reuse_admitted', 'physical_fit_verified', 'timing_signoff', 'electrical_verified',
                'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
        assert built[key] is False, 'Invalid build-only acceptance: ' + key
    assert [c['label'] for c in built['commands']] == [
        'software_controls', 'generated_check', 'compiler_version', 'relink_parent_identity',
        'compile_fasm.cc', 'compile_pack_dsp_xc7.cc', 'link_DSP_constant_candidate', 'native_version']
    assert all(c['returncode'] == 0 and c['status'] == 'PASS_TOOL_EXECUTION_ONLY' for c in built['commands'])
    assert built['production_source_before'] == built['production_source_after']


def check_native_log(log):
    assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', log), log[-3500:]
    for marker in ('Running Static placer...', 'Running simulated annealing placer for refinement.',
                   'Running post-placement legalisation...', 'Routing complete.', 'Program finished normally.'):
        assert marker in log, 'Missing native P&R marker: ' + marker
    assert 'Static refinement iteration limit:' not in log


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    args = parser.parse_args()
    build_path = args.build.resolve(strict=True)
    assert build_path.is_relative_to(ROOT / 'build/openxc7') and build_path.name == 'report.json'
    out = ROOT / f'build/openxc7/dsp-constant-qualification-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(), commands=[],
        scope=__doc__, candidate_build_report=str(build_path), source={}, part='xc7k480tffg1156-2',
        full_target_parallel_products=512, full_board_native_placement_executed=False, full_board_native_routing_executed=False,
        full_board_native_FASM_executed=False, full_circuit_equivalence_claimed=False, full_board_numerical_acceptance=False,
        expected_vectors_used_for_execution=False, old_full_placement_reuse_admitted=False, physical_fit_verified=False,
        timing_signoff=False, electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        production_source_before=source_revision())

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, timeout=600, expected=0, native_probe=False, **detail):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(ROOT), timeout_seconds=timeout,
                    log=str(out / (label + '.log')), expected_returncode=expected, status='RUNNING', **detail)
        report['commands'].append(step)
        started = time.monotonic()
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
            log = Path(step['log']).read_text()
            if native_probe: check_log(code, log, expected)
            else:
                assert code == expected and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', log), log[-3500:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY' if expected == 0 else 'PASS_EXPECTED_REJECTION_ONLY'
            return log
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
        built = json.loads(build_path.read_text())
        verify_build_metadata(built)
        before = {**built['inputs'], **built['artifacts'], str(build_path): digest(build_path)}
        selected = json.loads(SELECTED.read_text())
        pack = json.loads(PACK_REPORT.read_text())
        verify_packed_metadata(pack)
        q = json.loads(QUALIFICATION.read_text())
        parent_path = Path(q['build_report'])
        parent = json.loads(parent_path.read_text())
        probes = {step['label']: step for step in parent['commands'] if step['label'] in LABELS}
        assert set(probes) == set(LABELS)
        paths = [Path(__file__), SELECTED, PACK_REPORT, PACK_INPUT, parent_path, ROOT / 'fpga/ypcb.xdc',
                 ROOT / 'tests/cmac/test_corrected_dsp_feature_control.py',
                 ROOT / 'tests/cmac/test_dsp_constant_qualification_control.py',
                 ROOT / 'tests/cmac/test_prefix_native_feature_controls.py',
                 ROOT / 'tests/cmac/test_prefix_native_config_control.py', Path(sys.executable).resolve(strict=True)]
        for module in list(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if filename and Path(filename).resolve().is_relative_to(ROOT / 'tools'):
                paths.append(Path(filename).resolve())
        for path in paths:
            path = path.resolve(strict=True)
            sha = digest(path)
            assert str(path) not in before or before[str(path)] == sha, 'Changed inherited qualification input'
            before[str(path)] = sha
        assert before[str(PACK_INPUT)] == pack['source'][str(PACK_INPUT)], 'Changed original full physical pack input'
        gap = json.loads(GAP.read_text())
        assert before[str(SELECTED)] == gap['source'][str(SELECTED)], 'Changed audited original DSP/BRAM inventory'
        verify_bindings(before)
        report.update(source=before, executable=built['executable'], native_version=built['native_version'],
                      upstream_DSP_revision=UPSTREAM, stage='native_legality_controls')
        for label, filename in [('qualification_controls', 'test_dsp_constant_qualification_control.py'),
                                ('corrected_feature_controls', 'test_corrected_dsp_feature_control.py'),
                                ('old_feature_controls', 'test_prefix_native_feature_controls.py'),
                                ('old_fixture_controls', 'test_prefix_native_config_control.py')]:
            run(label, [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', filename, '-v'])
        run('generated_check', ['make', 'generated-check'])
        executable = built['executable']['path']
        assert run('version', [executable, '--version']).strip() == built['native_version']
        positives = []
        for label in LABELS:
            old = probes[label]
            fixture, xdc = Path(old['fixture']), Path(parent['constraints'])
            assert str(fixture) in before and str(xdc) in before
            output = out / (label + '-placed.json')
            run(label, probe_argv(executable, fixture, xdc, output), expected=125 if label == 'invalid-forced' else 0,
                native_probe=True, fixture=str(fixture), output=str(output))
            if label == 'invalid-forced': assert not output.exists()
            else:
                result = validate_placed(output, 47 if label == 'counter' else 49, None if label == 'counter' else fixture)
                report['commands'][-1]['placement_checks'] = result
                positives.append(result)
                save()
        assert len(positives) == 3 and sum(item['lut_output_comparisons'] for item in positives) == 1024
        report.update(native_positive_placements=3, lut_output_comparisons=1024, illegal_pair_rejected_before_postPlace=True)
        text, constraints = packing_xdc((ROOT / 'fpga/ypcb.xdc').read_text())
        xdc = out / 'literal.xdc'
        xdc.write_text(text)
        report['constraint_translation'] = constraints
        full_packed = out / 'full-packed.json'
        report.update(stage='full_native_pack', full_board_native_pack_executed=True)
        log = run('full_native_pack', [executable, '--chipdb', DATABASE, '--device', 'xc7k480tffg1156-2',
            '--top', TOP, '--json', PACK_INPUT, '-o', 'xdc=' + str(xdc), '--freq', '50', '--seed', '3588',
            '--Werror', '--debug', '--pack-only', '--write', full_packed], timeout=1800)
        verify_clock_admission(log, constraints)
        packed_primitives = routed_primitives(full_packed, selected)
        report['full_packed_kernel_inventory'] = full_inventory(selected, packed_primitives)
        for name, cell in selected.items():
            if cell['type'] == 'DSP48E1': verify_corrected_packed(cell, packed_primitives[name])
        report.update(full_packed_DSPs_compared=515, full_packed_extra_tile_only_ties_compared=4120,
                      full_pack_changed_ordinary_wire_identity_admitted=False)
        design, origins = config_fixture(selected)
        fixture = out / 'test-only-config-input.json'
        fixture.write_text(json.dumps(design, indent=2, sort_keys=True) + '\n')
        report.update(control_origins=origins, execution_input=str(fixture.relative_to(ROOT)), stage='native_clock_admission')
        log = run('native_clock_admission', [executable, '--chipdb', DATABASE, '--device', 'xc7k480tffg1156-2',
            '--top', TOP, '--json', fixture, '-o', 'xdc=' + str(xdc), '--freq', '50', '--seed', '3588',
            '--Werror', '--debug', '--pack-only', '--write', out / 'clock-admitted-packed.json'])
        verify_clock_admission(log, constraints)
        routed, fasm, placement = (out / name for name in ('routed.json', 'control.fasm', 'placement.json'))
        report.update(stage='small_native_PNR_FASM', small_native_PNR_FASM_executed=True)
        log = run('small_native_PNR_FASM', [executable, '--chipdb', DATABASE, '--device', 'xc7k480tffg1156-2',
            '--top', TOP, '--json', fixture, '-o', 'xdc=' + str(xdc), '-o', 'fasm=' + str(fasm),
            '-o', 'placement=' + str(placement), '--placer', 'static', '--router', 'router2',
            '--freq', '50', '--seed', '3588', '--Werror', '--verbose', '--write', routed], timeout=3600)
        check_native_log(log)
        features, repeated = parse_native_features(fasm.read_text())
        placed = json.loads(placement.read_text())
        native = next(iter(json.loads(routed.read_text())['modules'].values()))
        counts = Counter(cell['type'] for cell in native['cells'].values())
        assert counts['DSP48E1_DSP48E1'] == 4 and counts['RAMB36E1_RAMB36E1'] == 6
        assert set(native['cells']) == set(placed) and len({item['nextpnr_bel'] for item in placed.values()}) == len(placed)
        report['DSP_feature_comparison'] = {name: compare_corrected_dsp(features, placed[name], selected[origin], native['cells'][name])
            for name, origin in origins.items() if selected[origin]['type'] == 'DSP48E1'}
        report['BRAM_feature_comparison'] = {name: compare_bram(features, placed[name], selected[origin])
            for name, origin in origins.items() if selected[origin]['type'] == 'RAMB36E1'}
        report.update(native_control_cell_counts=dict(counts), native_FASM_features=len(features),
                      native_FASM_repeated_idempotent_STEPDOWN_lines=repeated,
                      ordinary_constant_net_routing_verified=False, USE_MULT_physical_default_verified=False)
        assert [step['label'] for step in report['commands']] == COMMANDS
        verify_bindings(before)
        report['production_source_after'] = source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status=QUALIFIED, stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(path.relative_to(ROOT)): digest(path) for path in out.rglob('*') if path.is_file() and path.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
