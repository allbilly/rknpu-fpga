#!/usr/bin/env python3
"""Source-bound structural admission of the completed prefix board diagnostics.

Recompute the actual 288-bit dead-cone proof and all 54 RAM normalization
proofs. Admit only their exact original 288/32 diagnostic lines, then apply the
unchanged original source/ABC gate to every remaining line. Recheck complete
independent numerical parents and all original remaining mapping/identity
gates. Preserve the original FAIL: this separate read-only admission neither
reruns synthesis nor proves full-board netlist numerical behavior or FPGA fit.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, fingerprint, timestamp
import audit_dsp_prefix_initial_driver_cones as cones
import capture_dsp_prefix_board_normalization as ram

mapper = ram.mapper
RAM_REPORT = 'build/rknpu-dsp-prefix-board-normalization/1791303221286845998/report.json'
CONE_REPORT = 'build/rknpu-dsp-prefix-initial-driver-cones/1791306673247975368/report.json'
STATUS = 'PASS_SOURCE_BOUND_FULL_C32K16_PREFIX_BOARD_STRUCTURAL_DIAGNOSTIC_ADMISSION_ONLY'


def validate_reports(original, memory, cone, fanout, original_path):
    assert original['status'] == 'FAIL' and original['finished_utc']
    assert 'Unknown whole-board source diagnostics' in original['error']
    assert original['commands'][-1]['status'] == 'FAIL' and original['commands'][-1]['returncode'] == 0
    assert memory['status'] == 'CAPTURED_FULL_C32K16_BOARD_RAM_NORMALIZATION_DIAGNOSTIC_ONLY'
    assert cone['status'] == 'PASS_SOURCE_BOUND_INITIAL_DRIVER_DEAD_CONES_ONLY'
    assert fanout['status'] == 'CAPTURED_FULL_BOARD_INITIAL_DRIVER_FANOUT_DIAGNOSTIC_ONLY'
    for report in (memory, cone, fanout):
        assert report['stage'] == 'complete' and report['finished_utc']
        assert (report['channels'], report['kernels'], report['parallel_products']) == (32, 16, 512)
        assert report['tool_version'] == original['tool_version']
        for field in ('mapping_diagnostics_accepted', 'numerical_netlist_acceptance',
                      'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
            assert report[field] is False, ('Invalid diagnostic evidence claim', field)
    expected = str(original_path.relative_to(ROOT))
    assert memory['original_report'] == fanout['original_report'] == expected
    assert memory['original_source_sha256'] == original['source']['sha256']
    assert memory['final_original_circuit_identity'] and memory['original_warning_gate_unchanged']
    assert memory['early_temporary_driver_diagnostics_admitted'] is False
    assert (memory['logged_ram_port_resizes'], memory['actual_ram_port_resizes']) == (32, 54)
    assert (memory['part'], memory['clock_period_ns'], memory['mapped_kernel_instances'], memory['retained_cmac_dsps']) == (
        'xc7k480tffg1156-2', 20, 16, 512)
    assert cone['verified_warning_bits'] == 288 and cone['original_warning_gate_unchanged']
    assert fanout['initial_driver_notices'] == 288 and fanout['checks_problem_counts'] == [288, 0]
    assert fanout['all_initial_notice_bits_have_no_direct_consumers'] is False
    for report in (memory, fanout):
        assert all(step['returncode'] == 0 and step['status'] == 'PASS_TOOL_EXECUTION_ONLY' for step in report['commands'])


def audit_log(text, top, kernel, proved_drivers, proved_resizes):
    """No generic warning suppression: exact bound lines only, once each."""
    assert sum(proved_drivers.values()) == len(proved_drivers) == 288
    assert cones.capture.driver_notices(text) == proved_drivers, 'Different initial driver diagnostics'
    assert len(proved_resizes) == 32 and ram.resize_notices(text, top) == proved_resizes, 'Different RAM diagnostics'
    resized_lines = Counter(
        f'Warning: Resizing cell port {top}.{cell}.{pin} from {widths[0]} bits to {widths[1]} bits.'
        for (cell, pin), widths in proved_resizes.items())
    admitted = proved_drivers + resized_lines
    actual = Counter(line for line in text.splitlines() if line in admitted)
    assert actual == admitted, 'Missing or repeated proved warning'
    residual = '\n'.join(line for line in text.splitlines() if line not in admitted) + '\n'
    original_contract = mapper.audit_board_mapping_log(residual, top, kernel)
    counts = [int(value) for value in re.findall(r'Found and reported (\d+) problems\.', text)]
    assert counts == [288, 0, 0, 0], ('Changed original CHECK sequence', counts)
    return dict(exact_proved_driver_notices=288, exact_proved_ram_notices=32,
                original_source_and_abc_gate=original_contract, original_check_counts=counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ram-report', type=Path, default=Path(RAM_REPORT))
    parser.add_argument('--cone-report', type=Path, default=Path(CONE_REPORT))
    args = parser.parse_args()
    rp, cp = [mapper.replay.workspace_path(path) for path in (args.ram_report, args.cone_report)]
    memory, cone = [json.loads(path.read_text()) for path in (rp, cp)]
    op, fp = [mapper.replay.workspace_path(Path(name)) for name in (memory['original_report'], cone['capture_report'])]
    original, fanout = [json.loads(path.read_text()) for path in (op, fp)]
    validate_reports(original, memory, cone, fanout, op)
    assert str(fp.relative_to(ROOT)) in cone['source']['files']
    paths = {op, rp, cp, fp, Path(__file__).resolve(), Path(cones.__file__).resolve(), Path(ram.__file__).resolve()}
    for parent, fields in ((original, ('source', 'compile_inputs', 'artifacts')),
                           (memory, ('source', 'artifacts')), (fanout, ('source', 'artifacts')), (cone, ('source',))):
        for field in fields:
            bound = [ROOT / name for name in parent[field]['files']]
            assert fingerprint(bound) == parent[field], ('Changed bound mapping/proof evidence', field)
            paths.update(bound)
    before = fingerprint(paths)
    out = ROOT / f'build/rknpu-dsp-prefix-board-diagnostic-admission/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='independent_revalidation', started_utc=timestamp(), source=before,
                  parent_reports=dict(original=str(op.relative_to(ROOT)), ram=str(rp.relative_to(ROOT)),
                                      cones=str(cp.relative_to(ROOT)), fanout=str(fp.relative_to(ROOT))),
                  channels=32, kernels=16, parallel_products=512,
                  intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20,
                  tool_version=original['tool_version'], mapping_diagnostics_accepted=False,
                  structural_mapping_acceptance=False, numerical_netlist_acceptance=False,
                  physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
                  original_failed_report_preserved=True, synthesis_rerun=False, scope=__doc__)
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    save()
    print(out / 'report.json', flush=True)
    try:
        spec, _ = mapper.inputs()
        assert (spec['top'], spec['part'], spec['clock_period_ns']) == ('ypcb_cmac_array_top', 'xc7k480tffg1156-2', 20)
        log = (op.parent / 'mapping.log').read_text()
        drivers = cones.capture.driver_notices(log)
        resizes = ram.resize_notices(log, spec['top'])
        initial = json.loads((fp.parent / 'after_proc.json').read_text())
        cleaned = json.loads((fp.parent / 'after_clean.json').read_text())
        assert cones.normalized_inventory(initial, drivers) == fanout['initial_driver_fanout']
        assert cones.audit_cones(initial, cleaned, drivers) == cone['dead_cone_audit']
        assert sum(item['warning_bits'] for item in cone['dead_cone_audit']) == 288
        assert sum(item['dead_cone_cells'] for item in cone['dead_cone_audit']) == 107
        assert {kind for item in cone['dead_cone_audit'] for kind in item['dead_cone_types']} == {'$mux'}
        assert (fp.parent / 'frontend_capture.ys').read_text() == cones.capture.frontend_capture_script(
            (op.parent / 'mapping.ys').read_text(), fp.parent)
        assert (rp.parent / 'capture.ys').read_text() == ram.capture_script(
            (op.parent / 'mapping.ys').read_text(), ram.FLAGS, op.parent, rp.parent)
        assert cones.capture.driver_notices((fp.parent / 'frontend.log').read_text()) == drivers
        assert ram.resize_notices((rp.parent / 'mapping.log').read_text(), spec['top']) == resizes
        pre = json.loads((rp.parent / 'before.json').read_text())
        final = json.loads((rp.parent / 'mapped_hierarchy.json').read_text())
        assert ram.audit_normalization(pre, final, spec['top'], resizes) == memory['normalization_audit']
        assert len(memory['normalization_audit']) == 54
        mapped = json.loads((op.parent / 'mapped_hierarchy.json').read_text())
        assert mapper.circuit_signature(final) == mapper.circuit_signature(mapped)
        report['source_bound_diagnostic_admission'] = audit_log(log, spec['top'], original['preserved_kernel'], drivers, resizes)
        report['stage'] = 'original_remaining_structure_and_parent_gates'
        save()
        ap, bp = [ROOT / original['parent_reports'][name] for name in ('area', 'board')]
        area, raw, _ = mapper.verify_area(ap)
        _, board_paths, _ = mapper.verify_board(bp, spec)
        mapper.validate_shared_prerequisites(area, board_paths)
        frozen, kernel, kernel_counts = mapper.partition(raw)
        assert kernel == original['preserved_kernel']
        part = json.loads((op.parent / 'cmac_partition.json').read_text())
        assert cones.capture.frontend.validate_frontend(cleaned, spec['top'], kernel, part) == fanout['compiled_hierarchy']
        counts, shell, qualifiers = mapper.validate_mapped(mapped, spec['top'], kernel, frozen['modules'][kernel], kernel_counts)
        assert dict(counts) == memory['cells'] and dict(shell) == memory['shell_cells']
        estimates = re.findall(r'Estimated number of LCs:\s+(\d+)', log)
        assert estimates
        mapper.array.validate_sources()
        assert fingerprint(paths) == before
        report.update(status=STATUS, stage='complete', mapping_diagnostics_accepted=True,
                      structural_mapping_acceptance=True, independent_numerical_parents_revalidated=True,
                      mapped_kernel_instances=16, retained_cmac_dsps=512,
                      kernel_circuit_identity='PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE',
                      cells=dict(counts), shell_cells=dict(shell), reused_kernel_cells=dict(kernel_counts),
                      timing_qualifier_counter_audit=qualifiers, dsp_count=counts['DSP48E1'],
                      lut_count=sum(value for kind, value in counts.items() if kind.startswith('LUT')),
                      ff_count=sum(value for kind, value in counts.items() if kind.startswith('FD')),
                      estimated_logic_cells=int(estimates[-1]), mapped_graph=str((op.parent / 'mapped_hierarchy.json').relative_to(ROOT)))
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        save()


if __name__ == '__main__':
    main()
