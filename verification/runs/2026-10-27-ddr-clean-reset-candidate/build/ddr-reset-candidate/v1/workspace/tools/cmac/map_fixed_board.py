#!/usr/bin/env python3
"""Map the complete raw C32/K16 board around its verified XC7 CMAC partition.

No arithmetic blackbox or serialized substitute is used. The actual mapped
kernel is kept hierarchical to avoid repeating its expensive ABC pass. This
is a partitioned whole-board area experiment, not numerical netlist or FPGA
fit/timing/electrical signoff. The full four-state Vivado gate is unchanged.
"""
import argparse
from collections import Counter
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
from test_fixed_array_board import (ARRAY, CELL, JOIN, ROWS, ROW_FORMAL,
    completed_commands, fixed_join, simulation_sources, validate_result,
    verify_fixed_native, verify_manifest)
from vivado_array import inputs
from xc7_primitive_counts import PRIMITIVE, TIMING, primitive_counts

CMAC = 'rk_cmac_fp16_array_fixed'
KERNEL = 'rk_cmac_fp16_cell_fixed'
MAPPED_CMAC = CMAC + '_xc7'


def verify_area(report):
    assert report['status'] == 'PASS_FIXED_CMAC_XC7_AREA_EXPERIMENT_ONLY', 'Completed full fixed CMAC mapping required'
    assert (report['channels'], report['kernels'], report['instantiated_helpers'],
            report['mapped_kernel_instances']) == (32, 16, 512, 16)
    assert report['numerical_acceptance'] is False and report['physical_fit_verified'] is False
    completed_commands(report, ('version', 'help', 'mapping'))
    verify_manifest(report['source']); verify_manifest(report['artifacts'])
    assert all(name in report['source']['files'] for name in (ROWS, CELL, ARRAY))


def verify_board(report, native):
    two = report['status'] == 'PASS_FIXED_RAW_ARRAY_BOARD_TWO_STATE_HIERARCHICAL_EXPERIMENT_ONLY'
    four = report['status'] == 'PASS_FIXED_RAW_ARRAY_BOARD_FOUR_STATE_RTL_EXPERIMENT_ONLY'
    assert two or four, 'Completed fixed-board integration required, not baseline or RUNNING'
    assert report['suite'] == ('fixed-verilator' if two else 'fixed-iverilog')
    assert (report['channels'], report['kernels'], report['parallel_products']) == (32, 16, 512)
    assert report['row_formal_status_at_start'] == ROW_FORMAL
    expected_modes = set(range(9)) - ({7} if two else set())
    assert len(report['tests']) == len(expected_modes)
    assert {test['mode'] for test in report['tests']} == expected_modes
    for test in report['tests']:
        assert test['status'] == 'PASS'
        validate_result(test['result'], test['mode'])
    completed_commands(report, ('rom_check', 'version', 'compile', *('mode'+str(mode) for mode in sorted(expected_modes))))
    verify_manifest(report['source']); verify_manifest(report['artifacts'])
    snapshots = [ROOT / name for name in report['source']['files'] if name.endswith('/fixed_report_snapshot.json')]
    assert len(snapshots) == 1 and json.loads(snapshots[0].read_text()) == native
    joins = [ROOT / name for name in report['simulation_sources'] if Path(name).name == Path(JOIN).name]
    assert len(joins) == 1 and joins[0] != ROOT / JOIN
    assert joins[0].read_text() == fixed_join((ROOT / JOIN).read_text())
    spec, _ = inputs()
    assert report['simulation_sources'] == [str(path.relative_to(ROOT)) for path in simulation_sources(spec, joins[0])]


def partition(design):
    modules = design['modules']
    array = modules[CMAC]
    defaults = array['parameter_default_values']
    assert {key: int(defaults[key], 2) for key in ('ATOMIC_C', 'ATOMIC_K', 'TAG_WIDTH')} == {
        'ATOMIC_C': 32, 'ATOMIC_K': 16, 'TAG_WIDTH': 35}
    kinds = [cell['type'] for cell in array['cells'].values() if KERNEL in cell['type']]
    assert len(kinds) == 16 and len(set(kinds)) == 1, 'Actual sixteen-kernel partition required'
    kind = kinds[0]
    assert modules[kind]['attributes']['hdlname'] == KERNEL
    assert int(modules[kind]['attributes']['keep_hierarchy'], 2) == 1
    # Only library definitions are omitted. Both implementation modules are
    # copied exactly, including their ports, parameters, cells and wiring.
    value = dict(design, modules={name: modules[name] for name in (CMAC, kind)})
    return value, kind, primitive_counts(modules, kind)


