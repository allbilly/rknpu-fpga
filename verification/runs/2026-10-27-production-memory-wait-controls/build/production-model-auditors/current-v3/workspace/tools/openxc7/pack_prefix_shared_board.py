#!/usr/bin/env python3
"""Fresh full C32/K16 shared-prefix native packing; no placement or signoff.

Admit only the independently expanded, pad-roundtripped shared candidate and
the completed isolated DSP-constant encoder qualification. Measure this actual
packed graph, not the original candidate's graph or a projected resource count.
No numerical acceptance, constraint waiver, FPGA bits or programming follows.
"""
import argparse
from collections import Counter
import json
import mmap
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, source_revision, timestamp
from pack_prefix_board import TOP, DATABASE, CONSTIDS, JSON_WRITER, packing_xdc, native_export_module
from prepare_prefix_shared_pack_input import digest
from qualify_dsp_constant_candidate import QUALIFIED, COMMANDS
from audit_corrected_full_pack_identity import layout, records, cell_value, verify_native_pack_stage
from check_corrected_dsp_features import verify_corrected_packed
from check_full_native_features import full_inventory
from probe_prefix_native_config import verify_clock_admission
from audit_himbaechel_timing import audit
from pack_prefix_board import QUALIFICATION as TIMING_QUALIFICATION
from packed_lut_bound import LUTInputs, physical_positions, POLICY_DIGESTS

PREPARED = 'PREPARED_FULL_C32K16_SHARED_PREFIX_LITERAL_PACK_INPUT_NOT_NATIVE_PACKING_OR_SIGNOFF'
QUALIFICATION = ROOT / 'build/openxc7/dsp-constant-qualification-1791414657664905509/report.json'
CONTROL = ROOT / 'tests/cmac/test_prefix_shared_pack_control.py'
NATIVE_TYPES = {'BUFGCTRL', 'CARRY4', 'DSP48E1_DSP48E1', 'IOB33_INBUF_EN', 'IOB33_OUTBUF',
                'PAD', 'PSEUDO_GND', 'PSEUDO_VCC', 'RAMB36E1_RAMB36E1', 'SELMUX2_1', 'SLICE_FFX', 'SLICE_LUTX'}


