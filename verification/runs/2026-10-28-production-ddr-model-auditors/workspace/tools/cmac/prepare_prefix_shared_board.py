#!/usr/bin/env python3
"""Build a separate full C32/K16 shared-cone candidate, never a bitstream.

Retain the original command/board shell, all sixteen kernels/512 DSP products,
state, primitive parameters and numerical policy. Exact reverse expansion
must restore the entire original graph. Actual Yosys export/checks and fresh
host controls are required; numerical replay and physical acceptance remain
separate. Original running tools and inputs are never edited.
"""
from collections import Counter
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent),
                str(Path(__file__).resolve().parents[1] / 'openxc7')]
from evidence import ROOT, source_revision, timestamp
from prefix_shared_cones import lift, verify_lift, PRIVATE, SHARED
from test_dsp_prefix_observed_mapped_board import verify_mapping_report
from prepare_shared_board import physical_counts
from lane_dsp_library import timing_only_view
from test_fixed_mapped_array import hardware_instance_aliases
from pair_board_luts import implementation_module_aliases
from export_board_netlist import structural_board_verilog
from prepare_prefix_pack_input import (verify_stream_manifest, restore_export_direction_metadata,
                                       assert_circuit_identity)

TOP = 'ypcb_cmac_array_top'
CONTROL = ROOT / 'tests/cmac/test_prefix_shared_cones.py'
PARENT = ROOT / 'build/rknpu-dsp-prefix-observed-board-mapping/1791308955335106261/report.json'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping-report', type=Path, default=PARENT)
    args = parser.parse_args()
    parent_path = args.mapping_report.resolve(strict=True)
    assert parent_path.is_relative_to(ROOT)
    parent = json.loads(parent_path.read_text())
    verify_mapping_report(parent)
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024**3, 6 * 1024**3))
    out = ROOT / f'build/rknpu-dsp-prefix-shared-board/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='source_admission', started_utc=timestamp(),
        python=platform.python_version(), supervisor_pid=__import__('os').getpid(),
        scope=__doc__, commands=[], source={}, production_source_before=source_revision(),
        mapping_report=str(parent_path), channels=32, kernels=16, parallel_products=512,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588,
        circuit_lift_verified=False, numerical_netlist_acceptance=False,
        native_packing_executed=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False)

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
        before = {}
        for key in ('source', 'artifacts'):
            before.update(verify_stream_manifest(parent[key]))
        before.update(verify_stream_manifest(parent['external_mapping_inputs'], external=True))
        used = {Path(m.__file__).resolve() for m in list(sys.modules.values())
                if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')}
        used.update((Path(__file__).resolve(), parent_path, CONTROL,
                     ROOT / 'tests/cmac/test_shared_kernel_cones.py', Path(shutil.which('yosys')).resolve()))
        before.update({str(p): digest(p) for p in used})
        report['source'] = before
        save()
        run([sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover',
             '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], 'software_controls')
        run(['make', 'generated-check'], 'generated_check')
        report['yosys_version'] = run(['yosys', '-V'], 'version').strip()
        assert report['yosys_version'] == parent['tool_version']
        netlist = parent_path.parent / 'mapped_hierarchy.json'
        assert str(netlist) in before
        original = json.loads(netlist.read_text())
        kernel = parent['preserved_kernel']
        candidate, certificate = lift(original, TOP, kernel, 16)
        assert certificate['analysis']['per_kernel_cells']['DSP48E1'] == 32
        assert len(certificate['analysis']['omitted_DSP_pins_barriered']) == 32
        original_view, audit_before = timing_only_view(original['modules'])
        candidate_view, audit_after = timing_only_view(candidate['modules'])
        assert audit_before == audit_after and len(audit_before) == 4
        original_counts = physical_counts(original_view, TOP, {TOP, kernel})
        candidate_counts = physical_counts(candidate_view, TOP, {TOP, PRIVATE, SHARED})
        assert dict(original_counts) == parent['cells']
        assert original_counts - candidate_counts == Counter(certificate['analysis']['removable_cells'])
        assert not candidate_counts - original_counts
        assert candidate_counts['DSP48E1'] == 515 and candidate_counts['RAMB36E1'] == 6
        assert {k: v for k, v in candidate_counts.items() if k.startswith('FD')} == {
            k: v for k, v in original_counts.items() if k.startswith('FD')}
        report.update(stage='candidate_export', circuit_lift_verified=True,
            cells_before=dict(original_counts), cells_after=dict(candidate_counts),
            removed_cells=dict(original_counts - candidate_counts), timing_counter_qualifiers=audit_before)
        save()
        # These are real full-candidate guard negatives, not changed hardware inputs.
        corrupted = deepcopy(candidate)
        lut = next(c for c in corrupted['modules'][SHARED]['cells'].values() if c['type'].startswith('LUT'))
        init = lut['parameters']['INIT']
        assert set(init) <= {'0', '1'}
        lut['parameters']['INIT'] = ('1' if init[0] == '0' else '0') + init[1:]
        try:
            verify_lift(original, corrupted, certificate)
        except AssertionError:
            report['actual_shared_INIT_bit_corruption_rejected'] = True
        else:
            raise AssertionError('Accepted full-candidate LUT corruption')
        corrupted = deepcopy(candidate)
        name = next(n for n, c in corrupted['modules'][PRIVATE]['cells'].items() if c['type'] == 'DSP48E1')
        del corrupted['modules'][PRIVATE]['cells'][name]
        try:
            verify_lift(original, corrupted, certificate)
        except AssertionError:
            report['actual_private_DSP_removal_rejected'] = True
        else:
            raise AssertionError('Accepted full-candidate DSP removal')
        del corrupted, original_view, candidate_view
        certificate_path = out / 'lift_certificate.json'
        certificate_path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + '\n')
        candidate_path = out / 'shared_hierarchy.json'
        candidate_path.write_text(json.dumps(candidate, separators=(',', ':')) + '\n')
        implementation = dict(modules={n: candidate['modules'][n] for n in (TOP, PRIVATE, SHARED)})
        implementation, module_aliases = implementation_module_aliases(implementation)
        exported, instance_aliases = hardware_instance_aliases(implementation)
        (out / 'hardware_aliases.json').write_text(json.dumps(dict(modules=module_aliases,
            instances=instance_aliases), indent=2, sort_keys=True) + '\n')
        sv = out / 'shared_board.v'
        sv.write_text(structural_board_verilog(exported))
        script = out / 'export.ys'
        roundtrip = out / 'export_roundtrip.json'
        script.write_text('read_verilog -sv ' + json.dumps(str(sv)) + ';\nwrite_json ' +
                          json.dumps(str(roundtrip)) + ';\n')
        run(['yosys', '-Q', '-T', '-s', script], 'export', 600)
        imported = json.loads(roundtrip.read_text())
        report['export_direction_annotations_restored'] = restore_export_direction_metadata(imported, exported)
        report['export_circuit_identity'] = assert_circuit_identity(exported, imported)
        check = out / 'check.ys'
        check.write_text('read_verilog -lib +/xilinx/cells_sim.v;\nread_verilog -sv ' +
            json.dumps(str(sv)) + ';\nhierarchy -check -top ' + TOP + ';\ncheck -assert;\nstat -tech xilinx;\n')
        run(['yosys', '-Q', '-T', '-s', check], 'hierarchy_check', 600)
        verify_lift(original, json.loads(candidate_path.read_text()), certificate)
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed candidate preparation input'
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='PREPARED_FULL_C32K16_PREFIX_SHARED_CONE_CIRCUIT_NOT_NUMERICAL_OR_PHYSICAL_ACCEPTANCE',
            stage='complete', controls=28, retained_cmac_dsps=512, retained_shell_dsps=3,
            retained_kernel_instances=16, original_kernel=kernel,
            private_module=PRIVATE, shared_module=SHARED,
            lut_count=sum(v for k, v in candidate_counts.items() if k.startswith('LUT')),
            ff_count=sum(v for k, v in candidate_counts.items() if k.startswith('FD')))
    except BaseException as error:
        report.update(status='FAIL_PREFIX_SHARED_CANDIDATE', error=repr(error))
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
