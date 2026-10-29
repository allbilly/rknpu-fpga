#!/usr/bin/env python3
"""Prepared full C32/K16 corrected-DSP checkpoint scan/route, not signoff.

Require a completed full bounded-search placement and independently rechecked
small imported-carry checker qualification. Import the literal placed JSON,
execute the opt-in native all-BEL scanner and normal router connectivity check,
then compare every BEL/logical endpoint and all 515 DSP/six-BRAM features.
Comparison projections/views are never execution inputs. The older engine's
admission/31-tie expectations are untouched. No timing/electrical/DRC, numerical
or bitstream acceptance follows. No SHA256SUMS file or FPGA access is performed.
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
import resume_imported_carry_checker as small
import probe_imported_placement_checker as checker
from place_strict_search_board import PLACED, FLAGS as PLACE_FLAGS
from qualify_strict_search_rounds import verify_qualification as verify_placement_engine
from place_prefix_board import bind_report, verify_bindings, verify_packed_metadata, verify_prepared_metadata, verify_placed_module
from pack_prefix_board import ROOT, DATABASE, CONSTIDS, digest, timestamp, native_export_module, packing_xdc
from route_prefix_board import physical_footprint, verify_routed_footprint, proof_module
from prepare_prefix_pack_input import assert_circuit_identity
from compare_full_imported_export import comparison_port_source, full_export_view
from audit_postplace_lut_pairs import audit_pairs
from build_imported_carry_checker import local_carry_roles
from check_full_corrected_native_features import verify_full_features
from himbaechel_site_bels import SiteBELMap
from evidence import source_revision

SMALL = ROOT / 'build/openxc7/imported-carry-checker-resume-1791427613948665478/report.json'
CONTROL = ROOT / 'tests/cmac/test_strict_search_route.py'
ROUTED = 'ROUTED_FULL_C32K16_CORRECTED_DSP_NATIVE_CHECKPOINT_SCAN_AND_CONNECTIVITY_NOT_PHYSICAL_SIGNOFF'
FLAGS = ('numerical_netlist_acceptance', 'physical_fit_verified', 'timing_signoff', 'electrical_verified',
         'drc_signoff', 'bitstream_emitted', 'hardware_programmed', 'proof_view_used_for_hardware_execution',
         'native_repacking_executed', 'native_replacement_executed')


def verify_placed_metadata(report):
    assert report['status'] == PLACED and report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'], report['retained_cmac_dsps'],
            report['retained_shell_dsps'], report['intended_part'], report['intended_clock_period_ns'], report['seed']) == (
                32, 16, 512, 512, 3, 'xc7k480tffg1156-2', 20, 3588)
    assert all(report[key] is False for key in PLACE_FLAGS)
    assert report['native_packing_executed'] is report['native_placement_executed'] is report['original_prepared_input_repacked'] is True
    assert report['packed_context_reloaded'] is report['FPGA_clock_period_changed'] is False
    assert report['corrected_DSP_encoder_preserved'] is report['native_legality_guards_preserved'] is True
    assert report['changed_static_placer_object'] == 1
    assert [c['label'] for c in report['commands']] == ['software_controls', 'generated_check', 'version', 'native_place']
    assert all(c['status'] == 'PASS_TOOL_EXECUTION_ONLY' and c['returncode'] == 0 for c in report['commands'])
    checks = report['placement_checks']; counts = checks['primitive_counts']
    assert counts['DSP48E1_DSP48E1'] == 515 and counts['RAMB36E1_RAMB36E1'] == 6
    assert checks['bound_cells'] == checks['unique_bel_slots'] == sum(counts.values()) == 538118
    assert len(checks['retained_kernel_dsps']) == 16 and set(checks['retained_kernel_dsps'].values()) == {32}
    assert checks['full_placed_numerical_acceptance'] is False
    assert report['constraint_translation']['target_period_ns'] == 20.0 and report['constraint_translation']['signoff_constraint_profile'] is False
    assert report['production_source_before'] == report['production_source_after']


def verify_small_metadata(report):
    assert report['status'] == small.PASS and report['stage'] == 'complete' and report['finished_utc']
    assert report['full_target_parallel_products'] == 512 and report['original_failure_relabelled'] is False
    assert report['reused_completed_source_bound_native_49_scan_and_route'] is report['fresh_native_286_scan_and_route_executed'] is True
    assert (report['unchanged_preplacement_positives'], report['original_preplacement_truth_comparisons'], report['imported_corruptions_revalidated']) == (3, 1024, 8)
    assert [c['label'] for c in report['commands']] == ['test_imported_carry_export', 'test_imported_carry_checker_resume', 'generated_check', 'native_286_scan_and_route']
    assert all(c['status'] == 'PASS_TOOL_EXECUTION_ONLY' and c['returncode'] == 0 for c in report['commands'])
    assert report['saved_native_49_comparison']['logical_identity']['logical_board']['cells'] == 49
    assert report['fresh_native_286_comparison']['logical_identity']['logical_board']['cells'] == 286
    assert all(report[key] is False for key in small.FLAGS)
    assert report['production_source_before'] == report['production_source_after']


def check_full_scan(text, cells, pairs, carry_roles):
    checker.scan_log(0, text, cells, pairs)
    marker = f'RKNPU imported placement scan: verified {carry_roles} local carry DI roles.'
    assert text.count(marker) == 1 and text.index(marker) < text.index('RKNPU imported placement scan: passed')
    assert text.index('RKNPU imported placement scan: begin before clock/general routing.') < text.index(marker)
    assert 'Running Static placer...' not in text, 'Checkpoint route unexpectedly executed placement'


def verify_small_evidence(before):
    report = json.loads(SMALL.read_text()); verify_small_metadata(report)
    bind_report(SMALL, report, before); verify_bindings(before)
    failed = json.loads(small.PARENT.read_text()); small.verify_parent_metadata(failed)
    built_path = Path(failed['candidate_build_report']); built = json.loads(built_path.read_text())
    checker.verify_build_metadata(built)
    assert built['executable'] == report['executable'] and digest(built['executable']['path']) == built['executable']['sha256']
    source = built_path.parent / 'himbaechel/uarch/xilinx/xilinx.cc'
    template = built_path.parent / checker.TEMPLATE.name
    assert source.read_text() == checker.checked_source(checker.TAG_SOURCE.read_text(), template.read_text())
    for command in report['commands']:
        text = Path(command['log']).read_text()
        if command['label'] == 'native_286_scan_and_route': small.scan_log(0, text, 286, 98)
        else: assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):', text)
    for command in failed['commands']:
        label = command['label']; text = Path(command['log']).read_text()
        if label in small.REASONS: small.scan_log(command['returncode'], text, rejection=small.REASONS[label])
        elif label == 'fixed_49': small.scan_log(0, text, 49, 9)
    original49 = next(iter(json.loads((checker.NATIVE.parent / 'valid-forced-placed.json').read_text())['modules'].values()))
    routed49 = next(iter(json.loads((small.PARENT.parent / 'fixed_49-routed.json').read_text())['modules'].values()))
    assert small.compare_route(original49, routed49) == report['saved_native_49_comparison']
    original286 = next(iter(json.loads((checker.TRANSFER.parent / 'corrected-transfer-input.json').read_text())['modules'].values()))
    routed286 = next(iter(json.loads((SMALL.parent / 'routed-286.json').read_text())['modules'].values()))
    identity286 = small.compare_route(original286, routed286)
    assert all(report['fresh_native_286_comparison'][k] == v for k, v in identity286.items())
    features, repeated = checker.checkpoint.parse_native_features((SMALL.parent / 'control-286.fasm').read_text())
    selected = json.loads(checker.checkpoint.SELECTED.read_text())
    transfer = json.loads(checker.TRANSFER.read_text())
    originals = {n: selected[s] for n, s in transfer['control_origins'].items()}
    placements = json.loads((SMALL.parent / 'placement-286.json').read_text())
    with SiteBELMap(DATABASE, CONSTIDS) as database:
        compared = checker.compare_selected(features, {n: placements[n] for n in originals}, originals,
            {n: routed286['cells'][n] for n in originals}, database.global_label)
    recorded = report['fresh_native_286_comparison']
    assert compared == recorded['primitive_features'] and len(features) == recorded['FASM_features']
    assert repeated == recorded['repeated_STEPDOWN_lines']
    return report, built


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--placed', type=Path, required=True)
    args = parser.parse_args(); placed_path = args.placed.resolve(strict=True)
    assert placed_path.is_relative_to(ROOT / 'build/openxc7')
    out = ROOT / f'build/openxc7/full-prefix-corrected-scan-route-{time.time_ns()}'; out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py'); shutil.copyfile(CONTROL, out / 'executed_control_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        scope=__doc__, source={}, commands=[], channels=32, kernels=16, parallel_products=512,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588,
        placed_report=str(placed_path), small_checker_report=str(SMALL), native_routing_executed=False,
        full_native_imported_checkpoint_scan_executed=False, full_native_FASM_emitted=False,
        full_DSP_BRAM_source_defined_features_compared=False, production_source_before=source_revision(),
        **{key: False for key in FLAGS})
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, timeout):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')), cwd=str(ROOT),
            expected_returncode=0, timeout_seconds=timeout, status='RUNNING')
        report['commands'].append(step); save(); start = time.monotonic()
        def limits():
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); resource.setrlimit(resource.RLIMIT_AS, (12 * 1024 ** 3, 12 * 1024 ** 3))
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True, preexec_fn=limits) as process:
                step['pid'] = process.pid; save()
                try: code = process.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(); step['returncode'] = process.returncode; raise
            step['returncode'] = code; text = Path(step['log']).read_text()
            assert code == 0 and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text), text[-4000:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'; return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3); save()
    print(out / 'report.json', flush=True); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        placed = json.loads(placed_path.read_text()); verify_placed_metadata(placed)
        qualification = Path(placed['qualified_engine_report']); candidate, before = verify_placement_engine(qualification)
        bind_report(placed_path, placed, before); verify_bindings(before)
        assert placed['executable'] == candidate['executable'] and placed['native_version'] == candidate['native_version']
        support, built = verify_small_evidence(before)
        placing_build = json.loads(Path(candidate['candidate_build_report']).read_text())
        assert Path(placing_build['parent_build_report']) == Path(built['parent_build_report']), 'Different corrected-DSP base engines'
        assert support['production_source_after'] == placed['production_source_after'] == report['production_source_before']
        for key, verifier in (('packed_report', verify_packed_metadata), ('prepared_report', verify_prepared_metadata)):
            path = Path(placed[key]).resolve(strict=True); assert str(path) in before
            parent = json.loads(path.read_text()); verifier(parent); bind_report(path, parent, before)
        files = {Path(__file__).resolve(), CONTROL, Path(sys.executable).resolve()}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
            if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for path in files:
            sha = digest(path); assert str(path) not in before or before[str(path)] == sha
            before[str(path)] = sha
        verify_bindings(before)
        executable = support['executable']['path']; report.update(source=before, executable=support['executable'],
            native_version=support['native_version'], placement_and_route_share_corrected_DSP_base=True,
            placement_engine_not_executed_during_route=True, stage='software_controls')
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], 120)
        run('generated_check', ['make', 'generated-check'], 120)
        version = run('version', [executable, '--version'], 60).strip(); assert version == support['native_version']
        assembly = run('linked_router_check', ['objdump', '-d', '--disassemble=' + checker.checkpoint.ROUTER_SYMBOL, executable], 120)
        assert re.search(r'\bcall\s+[0-9a-f]+ <' + checker.checkpoint.CHECK_SYMBOL + '>', assembly)
        design_path = (ROOT / placed['placed_design']).resolve(strict=True)
        assert design_path.is_relative_to(placed_path.parent) and str(design_path) in before
        design = json.loads(design_path.read_text()); module, labels = native_export_module(design, version)
        verify_placed_module(module, placed['placement_checks']['primitive_counts'], placed['placement_checks']['retained_kernel_dsps'])
        pairs = audit_pairs(module); roles = local_carry_roles(module)
        report.update(full_bound_cells=len(module['cells']), fixed_logic_pairs=pairs['logic_pairs_compared'],
            expected_local_carry_DI_roles=len(roles), checkpoint_label_translation=labels)
        del pairs, roles
        ports = module['ports']; footprint_path = out / 'comparison-only-physical-footprint.json'
        with SiteBELMap(DATABASE, CONSTIDS) as database: footprint = physical_footprint(module, database)
        footprint_path.write_text(json.dumps(footprint, separators=(',', ':'))); del footprint
        proof_path = out / 'comparison-only-logical-input.json'; proof_path.write_text(json.dumps(proof_module(module), separators=(',', ':')))
        empty_path = out / 'comparison-only-empty-port-source.json'; empty_path.write_text(json.dumps(comparison_port_source(module), separators=(',', ':')))
        report['comparison_artifact_bindings'] = {str(p.relative_to(ROOT)): digest(p) for p in (footprint_path, proof_path, empty_path)}
        del design, module
        text, translation = packing_xdc((ROOT / 'fpga/ypcb.xdc').read_text()); assert translation == placed['constraint_translation']
        xdc = out / 'literal.xdc'; xdc.write_text(text)
        output, fasm, placements = (out / name for name in ('routed.json', 'full-board.fasm', 'native-placement.json'))
        argv = checker.checkpoint.resume_argv(executable, design_path, labels['emitted_context_label'], xdc, output, route=True)
        argv += ['-o', 'rknpu-check-imported-placement=fixed-lut-v1', '-o', 'fasm=' + str(fasm), '-o', 'placement=' + str(placements)]
        report.update(stage='native_scan_and_route', native_routing_executed=True,
            hardware_execution_input=str(design_path), constraint_translation=translation)
        log = run('native_scan_and_route', argv, 43200)
        check_full_scan(log, report['full_bound_cells'], report['fixed_logic_pairs'], report['expected_local_carry_DI_roles'])
        report['full_native_imported_checkpoint_scan_executed'] = True
        assert all(digest(ROOT / name) == sha for name, sha in report['comparison_artifact_bindings'].items())
        routed = json.loads(output.read_text()); assert routed['creator'] == labels['producer'] and list(routed['modules']) == [labels['emitted_context_label']]
        module = next(iter(routed['modules'].values()))
        footprint = json.loads(footprint_path.read_text())
        report['physical_resource_checks'] = verify_routed_footprint(module, footprint, placed['placement_checks']['retained_kernel_dsps']); del footprint
        empty_source = json.loads(empty_path.read_text()); view, annotations = full_export_view(empty_source, module)
        report['comparison_only_empty_port_annotations'] = annotations
        canonical = proof_module(view, ports); del routed, module, view, empty_source
        report['original_logical_circuit_identity'] = assert_circuit_identity(json.loads(proof_path.read_text()), canonical); del canonical
        report['stage'] = 'full_native_feature_comparison'; save()
        selected = json.loads(checker.checkpoint.SELECTED.read_text())
        report['full_DSP_BRAM_FASM_feature_comparison'] = verify_full_features(fasm, placements, output, selected, placed['placement_checks']['retained_kernel_dsps'])
        verify_bindings(before); report['production_source_after'] = source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status=ROUTED, stage='complete', full_native_FASM_emitted=True,
            full_DSP_BRAM_source_defined_features_compared=True, routed_design=str(output.relative_to(ROOT)), native_FASM=str(fasm.relative_to(ROOT)))
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
