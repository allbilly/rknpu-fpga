#!/usr/bin/env python3
"""Prepare exact original raw-board observations before optimization/recoding.

Reuse the source-bound original board import, not guessed mapped aliases.
This is pre-mapping verification infrastructure, not area/numerical/FPGA signoff.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from bind_mapped_board_bench import TOP, BENCH, WIDTHS, analyze
from test_fixed_array_board import verify_manifest
from test_fixed_mapped_array import circuit_signature

KERNEL = 'rk_cmac_fp16_cell_fixed'
MARKER = f'synth_xilinx -family xc7 -top {TOP} -flatten -noiopad -noclkbuf -run begin:map_dsp;'
LOWERING_WARNINGS = {
    f'Warning: Replacing memory \\temp_array with list of registers. See {ROOT}/rtl/vendor/nvdla/NV_DW02_tree.v:41, {ROOT}/rtl/vendor/nvdla/NV_DW02_tree.v:33': 'Combinational donor tree temporary array, not block RAM',
    f'Warning: Replacing memory \\input_array with list of registers. See {ROOT}/rtl/vendor/nvdla/NV_DW02_tree.v:33, {ROOT}/rtl/vendor/nvdla/NV_DW02_tree.v:28': 'Combinational donor tree input array, not block RAM',
    f'Warning: Replacing memory \\regs with list of registers. See {ROOT}/rtl/rk_cmac_profile.sv:154': 'Existing configuration register bank, not workload RAM',
}


def keep_commands():
    lines = []
    for name in sorted(WIDTHS):
        assert re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', name)
        selection = TOP + '/w:' + name
        lines += ['select -assert-count 1 ' + selection + ';',
                  'setattr -set keep 1 ' + selection + ';']
    lines.append('setattr -set fsm_encoding "none" ' + TOP + '/w:demo.state;')
    return '\n'.join(lines) + '\n'


def premap_script(original, destination):
    assert original.count(MARKER) == 1, 'Unexpected original mapping-stage boundary'
    prefix = original.split(MARKER)[0]
    commands = [line.strip() for line in prefix.splitlines() if line.strip()]
    expected = ('read_verilog -lib +/xilinx/cells_sim.v;', 'read_json ',
        'read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST ',
        'hierarchy -check -top ' + TOP + ';',
        'select -assert-mod-count 1 A:hdlname=' + KERNEL + ';',
        'select -assert-mod-count 1 A:keep_hierarchy=1;')
    assert len(commands) == len(expected)
    for command, pattern in zip(commands, expected):
        assert command == pattern if pattern.endswith(';') else command.startswith(pattern), ('Changed original import command', command)
    # proc/flatten expose the original hierarchical wires before the first
    # optimization or FSM pass. The mapped CMAC kernel retains keep_hierarchy.
    # Clean only the board shell, after keeping every observation. Do not
    # replace undriven nets with constants, disable check, or optimize the
    # imported kernel. keepdc retains don't-care/four-state expression policy.
    cleanup = f'opt_expr -keepdc {TOP};\nopt_clean {TOP};\n'
    return prefix + 'proc;\nflatten;\n' + keep_commands() + cleanup + 'check -assert;\n' + implementation_export(destination)


def implementation_export(destination):
    # Export both complete implementation modules, not the behavioral library
    # definitions loaded with read_verilog -lib. No cells are selected out,
    # removed or blackboxed. Primitive instances remain in the mapped kernel;
    # their original library is reloaded at the later mapping/simulation stage.
    # Yosys 0.65 documents write_json -selected as a module-only filter.
    return (f'select {TOP} A:hdlname={KERNEL};\n'
            'select -assert-mod-count 2 %;\n'
            'write_json -selected ' + json.dumps(str(destination)) + ';\n'
            'select -clear;\n')


def verify_implementation_boundary(design, original, kernel):
    assert set(design['modules']) == {TOP, kernel}, 'Incomplete or unexpected implementation module export'
    assert circuit_signature({'modules': {kernel: design['modules'][kernel]}}) == circuit_signature({'modules': {kernel: original['modules'][kernel]}}), 'Imported CMAC kernel changed'
    assert sum(c['type'] == kernel for c in design['modules'][TOP]['cells'].values()) == 16, 'Not all sixteen CMAC instances retained'


def classify_warnings(log):
    warnings = [line for line in log.splitlines() if re.match(r'(?i)warning:', line)]
    assert len(warnings) == len(set(warnings)), 'Repeated lowering warning'
    assert set(warnings) <= set(LOWERING_WARNINGS), ('Unclassified preparation warning', warnings)
    return {warning: LOWERING_WARNINGS[warning] for warning in warnings}


def verify_observations(module, bench):
    bindings, issues = analyze(module, bench)
    assert not issues, ('Original pre-mapping observation contract not preserved', issues)
    assert set(bindings) == set(WIDTHS)
    for name in WIDTHS:
        assert int(module['netnames'][name]['attributes']['keep'], 2) == 1, ('Missing explicit retention', name)
    assert module['netnames']['demo.state']['attributes']['fsm_encoding'] == 'none'
    return bindings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping-report', required=True, type=Path)
    args = parser.parse_args()
    parent_path = args.mapping_report.resolve()
    assert parent_path.is_relative_to(ROOT)
    parent = json.loads(parent_path.read_text())
    assert parent['status'] == 'PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY'
    assert (parent['channels'], parent['kernels'], parent['parallel_products']) == (32, 16, 512)
    assert all(c['status'] == 'PASS' and c['returncode'] == 0 for c in parent['commands'])
    verify_manifest(parent['source'])
    mapping_script, imported_partition = [parent_path.parent / name for name in ('mapping.ys', 'cmac_partition.json')]
    for path in (mapping_script, imported_partition):
        expected = parent['artifacts']['files'].get(str(path.relative_to(ROOT)), parent['source']['files'].get(str(path.relative_to(ROOT))))
        assert expected and fingerprint([path])['files'][str(path.relative_to(ROOT))] == expected
    tracked = [parent_path, mapping_script, imported_partition, BENCH, Path(__file__).resolve(),
               *(ROOT / name for name in parent['source']['files'])]
    tracked.extend(Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
    out = ROOT / f'build/rknpu-observable-board-premap/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    netlist, script = out / 'observable_premap.json', out / 'prepare.ys'
    script.write_text(premap_script(mapping_script.read_text(), netlist))
    tracked.append(script)
    report = dict(status='RUNNING', stage='prepare', source=fingerprint(tracked), started_utc=timestamp(),
        supervisor_pid=os.getpid(), parent_report=str(parent_path.relative_to(ROOT)),
        parent_source_sha256=parent['source']['sha256'], commands=[], channels=32, kernels=16, parallel_products=512,
        numerical_netlist_acceptance=False, physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Original source-bound board import, proc/flatten and explicit keep on all 22 exact bench signals plus fsm_encoding=none on the native four-bit state. Live-wire/width/force-point and unchanged imported-kernel checks. No FPGA RTL edit, guessed aliases, expected-code substitution, arithmetic/layout fallback, optimized mapping, numerical/fault/reset execution, packed fit, timing/DRC or bitstream acceptance.')

    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    save()
    try:
        # Snapshot before executing so a failed attempt retains its exact
        # pre-run tool and source bytes, not a later correction.
        for path in set(tracked):
            if path.suffix == '.json' and path.stat().st_size > 1024 * 1024: continue
            dest = out / 'snapshot' / path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(path.read_bytes())
        for label, argv in [('version', ['yosys', '-V']), ('prepare', ['yosys', '-Q', '-T', '-s', str(script)])]:
            log_path = out / (label + '.log')
            step = dict(argv=argv, status='RUNNING', log=str(log_path.relative_to(ROOT)))
            report['commands'].append(step); save(); started = time.monotonic()
            try:
                with log_path.open('w') as stream:
                    with subprocess.Popen(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                        step['pid'] = proc.pid; save()
                        try: code = proc.wait(timeout=14400)
                        except BaseException:
                            try: os.killpg(proc.pid, signal.SIGKILL)
                            except ProcessLookupError: pass
                            proc.wait(); raise
                step['returncode'] = code
                log = log_path.read_text()
                assert code == 0 and not re.search(r'(?im)\berror:', log), log[-4000:]
                if label == 'prepare': report['classified_source_lowering_warnings'] = classify_warnings(log)
                else: assert not re.search(r'(?im)\bwarning:', log), log
                if label == 'version':
                    report['tool_version'] = log.strip()
                    assert report['tool_version'] == parent['tool_version']
                step['status'] = 'PASS'
            except BaseException:
                step['status'] = 'FAIL'; raise
            finally:
                step['seconds'] = round(time.monotonic() - started, 3); save()
        design = json.loads(netlist.read_text())
        report['bindings'] = verify_observations(design['modules'][TOP], BENCH.read_text())
        original = json.loads(imported_partition.read_text())
        kernel = parent['preserved_kernel']
        verify_implementation_boundary(design, original, kernel)
        report['imported_kernel_circuit_identity'] = 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
        assert fingerprint(tracked) == report['source'], 'Preparation inputs changed'
        report.update(status='PREPARED_ORIGINAL_RAW_BOARD_OBSERVABILITY_ONLY', stage='complete',
            artifacts=fingerprint([script, netlist, *(ROOT / c['log'] for c in report['commands'])]))
    except BaseException as exc:
        report.update(status='FAIL', reason=str(exc) or repr(exc)); raise
    finally:
        report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
    print(report['status'], len(report['bindings']), 'exact original observations')


if __name__ == '__main__': main()
