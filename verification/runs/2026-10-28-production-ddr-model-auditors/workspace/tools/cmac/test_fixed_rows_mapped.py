#!/usr/bin/env python3
"""Replay the unchanged FP16 row corpus against its actual XC7 helper netlist.

This is an isolated helper gate, never full-array or physical FPGA signoff.
The reference remains original NVIDIA RTL. Vendor functional primitive models
and their default startup are preserved; no timing backannotation is claimed.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from xc7_primitive_counts import primitive_counts


def verify(manifest):
    paths = [(ROOT / name).resolve() for name in manifest['files']]
    assert all(path.is_relative_to(ROOT) for path in paths), 'External manifest member'
    assert fingerprint(paths) == manifest, 'Source/artifact manifest differs'


def validate_parents(area, rows):
    assert area['status'] == 'PASS_FIXED_FP16_ROW_AREA_ONLY', area['status']
    assert rows['status'] == 'PASS_FIXED_FP16_ROWS_EXPERIMENT_ONLY', rows['status']
    assert rows['formal_result'] == 'PASS_COMPOSED_POST_CONFIGURATION_ROWS_AND_ACTIVE_COMPARE'
    assert rows['seed'] == '3588f016'
    assert rows['simulation_result'] == (
        'PASS fixed FP16 rows comparisons=2097152 resets=4 seed=3588f016; post-configuration only')
    for parent in (area, rows):
        for step in parent['commands']:
            assert step['status'] == 'PASS' and step['returncode'] == 0, step
        verify(parent['source'])
        verify(parent['artifacts'])
    proofs = {step['log'].rsplit('/', 1)[-1] for step in rows['commands']}
    assert {'formal_control.log', 'formal_datapath.log'} <= proofs
    fixed = area['results']['fixed']
    assert fixed['booth_instances'] == 8 and fixed['ff_count'] == fixed['dsp_count'] == 0
    assert fixed['lut_count'] > 0


def mapped_bench(text):
    changes = (
        ('module tb_cmac_fp16_rows;', 'module tb_cmac_fp16_rows_mapped;'),
        ('    rk_cmac_fp16_rows dut(.*);', '    fp16_rows_area_top dut(.*);'),
        ('    logic clk, rst_n=0, pair_nz=0;', '    logic clk, rst_n=0, pair_nz;'),
        ('    logic [15:0] op_a=0,op_b=0;', '    logic [15:0] op_a,op_b;'),
        ('    logic [3:0] exp_sft=0;', '    logic [3:0] exp_sft;'),
        ('    initial begin\n        configure();',
         '    initial begin\n'
         '        #1; // Drive after vendor primitive INIT_REG initialization.\n'
         '        pair_nz=0;op_a=0;op_b=0;exp_sft=0;\n'
         '        #200; // Preserve default vendor GSR through 100 ns.\n'
         '        configure();'),
        ('PASS fixed FP16 rows comparisons=', 'PASS mapped fixed FP16 rows comparisons='),
    )
    for old, new in changes:
        assert text.count(old) == 1, ('Unexpected source bench', old)
        text = text.replace(old, new)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--area-report', type=Path, required=True)
    parser.add_argument('--rows-report', type=Path, required=True)
    args = parser.parse_args()
    ap, rp = args.area_report.resolve(), args.rows_report.resolve()
    assert ap.is_relative_to(ROOT) and rp.is_relative_to(ROOT)
    area, rows = json.loads(ap.read_text()), json.loads(rp.read_text())
    validate_parents(area, rows)
    netlist, mapped_json = ap.parent / 'fixed_mapped.v', ap.parent / 'fixed_mapped.json'
    for path in (netlist, mapped_json):
        assert str(path.relative_to(ROOT)) in area['artifacts']['files']
    cells = dict(primitive_counts(json.loads(mapped_json.read_text())['modules'], 'fp16_rows_area_top'))
    assert cells == area['results']['fixed']['cells'], 'Mapped helper primitives differ'
    source_bench = ROOT / 'tests/cmac/tb_cmac_fp16_rows.sv'
    assert str(source_bench.relative_to(ROOT)) in rows['source']['files']
    generated = mapped_bench(source_bench.read_text())
    out = ROOT / f'build/rknpu-fixed-fp16-rows/mapped-iverilog-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    bench = out / 'tb_cmac_fp16_rows_mapped.sv'
    bench.write_text(generated)
    snapshots = []
    for label, parent in (('area', area), ('rows', rows)):
        path = out / f'{label}_report_snapshot.json'
        path.write_text(json.dumps(parent, indent=2) + '\n')
        snapshots.append(path)
    donor = ROOT / 'rtl/vendor/nvdla'
    reference = [donor / name for name in (
        'compat/nv_assert_never.v', 'compat/nv_assert_no_x.v', 'NV_DW02_tree.v',
        'NV_NVDLA_CMAC_CORE_MAC_mul.v')]
    headers = [donor / name for name in (
        'assertion_header.h', 'assertion_task.h', 'nv_assert_never.vlib', 'nv_assert_no_x.vlib', 'LICENSE')]
    models_root = ROOT / 'tests/vendor/xilinx-unisim'
    models = list(models_root.rglob('*.v')) + [models_root / 'LICENSE', models_root / 'README.md']
    tracked = reference + headers + snapshots + [ap, rp, netlist, mapped_json, source_bench, bench,
        Path(__file__).resolve(), ROOT / 'tools/cmac/xc7_primitive_counts.py', ROOT / 'tools/evidence.py']
    report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked),
                  primitive_models=fingerprint(models), area=area, native_rows=rows, commands=[],
                  seed='3588f016', expected_comparisons=2097152, expected_resets=4, cells=cells,
                  bench_changes='Only module name, mapped DUT instance, external input initialization at 1 ns (after primitive INIT_REG initialization), 200 ns startup wait and PASS marker. All operand sweeps, row/tag case-inequality, coverage counts and reset/setup calls unchanged.',
                  scope='Single mapped fixed-FP16 partial-row helper versus original NVIDIA RTL, four-state functional primitive models with default GSR. Not full C32/K16 numerical mapping, routed timing/SDF, fit, DRC, bitstream, physical FPGA or RK evidence.')
    for path in tracked + models:
        target = out / 'snapshot' / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, name):
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / f'{name}.log').relative_to(ROOT)))
        report['commands'].append(step)
        save()
        started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                      start_new_session=True) as proc:
                    try:
                        code = proc.wait(timeout=14400)
                    except BaseException:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        proc.wait()
                        raise
            step['returncode'] = code
            log = (ROOT / step['log']).read_text()
            assert code == 0, log[-6000:]
            if name in ('compile', 'test'):
                assert not any(token in log.lower() for token in ('warning', 'sorry:', 'error:', 'error :', 'fatal:')), log[-6000:]
            step['status'] = 'PASS'
            return log
        except Exception:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3)
            save()

    save()
    try:
        report['tool_version'] = run(['iverilog', '-V'], 'version').splitlines()[0]
        report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
        binary = out / 'sim.vvp'
        run(['iverilog', '-g2012', '-Ttyp', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}',
             '-s', bench.stem, '-s', 'glbl', '-y', models_root / 'verilog/src/unisims',
             '-o', binary, models_root / 'verilog/src/glbl.v', *reference, netlist, bench], 'compile')
        log = run(['vvp', binary], 'test')
        expected = 'PASS mapped fixed FP16 rows comparisons=2097152 resets=4 seed=3588f016; post-configuration only'
        assert [line for line in log.splitlines() if line.startswith('PASS ')] == [expected], log[-4000:]
        assert fingerprint(tracked) == report['source']
        verify(report['primitive_models'])
        validate_parents(area, rows)
        report.update(status='PASS_FIXED_FP16_ROWS_MAPPED_FUNCTIONAL_ONLY', result=expected,
                      artifacts=fingerprint([binary] + [ROOT / step['log'] for step in report['commands']]))
    except Exception as exc:
        report.update(status='FAIL', reason=str(exc))
        raise
    finally:
        report['finished_utc'] = timestamp()
        save()
        print(out / 'report.json')
    print(report['status'], report['result'])


if __name__ == '__main__':
    main()