def parameter_binding(design, source):
    """read_json drops parameter interfaces; retain explicit caller checks.

    Only the imported array module key is aliased. Its entire body and the
    mapped kernel are untouched. The matching SV port wrapper contributes
    wiring only and rejects any parameter geometry other than this partition.
    """
    assert set(design['modules']) == {CMAC} | {
        name for name in design['modules'] if KERNEL in name}
    renamed = dict(design, modules={
        MAPPED_CMAC if name == CMAC else name: body
        for name, body in design['modules'].items()})
    marker = '    wire [ATOMIC_K*44-1:0] groups;'
    assert source.count(marker) == 1, 'Unexpected fixed array declaration'
    header = source.split(marker)[0]
    assert header.count('module '+CMAC+' #(') == 1
    assert header.rstrip().endswith(');')
    shim = header.replace('output logic', 'output wire')
    shim += ('    initial if(ATOMIC_C!=32 || ATOMIC_K!=16 || TAG_WIDTH!=35)\n'
             '        $fatal(1,"XC7 partition requires C32 K16 TAG35");\n'
             f'    {MAPPED_CMAC} actual_partition(.*);\n'
             'endmodule\n')
    return renamed, shim


def count_shell(modules, top, kernel):
    counts = Counter()
    for cell in modules[top]['cells'].values():
        kind = cell['type']
        if kind in (kernel, '$scopeinfo'):
            continue
        assert PRIMITIVE.fullmatch(kind) or kind in ('RAMB18E1', 'RAMB36E1'), ('Unknown board hardware cell', kind)
        definition = modules[kind]
        assert int(definition.get('attributes', {}).get('blackbox', '0'), 2) == 1, kind
        assert {item['type'] for item in definition.get('cells', {}).values()} <= TIMING, kind
        counts[kind] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--area-report', type=Path, required=True)
    parser.add_argument('--fixed-report', type=Path, required=True)
    parser.add_argument('--board-report', type=Path, required=True)
    args = parser.parse_args()
    ap, np, bp = [path.resolve() for path in (args.area_report, args.fixed_report, args.board_report)]
    assert all(path.is_relative_to(ROOT) for path in (ap, np, bp))
    area, board = json.loads(ap.read_text()), json.loads(bp.read_text())
    verify_area(area)
    native = verify_fixed_native(np)
    verify_board(board, native)
    part_path = ap.parent / 'mapped_hierarchy.json'
    assert str(part_path.relative_to(ROOT)) in area['artifacts']['files']
    raw_part = json.loads(part_path.read_text())
    frozen, kernel, kernel_counts = partition(raw_part)
    frozen, shim_text = parameter_binding(frozen, (ROOT / ARRAY).read_text())
    spec, tracked = inputs()
    out = ROOT / f'build/rknpu-fixed-board-area/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    join = out / Path(JOIN).name
    join.write_text(fixed_join((ROOT / JOIN).read_text()))
    all_sources = simulation_sources(dict(spec, simulation_helpers=[]), join)
    sources = [path for path in all_sources if str(path.relative_to(ROOT)) not in (ROWS, CELL, ARRAY)]
    partition_path = out / 'cmac_partition.json'
    partition_path.write_text(json.dumps(frozen) + '\n')
    shim = out / 'mapped_cmac_parameter_binding.sv'
    shim.write_text(shim_text)
    sources.append(shim)
    snapshots = []
    for label, parent in (('area', area), ('native', native), ('board', board)):
        path = out / f'{label}_report_snapshot.json'
        path.write_text(json.dumps(parent, indent=2) + '\n'); snapshots.append(path)
    tracked += all_sources + snapshots + [ap, np, bp, part_path, partition_path, shim,
        Path(__file__).resolve(), ROOT / 'tools/cmac/test_fixed_array_board.py',
        ROOT / 'tools/cmac/xc7_primitive_counts.py']
    report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), commands=[],
                  area=area, native=native, board=board, channels=32, kernels=16, parallel_products=512,
                  intended_part=spec['part'], intended_clock_period_ns=spec['clock_period_ns'],
                  preserved_kernel=kernel, numerical_netlist_acceptance=False, physical_fit_verified=False,
                  parameter_binding='Imported array module key aliased; its body/kernel untouched. Original SV port declaration with a wire-only delegate and explicit C32/K16/TAG35 rejection guard, because read_json drops parameter interfaces.',
                  bitstream_emitted=False, hardware_programmed=False,
                  scope='Complete raw K65 BRAM-board partitioned XC7 area experiment. Exact previously mapped C32 kernel reused sixteen times; all CACC/output/DMA/decoder/ROM/RAM/reset/LED logic mapped from unchanged RTL. Hierarchy preservation limits cross-boundary optimization. No routed timing, pin/electrical/DRC, numerical netlist, bitstream, FPGA or RK acceptance.')
    for path in set(tracked):
        target = out / 'snapshot' / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes())

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, name):
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name+'.log')).relative_to(ROOT)))
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                      start_new_session=True) as proc:
                    try:
                        code = proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            log = (ROOT / step['log']).read_text(); step['returncode'] = code
            assert code == 0 and 'ERROR:' not in log, log[-6000:]
            step['status'] = 'PASS'; return log
        except Exception:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic()-started, 3); save()

    save()
    try:
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        assert report['tool_version'] == area['tool_version'], 'Different CMAC/tool mapping provenance'
        run([sys.executable, ROOT / 'tools/cmac/gen_array_board.py', '--check'], 'rom_check')
        help_text = run(['yosys', '-Q', '-T', '-p', 'help synth_xilinx'], 'help')
        coarse = re.search(r'\n    coarse:\n(.*?)\n    map_memory:', help_text, re.S)
        assert coarse
        commands = [line.strip() for line in coarse.group(1).splitlines() if line.strip()]
        assert commands == ['techmap -map +/cmp2lut.v -map +/cmp2lcu.v -D LUT_WIDTH=[46]',
                            'alumacc', 'share', 'opt', 'memory -nomap', 'opt_clean']
        unshared = [line.replace('LUT_WIDTH=[46]', 'LUT_WIDTH=6') for line in commands if line != 'share']
        report.update(original_coarse_stage=commands, executed_coarse_stage=unshared)
        mapped_json, mapped_v, script = [out / name for name in ('mapped_hierarchy.json', 'mapped.v', 'mapping.ys')]
        top = spec['top']
        text = 'read_verilog -lib +/xilinx/cells_sim.v; read_json ' + json.dumps(str(partition_path))
        text += '; read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST '
        text += ' '.join('-I'+json.dumps(str(ROOT / name)) for name in spec['include_dirs'])
        text += ' ' + ' '.join(json.dumps(str(path)) for path in sources)
        text += f'; hierarchy -check -top {top}; select -assert-mod-count 1 A:hdlname={KERNEL}'
        text += '; select -assert-mod-count 1 A:keep_hierarchy=1'
        flags = f'-family xc7 -top {top} -flatten -noiopad -noclkbuf'
        text += f'; synth_xilinx {flags} -run begin:map_dsp; ' + '; '.join(unshared)
        text += f'; synth_xilinx {flags} -run map_memory:; check -assert; write_json {json.dumps(str(mapped_json))}'
        text += f'; write_verilog -noattr {json.dumps(str(mapped_v))}'
        script.write_text(text.replace('; ', ';\n') + '\n')
        log = run(['yosys', '-Q', '-T', '-s', script], 'mapping')
        assert 'Executing SHARE pass' not in log
        modules = json.loads(mapped_json.read_text())['modules']
        kinds = [cell['type'] for cell in modules[top]['cells'].values() if KERNEL in cell['type']]
        assert kinds == [kernel]*16, 'Mapped board lost/replaced parallel CMAC kernels'
        assert primitive_counts(modules, kernel) == kernel_counts, 'Reused actual kernel primitives changed'
        shell = count_shell(modules, top, kernel)
        counts = Counter(shell)
        for _ in range(16): counts.update(kernel_counts)
        assert shell['RAMB18E1'] + shell['RAMB36E1'] > 0, 'BRAM inference required'
        for name, direction, width in (('SYS_CLK', 'input', 1), ('SYS_RSTN', 'input', 1),
                                       ('led_3bits_tri_o', 'output', 3)):
            port = modules[top]['ports'][name]
            assert port['direction'] == direction and len(port['bits']) == width
            assert all(isinstance(bit, int) for bit in port['bits']), 'Board I/O became constant'
        estimates = re.findall(r'Estimated number of LCs:\s+(\d+)', log)
        assert estimates
        assert fingerprint(tracked) == report['source']
        verify_area(area); verify_fixed_native(np); verify_board(board, native)
        report.update(status='PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY', mapped_kernel_instances=16,
                      cells=dict(counts), shell_cells=dict(shell), reused_kernel_cells=dict(kernel_counts),
                      lut_count=sum(n for kind, n in counts.items() if kind.startswith('LUT')),
                      ff_count=sum(n for kind, n in counts.items() if kind.startswith('FD')),
                      dsp_count=counts['DSP48E1'], estimated_logic_cells=int(estimates[-1]),
                      artifacts=fingerprint([script, mapped_json, mapped_v] + [ROOT / step['log'] for step in report['commands']]))
    except Exception as exc:
        report.update(status='FAIL', reason=str(exc)); raise
    finally:
        report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
    print(report['status'], report['cells'])


if __name__ == '__main__':
    main()
