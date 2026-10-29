#!/usr/bin/env python3
"""Prepare unchanged full shared-prefix hardware for native packing, not signoff.

Expand all sixteen private kernels and the one shared combinational module.
Independently compare literal expansion with real Yosys flattening. Add only
the original five pads/one clock buffer; collapse them for another exact
circuit comparison. No optimization, runtime BO fixups, numerical acceptance,
native placement, bitstream emission or programming is performed.
"""
from collections import Counter
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
                str(Path(__file__).resolve().parents[1] / 'cmac')]
from evidence import ROOT, source_revision, timestamp
from prefix_shared_cones import PRIVATE, SHARED
from prefix_shared_flatten import flatten_shared
from prepare_prefix_pack_input import (restore_export_direction_metadata, assert_circuit_identity,
                                       remove_physical_buffers, EXPECTED_PORTS)
from test_fixed_mapped_array import hardware_instance_aliases
from pair_board_luts import implementation_module_aliases

TOP = 'ypcb_cmac_array_top'
STATUS = 'PREPARED_FULL_C32K16_SHARED_PREFIX_LITERAL_EXPORT_NOT_NUMERICAL_OR_PHYSICAL_ACCEPTANCE'
PARENT = ROOT / 'build/rknpu-dsp-prefix-shared-export/1791470852571972438/report.json'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_export(parent):
    assert parent['status'] == STATUS and parent['stage'] == 'complete' and parent['finished_utc']
    assert parent['circuit_lift_revalidated'] is True and parent['old_failure_relabelled'] is False
    assert (parent['channels'], parent['kernels'], parent['parallel_products'],
            parent['retained_kernel_instances'], parent['retained_cmac_dsps'], parent['retained_shell_dsps'],
            parent['intended_part'], parent['intended_clock_period_ns'], parent['seed']) == (
                32, 16, 512, 16, 512, 3, 'xc7k480tffg1156-2', 20, 3588)
    assert (parent['lut_count'], parent['ff_count'], parent['cells']['DSP48E1'],
            parent['cells']['RAMB36E1']) == (431206, 17519, 515, 6)
    assert parent['production_source_before'] == parent['production_source_after']
    assert (parent['sharing_controls'], parent['DSP_export_controls'], parent['continuation_controls']) == (28, 6, 9)
    assert set(parent['export_circuit_identity']) == {TOP, PRIVATE, SHARED}
    assert all(v['cells'] > 0 and v['bijective_wires'] > 0 and v['endpoint_bits'] > 0
               for v in parent['export_circuit_identity'].values())
    labels = ['sharing_controls', 'DSP_export_controls', 'continuation_controls',
              'generated_check', 'version', 'export', 'hierarchy_check']
    assert [c['label'] for c in parent['commands']] == labels
    assert all(c['status'] == 'PASS_TOOL_OR_SOFTWARE_CONTROL_ONLY' and c['returncode'] == 0
               for c in parent['commands'])
    for flag in ('numerical_netlist_acceptance', 'native_packing_executed', 'physical_fit_verified',
                 'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
        assert parent[flag] is False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export-report', type=Path, default=PARENT)
    args = parser.parse_args()
    pp = args.export_report.resolve(strict=True)
    assert pp.is_relative_to(ROOT / 'build/rknpu-dsp-prefix-shared-export')
    parent = json.loads(pp.read_text())
    validate_export(parent)  # Incomplete/different target fails before output/tools.
    resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
    out = ROOT / f'build/openxc7/full-prefix-shared-pack-input-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='source_admission', started_utc=timestamp(),
        python=platform.python_version(), source={}, commands=[], scope=__doc__,
        parent_report=str(pp), production_source_before=source_revision(), channels=32, kernels=16,
        parallel_products=512, intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588,
        arithmetic_optimized=False, runtime_BO_fixups=False, native_packing_executed=False,
        numerical_netlist_acceptance=False, physical_fit_verified=False, timing_signoff=False,
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
        before = {**parent['source'], **parent['artifacts'], str(pp): digest(pp)}
        imported = {Path(m.__file__).resolve() for m in list(sys.modules.values())
                    if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')}
        imported.update(ROOT / ('tests/cmac/' + name) for name in (
            'test_prefix_shared_flatten.py', 'test_shared_kernel_cones.py',
            'test_prefix_shared_pack_input_control.py'))
        imported.update(Path(shutil.which(name)).resolve() for name in ('yosys', 'yosys-config'))
        before.update({str(p): digest(p) for p in imported})
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed admitted export/source'
        assert parent['production_source_after'] == report['production_source_before']
        report['source'] = before
        save()
        for pattern, label in (('test_prefix_shared_flatten.py', 'flatten_controls'),
                              ('test_prefix_shared_pack_input_control.py', 'admission_controls')):
            run([sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover',
                 '-s', 'tests/cmac', '-p', pattern, '-v'], label)
        run(['make', 'generated-check'], 'generated_check')
        report['yosys_version'] = run(['yosys', '-V'], 'version').strip()
        assert report['yosys_version'] == parent['yosys_version']
        datadir = Path(run(['yosys-config', '--datdir'], 'datadir').strip())
        library = (datadir / 'xilinx/cells_sim.v').resolve(strict=True)
        assert str(library) in before and digest(library) == before[str(library)]
        candidate = json.loads(Path(parent['candidate']).read_text())
        implementation = dict(modules={n: candidate['modules'][n] for n in (TOP, PRIVATE, SHARED)})
        del candidate
        implementation, modules = implementation_module_aliases(implementation)
        aliased, instances = hardware_instance_aliases(implementation)
        del implementation
        assert modules == {}  # These public module names need no aliasing.
        assert json.loads((Path(parent['candidate']).parent / 'hardware_aliases.json').read_text()) == dict(
            modules=modules, instances=instances)
        exported_path = pp.parent / 'export_roundtrip.json'
        assert str(exported_path) in before
        exported = json.loads(exported_path.read_text())
        report['direction_annotations_restored'] = restore_export_direction_metadata(exported, aliased)
        report['admitted_export_identity'] = assert_circuit_identity(aliased, exported)
        del aliased
        assert {n: (p['direction'], len(p['bits'])) for n, p in exported['modules'][TOP]['ports'].items()} == EXPECTED_PORTS
        flat, audit = flatten_shared(exported, TOP, PRIVATE, SHARED, 16)
        del exported
        assert audit['cells'] == parent['cells']
        assert audit['cells']['DSP48E1'] == 515 and audit['cells']['RAMB36E1'] == 6
        assert len(audit['retained_private_instances']) == 16 and len(audit['retained_shared_instances']) == 1
        assert len(audit['private_output_aliases']) == len(audit['private_constant_outputs']) == 16
        assert all(r['formal_output_endpoints'] == [['result', 38], ['result', 39]]
                   for r in audit['private_output_aliases'])
        assert all((r['port'], r['index'], r['value']) == ('invalid', 0, '0')
                   for r in audit['private_constant_outputs'])
        assert not audit['shared_output_aliases'] and not audit['shared_constant_outputs']
        report.update(stage='independent_Yosys_flatten', literal_expansion=audit)
        save()
        literal = out / 'literal_flat.json'
        literal.write_text(json.dumps(flat, separators=(',', ':')) + '\n')
        del flat
        independent = out / 'yosys_flat.json'
        script = out / 'independent_flatten.ys'
        script.write_text(';\n'.join([
            'read_verilog -lib ' + json.dumps(str(library)),
            'read_verilog -sv ' + json.dumps(parent['literal_export']),
            'hierarchy -check -top ' + TOP, 'flatten -noscopeinfo', 'check -assert',
            'select ' + TOP, 'write_json -selected ' + json.dumps(str(independent))]) + '\n')
        run(['yosys', '-Q', '-T', '-s', script], 'independent_flatten', 1200)
        left, right = json.loads(literal.read_text()), json.loads(independent.read_text())
        report['independent_flatten_circuit_identity'] = assert_circuit_identity(left, right)
        del left, right
        report['stage'] = 'physical_IO_export'
        save()
        physical = out / 'pack_input.json'
        io_script = out / 'physical_io.ys'
        io_script.write_text(';\n'.join([
            'read_verilog -lib ' + json.dumps(str(library)), 'read_json ' + json.dumps(str(literal)),
            'hierarchy -check -top ' + TOP, 'clkbufmap -buf BUFG O:I',
            'iopadmap -bits -inpad IBUF O:I -outpad OBUF I:O', 'check -assert',
            'select ' + TOP, 'write_json -selected ' + json.dumps(str(physical))]) + '\n')
        run(['yosys', '-Q', '-T', '-s', io_script], 'physical_IO_export', 1200)
        actual = json.loads(physical.read_text())
        collapsed = remove_physical_buffers(actual, TOP)
        del actual
        literal_view = json.loads(literal.read_text())
        report['physical_buffer_roundtrip_identity'] = assert_circuit_identity(literal_view, collapsed)
        counts = Counter(c['type'] for c in collapsed['modules'][TOP]['cells'].values())
        assert dict(counts) == parent['cells']
        for instance in audit['retained_private_instances']:
            assert sum(c['type'] == 'DSP48E1' for n, c in collapsed['modules'][TOP]['cells'].items()
                       if n.startswith(instance + '.')) == 32
        del literal_view, collapsed
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed full preparation input'
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='PREPARED_FULL_C32K16_SHARED_PREFIX_LITERAL_PACK_INPUT_NOT_NATIVE_PACKING_OR_SIGNOFF',
            stage='complete', pack_input=str(physical), retained_cmac_dsps=512, retained_shell_dsps=3,
            retained_kernel_instances=16, physical_buffer_counts={'IBUF': 2, 'OBUF': 3, 'BUFG': 1},
            flatten_controls=6, admission_controls=9)
    except BaseException as error:
        report.update(status='FAIL_PREFIX_SHARED_PACK_INPUT', error=repr(error))
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
