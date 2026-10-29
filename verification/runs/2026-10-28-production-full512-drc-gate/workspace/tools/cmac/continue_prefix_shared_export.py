#!/usr/bin/env python3
"""Revalidate a saved full prefix lift and export its unchanged DSP settings.

The first generic-export failure and its source remain untouched. Use the
existing five-setting DSP exporter without pin defaults, parameter repairs,
arithmetic changes or pruning. This is fresh structural/export evidence only;
no numerical, native packing, physical signoff or bitstream is inferred.
"""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import resource
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent),
                str(Path(__file__).resolve().parents[1] / 'openxc7')]
from evidence import ROOT, source_revision, timestamp
from prefix_shared_cones import verify_lift, PRIVATE, SHARED
from prepare_shared_board import physical_counts
from lane_dsp_library import timing_only_view
from test_dsp_prefix_observed_mapped_board import verify_mapping_report
from test_fixed_mapped_array import hardware_instance_aliases
from pair_board_luts import implementation_module_aliases
from export_dsp_prefix_board_netlist import structural_board_verilog, DSP_STRINGS
from prepare_prefix_pack_input import restore_export_direction_metadata, assert_circuit_identity

TOP = 'ypcb_cmac_array_top'
PARENT = ROOT / 'build/rknpu-dsp-prefix-shared-board/1791470175035752151/report.json'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_preparation(parent):
    assert parent['status'] == 'FAIL_PREFIX_SHARED_CANDIDATE' and parent['finished_utc']
    assert parent['stage'] == 'candidate_export'
    assert parent['error'] == "AssertionError('Unsupported string primitive parameter')"
    assert (parent['channels'], parent['kernels'], parent['parallel_products'],
            parent['intended_part'], parent['intended_clock_period_ns'], parent['seed']) == (
                32, 16, 512, 'xc7k480tffg1156-2', 20, 3588)
    for flag in ('circuit_lift_verified', 'actual_shared_INIT_bit_corruption_rejected',
                 'actual_private_DSP_removal_rejected'):
        assert parent[flag] is True
    for flag in ('numerical_netlist_acceptance', 'native_packing_executed', 'physical_fit_verified',
                 'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
        assert parent[flag] is False
    assert [c['label'] for c in parent['commands']] == ['software_controls', 'generated_check', 'version']
    assert all(c['status'] == 'PASS_TOOL_OR_SOFTWARE_CONTROL_ONLY' and c['returncode'] == 0
               for c in parent['commands'])
    assert parent['cells_before']['DSP48E1'] == parent['cells_after']['DSP48E1'] == 515
    assert parent['cells_before']['RAMB36E1'] == parent['cells_after']['RAMB36E1'] == 6
    assert sum(v for k, v in parent['removed_cells'].items() if k.startswith('LUT')) == 14610
    assert parent['removed_cells']['MUXF7'] == 105
    assert not any(k.startswith('FD') or k in ('DSP48E1', 'RAMB36E1') for k in parent['removed_cells'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation-report', type=Path, default=PARENT)
    args = parser.parse_args()
    pp = args.preparation_report.resolve(strict=True)
    assert pp.is_relative_to(ROOT / 'build/rknpu-dsp-prefix-shared-board')
    parent = json.loads(pp.read_text())
    validate_preparation(parent)  # Fail before output/tools for incomplete/wrong scope.
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024**3, 6 * 1024**3))
    out = ROOT / f'build/rknpu-dsp-prefix-shared-export/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='source_revalidation', started_utc=timestamp(),
        python=platform.python_version(), source={}, commands=[], scope=__doc__,
        original_failed_parent=str(pp), production_source_before=source_revision(),
        channels=32, kernels=16, parallel_products=512, intended_part='xc7k480tffg1156-2',
        intended_clock_period_ns=20, seed=3588, old_failure_relabelled=False,
        numerical_netlist_acceptance=False, native_packing_executed=False, physical_fit_verified=False,
        timing_signoff=False, electrical_verified=False, drc_signoff=False,
        bitstream_emitted=False, hardware_programmed=False)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(argv, label, timeout=120):
        log = out / (label + '.log')
        step = dict(argv=list(map(str, argv)), label=label, log=str(log), status='RUNNING')
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with log.open('w') as stream:
                result = subprocess.run(step['argv'], cwd=ROOT, stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=timeout)
            step['returncode'] = result.returncode
            text = log.read_text()
            assert result.returncode == 0
            assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:', text), text[-2000:]
            step['status'] = 'PASS_TOOL_OR_SOFTWARE_CONTROL_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save()
    try:
        before = {**parent['source'], **parent['artifacts'], str(pp): digest(pp)}
        paths = {Path(m.__file__).resolve() for m in list(sys.modules.values())
                 if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')}
        paths.update(ROOT / ('tests/cmac/' + name) for name in (
            'test_prefix_shared_cones.py', 'test_shared_kernel_cones.py',
            'test_dsp_prefix_board_export_control.py', 'test_prefix_shared_export_control.py'))
        before.update({str(p): digest(p) for p in paths})
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed failed-preparation source/artifact'
        assert parent['production_source_before'] == report['production_source_before']
        report['source'] = before
        save()
        for pattern, label in (('test_prefix_shared_cones.py', 'sharing_controls'),
                ('test_dsp_prefix_board_export_control.py', 'DSP_export_controls'),
                ('test_prefix_shared_export_control.py', 'continuation_controls')):
            run([sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover',
                 '-s', 'tests/cmac', '-p', pattern, '-v'], label)
        run(['make', 'generated-check'], 'generated_check')
        report['yosys_version'] = run(['yosys', '-V'], 'version').strip()
        assert report['yosys_version'] == parent['yosys_version']
        mp = Path(parent['mapping_report'])
        mapping = json.loads(mp.read_text())
        verify_mapping_report(mapping)
        assert str(mp) in before
        original = json.loads((mp.parent / 'mapped_hierarchy.json').read_text())
        candidate_path = pp.parent / 'shared_hierarchy.json'
        certificate_path = pp.parent / 'lift_certificate.json'
        assert str(candidate_path) in before and str(certificate_path) in before
        candidate = json.loads(candidate_path.read_text())
        certificate = json.loads(certificate_path.read_text())
        verify_lift(original, candidate, certificate)
        assert certificate['instances'] == 16 and certificate['kernel'] == mapping['preserved_kernel']
        assert certificate['analysis']['per_kernel_cells']['DSP48E1'] == 32
        assert len(certificate['analysis']['omitted_DSP_pins_barriered']) == 32
        view, counter_audit = timing_only_view(candidate['modules'])
        counts = physical_counts(view, TOP, {TOP, PRIVATE, SHARED})
        assert dict(counts) == parent['cells_after'] and counts['DSP48E1'] == 515 and counts['RAMB36E1'] == 6
        assert Counter(parent['cells_before']) - counts == Counter(parent['removed_cells'])
        assert sum(v for k, v in counts.items() if k.startswith('LUT')) == 431206
        string_census = Counter()
        for module in (TOP, PRIVATE):
            for cell in candidate['modules'][module]['cells'].values():
                if cell['type'] == 'DSP48E1':
                    assert {k: cell['parameters'][k] for k in DSP_STRINGS} == DSP_STRINGS
                    string_census.update(cell['parameters'][k] for k in DSP_STRINGS)
        expected_strings = Counter(DSP_STRINGS.values())
        assert string_census == Counter({k: v * 35 for k, v in expected_strings.items()})
        report.update(stage='literal_DSP_export', circuit_lift_revalidated=True,
            cells=dict(counts), counter_timing_qualifiers=counter_audit, actual_DSP_string_values=dict(string_census))
        save()
        implementation = dict(modules={n: candidate['modules'][n] for n in (TOP, PRIVATE, SHARED)})
        implementation, modules = implementation_module_aliases(implementation)
        exported, instances = hardware_instance_aliases(implementation)
        assert json.loads((pp.parent / 'hardware_aliases.json').read_text()) == dict(modules=modules, instances=instances)
        sv = out / 'shared_board.v'
        sv.write_text(structural_board_verilog(exported))
        script, imported_path = out / 'export.ys', out / 'export_roundtrip.json'
        script.write_text('read_verilog -sv ' + json.dumps(str(sv)) + ';\nwrite_json ' +
                          json.dumps(str(imported_path)) + ';\n')
        run(['yosys', '-Q', '-T', '-s', script], 'export', 600)
        imported = json.loads(imported_path.read_text())
        report['direction_annotations_restored'] = restore_export_direction_metadata(imported, exported)
        report['export_circuit_identity'] = assert_circuit_identity(exported, imported)
        check = out / 'check.ys'
        check.write_text('read_verilog -lib +/xilinx/cells_sim.v;\nread_verilog -sv ' +
            json.dumps(str(sv)) + ';\nhierarchy -check -top ' + TOP + ';\ncheck -assert;\nstat -tech xilinx;\n')
        run(['yosys', '-Q', '-T', '-s', check], 'hierarchy_check', 600)
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed export continuation input'
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='PREPARED_FULL_C32K16_SHARED_PREFIX_LITERAL_EXPORT_NOT_NUMERICAL_OR_PHYSICAL_ACCEPTANCE',
            stage='complete', sharing_controls=28, DSP_export_controls=6, continuation_controls=9,
            retained_kernel_instances=16, retained_cmac_dsps=512, retained_shell_dsps=3,
            lut_count=431206, ff_count=sum(v for k, v in counts.items() if k.startswith('FD')),
            candidate=str(candidate_path), certificate=str(certificate_path), literal_export=str(sv))
    except BaseException as error:
        report.update(status='FAIL_PREFIX_SHARED_EXPORT_CONTINUATION', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p): digest(p) for p in out.iterdir()
                               if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)
        print(report['status'], flush=True)


if __name__ == '__main__':
    main()
