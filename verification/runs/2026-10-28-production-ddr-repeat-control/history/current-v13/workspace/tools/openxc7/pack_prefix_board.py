#!/usr/bin/env python3
"""Characterize full C32/K16 native packing only; never place/route or emit bits.

Missing DSP timing and -2 corner models remain explicit signoff gaps. Packing
is allowed to measure resources, not to bypass those final physical gates.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]),
                str(Path(__file__).resolve().parent)]
from evidence import ROOT, timestamp
from prepare_prefix_pack_input import TOP, EXPECTED_PORTS, digest
from run_openxc7 import normalized_xdc
from audit_himbaechel_timing import audit

QUALIFICATION = Path('/home/fedora/soDLA/build/ypcb/lut-pair-engine-1791377260734986151/qualification.json')
DATABASE = Path('/home/fedora/tiny-gpu/build/ypcb/nextpnr-build/share/himbaechel/xilinx/chipdb-xc7k480t.bin')
CONSTIDS = Path('/home/fedora/tiny-gpu/build/ypcb/nextpnr-himbaechel/himbaechel/uarch/xilinx/constids.inc')
JSON_WRITER = Path('/home/fedora/tiny-gpu/build/ypcb/nextpnr-himbaechel/json/jsonwrite.cc')
PREPARED = 'PREPARED_FULL_C32K16_LITERAL_PACK_INPUT_NOT_NATIVE_PACKING_OR_SIGNOFF'


def native_export_module(design, version):
    """Admit the pinned writer's explicit label contract, never guess a top.

    json/jsonwrite.cc::write_module uses ctx.attrs['module'], otherwise the
    literal 'top'; --top selects the input and does not set that attribute.
    Its group_ports restores vector names/widths. Record the context label
    separately from the logical input top, without changing any graph data.
    """
    creators = re.findall(r'Next Generation Place and Route \(Version [^)]+\)', version)
    assert len(creators) == 1 and design['creator'] == creators[0], 'Native producer/version mismatch'
    assert len(design['modules']) == 1, 'Unexpected native export modules'
    label, module = next(iter(design['modules'].items()))
    attributes = module.get('attributes', {})
    if 'module' in attributes:
        assert attributes['module'] == TOP, 'Unexpected explicit context module'
        expected_label = TOP
    else:
        expected_label = 'top'
    assert label == expected_label, 'Native writer module-label mismatch'
    assert {p: (spec['direction'], len(spec['bits']))
            for p, spec in module['ports'].items()} == EXPECTED_PORTS, 'Changed native board port contract'
    bits = []
    for spec in module['ports'].values():
        assert spec.get('offset', 0) == 0, 'Changed native port offset'
        assert all(type(bit) is int and bit >= 2 for bit in spec['bits']), 'Invalid native port endpoint'
        bits.extend(spec['bits'])
    assert len(set(bits)) == 5, 'Merged native external ports'
    return module, dict(logical_input_top=TOP, emitted_context_label=label,
        module_attribute_present='module' in attributes,
        contract='PINNED_JSON_WRITER_CONTEXT_MODULE_ATTRIBUTE_OR_LITERAL_TOP_AND_GROUPED_PORTS',
        producer=creators[0], graph_data_changed=False)


def packing_xdc(source):
    """Strict original-profile whitelist, with every translation reported.

    This backend rejects -name under Werror although it applies the exact
    port period. Omit that metadata-only clock label, not its port or period.
    The two external exceptions are NOT implemented: this run has no timing
    acceptance and must not be reused as a signoff constraint profile.
    """
    text, unapplied = normalized_xdc(source)
    original = 'create_clock -name sys_clk -period 20.000 [get_ports SYS_CLK]'
    assert text.count(original) == 1
    text = text.replace(original, 'create_clock -period 20.000 [get_ports SYS_CLK]')
    return text, dict(unapplied_external_timing_exceptions=unapplied,
                     metadata_clock_label='sys_clk', target_port='SYS_CLK',
                     target_period_ns=20.0, signoff_constraint_profile=False)


def verify_prepared_metadata(report):
    assert report['status'] == PREPARED and report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'],
            report['retained_cmac_dsps'], report['intended_part'], report['intended_clock_period_ns']) == (
                32, 16, 512, 512, 'xc7k480tffg1156-2', 20)
    assert len(report['retained_kernel_instances']) == len(set(report['retained_kernel_instances'])) == 16
    assert report['primitive_counts']['DSP48E1'] == 515 and report['primitive_counts']['RAMB36E1'] == 6
    assert report['physical_buffer_counts'] == {'IBUF': 2, 'OBUF': 3, 'BUFG': 1}
    assert report['mapping_to_export_identity'] and report['physical_buffer_roundtrip_identity']
    assert report['circuit_identity'] == 'ALL_PRIMITIVE_PARAMETERS_PORT_BITS_AND_PIN_WIRE_INCIDENCE_AFTER_BUFFER_REMOVAL'
    assert report['original_parent_status'] == 'FAIL' and report['full_board_numerical_acceptance_inherited'] is False
    for key in ('native_packing_executed', 'numerical_netlist_acceptance', 'physical_fit_verified',
                'timing_signoff', 'electrical_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[key] is False
    assert [Path(step['log']).stem for step in report['commands']] == ['datadir', 'version', 'physical_io']
    assert all(step['status'] == 'PASS_TOOL_EXECUTION_ONLY' and step['returncode'] == 0
               for step in report['commands'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    args = parser.parse_args()
    prepared_path = (ROOT / args.prepared).resolve(strict=True)
    assert prepared_path.is_relative_to(ROOT / 'build/openxc7')
    out = ROOT / f'build/openxc7/full-prefix-native-pack-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__), out / 'executed_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(),
        supervisor_pid=os.getpid(), commands=[], channels=32, kernels=16, parallel_products=512,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588,
        native_packing_executed=False, native_placement_executed=False, native_routing_executed=False,
        numerical_netlist_acceptance=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, bitstream_emitted=False, hardware_programmed=False, scope=__doc__)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(argv, label, timeout=7200):
        log = out / (label + '.log')
        step = dict(argv=list(map(str, argv)), cwd=str(ROOT), log=str(log.relative_to(ROOT)),
                    timeout_seconds=timeout, status='RUNNING')
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with log.open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                step['pid'] = proc.pid
                save()
                try:
                    code = proc.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = log.read_text()
            assert code == 0, text[-2000:]
            assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text), text[-2000:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        prepared = json.loads(prepared_path.read_text())
        verify_prepared_metadata(prepared)
        before = dict(prepared['source'])
        for name, sha in prepared['artifacts'].items():
            path = (ROOT / name).resolve(strict=True)
            assert path.is_relative_to(prepared_path.parent)
            before[str(path)] = sha
        for name, sha in before.items():
            assert digest(name) == sha, 'Changed preparation input: ' + name
        inventory = audit(QUALIFICATION, DATABASE, CONSTIDS)
        report['timing_inventory'] = inventory
        candidate = json.loads(QUALIFICATION.read_text())
        executable = Path(candidate['executable']['path'])
        assert str(JSON_WRITER) in candidate['inputs'], 'Unbound native JSON writer contract'
        before.update(candidate['inputs'])
        before.update({str(p.resolve()): digest(p) for p in (prepared_path, QUALIFICATION, Path(__file__))})
        for module in list(sys.modules.values()):
            if getattr(module, '__file__', None):
                path = Path(module.__file__).resolve()
                if path.is_relative_to(ROOT / 'tools'):
                    before[str(path)] = digest(path)
        xdc = ROOT / 'fpga/ypcb.xdc'
        before[str(xdc)] = digest(xdc)
        text, translation = packing_xdc(xdc.read_text())
        constraints = out / 'ypcb.pack-only.literal.xdc'
        constraints.write_text(text)
        report.update(source=before, constraint_translation=translation,
                      prepared_report=str(prepared_path.relative_to(ROOT)),
                      native_version=run([executable, '--version'], 'version', 60).strip())
        help_text = run([executable, '--help'], 'help', 60)
        assert '--pack-only' in help_text and '--Werror' in help_text
        input_path = (ROOT / prepared['pack_input']).resolve(strict=True)
        assert input_path.is_relative_to(prepared_path.parent) and str(input_path) in before
        output = out / 'packed.json'
        report.update(stage='native_pack', native_packing_executed=True)
        run([executable, '--chipdb', DATABASE, '--device', report['intended_part'],
             '--top', TOP, '--json', input_path, '-o', 'xdc=' + str(constraints),
             '--pack-only', '--freq', '50', '--seed', '3588', '--Werror', '--verbose',
             '--write', output], 'native_pack')
        design = json.loads(output.read_text())
        module, translation = native_export_module(design, report['native_version'])
        translation.update(writer_source=str(JSON_WRITER), writer_source_sha256=before[str(JSON_WRITER)])
        report['native_export_top_translation'] = translation
        cells = module['cells']
        counts = Counter(cell['type'] for cell in cells.values())
        assert counts['DSP48E1_DSP48E1'] == 515, 'DSP resources changed during packing'
        per_kernel = {name: sum(cell['type'] == 'DSP48E1_DSP48E1' for key, cell in cells.items()
                              if key.startswith(name + '.')) for name in prepared['retained_kernel_instances']}
        assert len(per_kernel) == 16 and set(per_kernel.values()) == {32}
        del design, cells
        assert all(digest(name) == sha for name, sha in before.items()), 'Changed native packing input'
        report.update(status='PACKED_FULL_C32K16_NATIVE_RESOURCE_CHARACTERIZATION_NOT_PLACED_FIT_OR_SIGNOFF',
            stage='complete', native_packed_cell_counts=dict(counts), retained_kernel_dsps=per_kernel,
            retained_cmac_dsps=512, retained_shell_dsps=3, packed_design=str(output.relative_to(ROOT)))
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.iterdir()
                               if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
