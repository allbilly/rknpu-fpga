#!/usr/bin/env python3
"""Check actual XC7 partition import and parameter rejection in real Yosys.

Uses the preserved mapped arithmetic, not a dummy implementation. This checks
only the import boundary, never numerical equivalence or physical acceptance.
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
from map_fixed_board import CMAC, KERNEL, parameter_binding, partition, verify_area
from test_fixed_array_board import ARRAY, verify_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping-report', type=Path, required=True)
    args = parser.parse_args()
    parent = args.mapping_report.resolve()
    assert parent.is_relative_to(ROOT)
    report = json.loads(parent.read_text())
    assert report['status'] in ('RUNNING', 'PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY')
    assert (report['channels'], report['kernels'], report['parallel_products']) == (32, 16, 512)
    verify_manifest(report['source'])
    verify_area(report['area'])
    actual = parent.parent / 'cmac_partition.json'
    shim = parent.parent / 'mapped_cmac_parameter_binding.sv'
    source = [ROOT / name for name in report['area']['artifacts']['files']
              if Path(name).name == 'mapped_hierarchy.json']
    assert len(source) == 1
    frozen, _, _ = partition(json.loads(source[0].read_text()))
    expected, expected_shim = parameter_binding(frozen, (ROOT / ARRAY).read_text())
    assert json.loads(actual.read_text()) == expected
    assert shim.read_text() == expected_shim
    out = ROOT / f'build/rknpu-fixed-partition-binding/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    snapshot = out / 'mapping_report_snapshot.json'
    snapshot.write_text(json.dumps(report, indent=2) + '\n')
    tracked = [actual, shim, source[0], snapshot, Path(__file__).resolve(),
               ROOT / ARRAY, ROOT / 'tools/cmac/map_fixed_board.py',
               ROOT / 'tools/cmac/test_fixed_array_board.py', ROOT / 'tools/evidence.py']
    result = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked),
                  commands=[], numerical_acceptance=False, physical_fit_verified=False,
                  scope='Real Yosys import of the actual C32/K16/TAG35 mapped partition, '
                        'plus wrong-C, wrong-K and wrong-tag parameter rejection. '
                        'Not numerical simulation, full-board mapping, FPGA timing/DRC or a bitstream.')

    def save():
        (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')

    def run(argv, name, reject=False):
        step = dict(argv=list(map(str, argv)), status='RUNNING',
                    log=str((out / (name+'.log')).relative_to(ROOT)),
                    expected='nonzero $fatal parameter rejection' if reject else 'exit zero without ERROR')
        result['commands'].append(step); save()
        started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream,
                                      stderr=subprocess.STDOUT, start_new_session=True) as proc:
                    try:
                        code = proc.wait(timeout=600)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            log = (ROOT / step['log']).read_text()
            step['returncode'] = code
            if reject:
                errors = [line for line in log.splitlines() if 'ERROR:' in line]
                assert code != 0 and len(errors) == 1 and 'resolve task name' in errors[0] and '$fatal' in errors[0], log[-3000:]
                step['observed_rejection'] = errors[0]
            else:
                assert code == 0 and 'ERROR:' not in log, log[-3000:]
            step['status'] = 'PASS'
            return log
        except Exception:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic()-started, 3); save()

    save()
    try:
        result['tool_version'] = run(['yosys', '-V'], 'version').strip()
        assert result['tool_version'] == report['area']['tool_version']
        base = 'read_verilog -lib +/xilinx/cells_sim.v; read_json ' + json.dumps(str(actual))
        base += '; read_verilog -sv ' + json.dumps(str(shim)) + '; '
        for label, parameters in [('exact', {'ATOMIC_C': 32, 'ATOMIC_K': 16, 'TAG_WIDTH': 35}),
                                  ('wrong_c', {'ATOMIC_C': 8}), ('wrong_k', {'ATOMIC_K': 8}),
                                  ('wrong_tag', {'TAG_WIDTH': 34})]:
            command = base + 'chparam ' + ' '.join(f'-set {name} {value}' for name, value in parameters.items()) + ' ' + CMAC
            command += '; hierarchy -check -top ' + CMAC
            if label == 'exact':
                command += '; select -assert-mod-count 1 A:hdlname=' + KERNEL
                command += '; select -assert-count 16 t:*' + KERNEL + '*; check -assert; stat'
            script = out / (label+'.ys')
            script.write_text(command.replace('; ', ';\n') + '\n')
            run(['yosys', '-Q', '-T', '-s', script], label, reject=label != 'exact')
        assert fingerprint(tracked) == result['source']
        verify_manifest(report['source']); verify_area(report['area'])
        artifacts = [out / (label+'.ys') for label in ('exact', 'wrong_c', 'wrong_k', 'wrong_tag')]
        artifacts += [ROOT / step['log'] for step in result['commands']]
        result.update(status='PASS_ACTUAL_FIXED_PARTITION_IMPORT_BOUNDARY_ONLY', artifacts=fingerprint(artifacts))
    except Exception as exc:
        result.update(status='FAIL', reason=str(exc)); raise
    finally:
        result['finished_utc'] = timestamp(); save(); print(out / 'report.json')
    print(result['status'])


if __name__ == '__main__':
    main()