def validate_prepared(report):
    assert report['status'] == PREPARED and report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'], report['retained_cmac_dsps'],
            report['retained_shell_dsps'], report['retained_kernel_instances'], report['intended_part'],
            report['intended_clock_period_ns'], report['seed']) == (32, 16, 512, 512, 3, 16, 'xc7k480tffg1156-2', 20, 3588)
    expanded = report['literal_expansion']
    groups = expanded['retained_private_instances']
    assert len(groups) == len(set(groups)) == 16
    assert len(expanded['retained_shared_instances']) == 1
    counts = expanded['cells']
    assert counts['DSP48E1'] == 515 and counts['RAMB36E1'] == 6
    assert sum(v for k, v in counts.items() if re.fullmatch('LUT[1-6]', k)) == 431206
    assert sum(v for k, v in counts.items() if k in ('FDCE', 'FDRE', 'FDSE', 'FDPE')) == 17519
    assert sum(counts.values()) == 488407
    assert report['physical_buffer_counts'] == {'IBUF': 2, 'OBUF': 3, 'BUFG': 1}
    assert (report['flatten_controls'], report['admission_controls']) == (6, 9)
    assert report['production_source_before'] == report['production_source_after']
    for key in ('independent_flatten_circuit_identity', 'physical_buffer_roundtrip_identity'):
        assert set(report[key]) == {TOP}
        assert report[key][TOP]['cells'] == 488407
        assert report[key][TOP]['bijective_wires'] > 0 and report[key][TOP]['endpoint_bits'] > 0
    labels = ['flatten_controls', 'admission_controls', 'generated_check', 'version', 'datadir',
              'independent_flatten', 'physical_IO_export']
    assert [s['label'] for s in report['commands']] == labels
    assert all(s['returncode'] == 0 and s['status'] == 'PASS_TOOL_OR_SOFTWARE_CONTROL_ONLY' for s in report['commands'])
    for key in ('arithmetic_optimized', 'runtime_BO_fixups', 'native_packing_executed', 'numerical_netlist_acceptance',
                'physical_fit_verified', 'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
        assert report[key] is False


def validate_qualification(report):
    assert report['status'] == QUALIFIED and report['stage'] == 'complete' and report['finished_utc']
    verify_native_pack_stage(report)
    assert report['production_source_before'] == report['production_source_after']
    assert [s['label'] for s in report['commands']] == COMMANDS
    for step in report['commands']:
        negative = step['label'] == 'invalid-forced'
        assert step['returncode'] == (125 if negative else 0)
        assert step['status'] == ('PASS_EXPECTED_REJECTION_ONLY' if negative else 'PASS_TOOL_EXECUTION_ONLY')
    assert str(JSON_WRITER) in report['source'] and str(DATABASE) in report['source']
    assert report['source'][report['executable']['path']] == report['executable']['sha256']


def native_census(path, selected, version, lut_observer=None):
    """Read the pinned complete cell table; header view is comparison-only.

    Native writer syntax is admitted by layout/records, whose source is bound.
    Removing cells from the tiny header view avoids loading a 600+ MB graph.
    This header view is never saved or passed to an execution tool.
    """
    counts, seen, primitives = Counter(), set(), {}
    with Path(path).open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        begin, end = layout(data)
        header = json.loads(data[:begin] + b'}\n    }\n  }\n}\n')
        module, translation = native_export_module(header, version)
        settings = module['settings']
        assert int(settings['pack'], 2) == 1 and int(settings['synth'], 2) == 1
        assert settings['frontend/top'] == TOP and settings['target_freq'] == '50000000.000000'
        assert all(int(settings.get(k, '0'), 2) == 0 for k in ('place', 'route'))
        for name, raw in records(data, begin, end):
            assert name not in seen, 'Duplicate native cell'
            seen.add(name)
            kinds = re.findall(rb'(?m)^          "type": "([^"\r\n]+)",$', raw)
            assert len(kinds) == 1, 'Missing/duplicate native cell type'
            kind = kinds[0].decode()
            assert kind in NATIVE_TYPES, 'Unmodeled native packed primitive: ' + kind
            counts[kind] += 1
            if kind == 'SLICE_LUTX' and lut_observer is not None:
                lut_observer(cell_value(raw))
            if kind in ('DSP48E1_DSP48E1', 'RAMB36E1_RAMB36E1'):
                assert name in selected, 'Unexpected native DSP/BRAM'
                primitives[name] = cell_value(raw)
        assert set(primitives) == set(selected), 'Missing native DSP/BRAM'
    return dict(cells=len(seen), primitive_counts=dict(counts), native_export_top_translation=translation), primitives


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    args = parser.parse_args()
    pp = args.prepared.resolve(strict=True)
    assert pp.is_relative_to(ROOT / 'build/openxc7') and pp.name == 'report.json'
    parent = json.loads(pp.read_text())
    native = json.loads(QUALIFICATION.read_text())
    validate_prepared(parent)
    validate_qualification(native)  # Reject unfinished/wrong profiles before creating output.
    resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    out = ROOT / f'build/openxc7/full-prefix-shared-native-pack-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='source_admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        source={}, commands=[], scope=__doc__, prepared_report=str(pp), encoder_qualification=str(QUALIFICATION),
        channels=32, kernels=16, parallel_products=512, intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20,
        seed=3588, executable=native['executable'], production_source_before=source_revision(),
        native_packing_executed=False, native_placement_executed=False, native_routing_executed=False,
        full_circuit_equivalence_claimed=False, numerical_netlist_acceptance=False, physical_fit_verified=False,
        timing_signoff=False, electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, timeout=120):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')),
                    timeout_seconds=timeout, status='RUNNING')
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                step['pid'] = proc.pid
                save()
                try:
                    code = proc.wait(timeout=timeout)
                except BaseException:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = Path(step['log']).read_text()
            assert code == 0, text[-3500:]
            assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text), text[-3500:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    print(out / 'report.json', flush=True)
    save()
    try:
        before = {}
        for manifest in (parent['source'], parent['artifacts'], native['source'], native['artifacts']):
            for name, sha in manifest.items():
                path = (ROOT / name).resolve(strict=True)
                assert str(path) not in before or before[str(path)] == sha, 'Conflicting inherited source'
                before[str(path)] = sha
        paths = {pp, QUALIFICATION, CONTROL, Path(sys.executable).resolve(), ROOT / 'fpga/ypcb.xdc', TIMING_QUALIFICATION,
                 ROOT / 'tests/cmac/test_corrected_dsp_feature_control.py',
                 ROOT / 'tests/cmac/test_packed_lut_bound.py', ROOT / 'tests/cmac/test_lut_sharing_bound.py'}
        paths.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for path in paths:
            sha = digest(path)
            assert str(path) not in before or before[str(path)] == sha, 'Changed inherited module'
            before[str(path)] = sha
        assert all(before.get(p) == sha for p, sha in POLICY_DIGESTS.items()), 'Unbound/different native LUT pairing policy'
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed admitted input/source'
        assert parent['production_source_after'] == native['production_source_after'] == report['production_source_before']
        report['source'] = before
        save()
        for label, name in (('software_controls', CONTROL.name), ('DSP_feature_controls', 'test_corrected_dsp_feature_control.py')):
            run(label, [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', name, '-v'])
        for label, name in (('LUT_census_controls', 'test_packed_lut_bound.py'), ('LUT_matching_controls', 'test_lut_sharing_bound.py')):
            run(label, [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        executable = native['executable']['path']
        report['native_version'] = run('version', [executable, '--version']).strip()
        assert report['native_version'] == native['native_version']
        report['timing_inventory'] = audit(TIMING_QUALIFICATION, DATABASE, CONSTIDS)
        input_path = Path(parent['pack_input']).resolve(strict=True)
        assert input_path.is_relative_to(pp.parent) and str(input_path) in before
        report['stage'] = 'literal_input_inventory'
        save()
        design = json.loads(input_path.read_text())
        assert set(design['modules']) == {TOP}
        cells = design['modules'][TOP]['cells']
        counts = dict(Counter(c['type'] for c in cells.values()))
        assert counts == {**parent['literal_expansion']['cells'], **parent['physical_buffer_counts']}
        selected = {n: c for n, c in cells.items() if c['type'] in ('DSP48E1', 'RAMB36E1')}
        groups = Counter(n.split('.')[0] for n, c in selected.items() if c['type'] == 'DSP48E1' and '.' in n)
        assert set(groups) == set(parent['literal_expansion']['retained_private_instances']) and set(groups.values()) == {32}
        del cells, design
        (out / 'actual-DSP-BRAM-input.json').write_text(json.dumps(selected, indent=2, sort_keys=True) + '\n')
        text, constraints = packing_xdc((ROOT / 'fpga/ypcb.xdc').read_text())
        xdc = out / 'literal.pack-only.xdc'
        xdc.write_text(text)
        output = out / 'packed.json'
        report.update(stage='native_pack', constraint_translation=constraints, native_packing_executed=True,
                      input_primitive_counts=counts, execution_input=str(input_path))
        log = run('native_pack', [executable, '--chipdb', DATABASE, '--device', 'xc7k480tffg1156-2', '--top', TOP,
            '--json', input_path, '-o', 'xdc=' + str(xdc), '--pack-only', '--freq', '50', '--seed', '3588',
            '--Werror', '--debug', '--write', output], 1800)
        verify_clock_admission(log, constraints)
        report['stage'] = 'complete_actual_native_census'
        save()
        collector = LUTInputs()
        census, packed = native_census(output, selected, report['native_version'], collector.observe)
        inventory = full_inventory(selected, packed)
        assert inventory == dict(groups)
        for name, cell in selected.items():
            if cell['type'] == 'DSP48E1':
                verify_corrected_packed(cell, packed[name])
        assert census['primitive_counts']['SLICE_FFX'] == 17519
        report['native_census'] = census
        report['stage'] = 'source_bound_LUT_matching'
        save()
        positions = physical_positions(log, census['primitive_counts']['SLICE_LUTX'])
        report['LUT_sharing_bound'] = collector.bound(census['primitive_counts']['SLICE_LUTX'], positions)
        cache = dict(schema=1, whole=collector.whole, positions=positions,
                     lut_cells=census['primitive_counts']['SLICE_LUTX'],
                     groups=[[sorted(inputs), count] for inputs, count in collector.groups.items()],
                     placement_assignment=False, hardware_execution_input=False)
        (out / 'actual-LUT-input-groups.json').write_text(json.dumps(cache, separators=(',', ':')) + '\n')
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed actual packing source/input'
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='PACKED_FULL_C32K16_SHARED_PREFIX_NATIVE_RESOURCE_CHARACTERIZATION_NOT_PLACED_FIT_OR_SIGNOFF',
            stage='complete', native_census=census, retained_kernel_dsps=inventory, retained_cmac_dsps=512,
            retained_shell_dsps=3, DSP_configurations_compared=515, extra_tile_only_ties_compared=4120,
            packed_design=str(output), complete_ordinary_wire_identity_proved=False, clock_constraint_admitted=True)
    except BaseException as error:
        report.update(status='FAIL_PREFIX_SHARED_NATIVE_PACK', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p): digest(p) for p in out.iterdir() if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)
        print(report['status'], flush=True)


if __name__ == '__main__':
    main()
