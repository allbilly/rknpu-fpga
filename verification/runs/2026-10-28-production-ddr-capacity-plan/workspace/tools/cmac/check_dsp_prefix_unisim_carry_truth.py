#!/usr/bin/env python3
"""Separate vendor carry truth-table control; never relabel old oracle failures."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, fingerprint, timestamp
import unisim_board_models as unisim

BENCH = ROOT / 'tests/cmac/tb_dsp_prefix_unisim_carry_truth.sv'
TOP = BENCH.stem
RESULT = (r'^PASS pinned UNISIM CARRY truth binary=1024 four_state=1048576 '
          r'yosys_four_state_differences=([1-9]\d*) first_difference=(\d+); '
          r'not Yosys four-state equivalence or FPGA acceptance$')


def validate_result(text, code, negative=False):
    assert not re.search(r'(?im)\b(?:warning|error)\s*:|sorry:', text)
    markers = [line for line in text.splitlines() if line.startswith('PASS ')]
    if negative:
        marker = 'vendor CARRY mismatch case=0 got=0/0 expected=1/0'
        assert code == 1 and marker in text and not markers
        assert all(marker in line for line in text.splitlines() if 'FATAL:' in line)
        return None
    assert code == 0 and len(markers) == 1 and not re.search(r'FATAL:', text)
    match = re.fullmatch(RESULT, markers[0])
    assert match, 'Incomplete vendor carry truth-table result'
    differences, first = map(int, match.groups())
    assert 0 < differences <= 1048576 and 0 <= first < 1048576
    return dict(binary_comparisons=1024, four_state_comparisons=1048576,
                yosys_four_state_differences=differences, first_difference=first,
                binary_yosys_vendor_equivalence=True, four_state_yosys_vendor_equivalence=False)


def main():
    out = ROOT / f'build/rknpu-dsp-prefix-unisim-carry-truth/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    models, frozen = unisim.freeze_models(out / 'models', {'CARRY4'})
    bench = out / BENCH.name
    bench.write_bytes(BENCH.read_bytes())
    paths = {Path(__file__).resolve(), Path(unisim.__file__).resolve(), ROOT / 'tools/evidence.py',
             BENCH, bench, *models, *frozen}
    source = fingerprint(paths)
    report = dict(status='RUNNING', stage='compile', source=source, started_utc=timestamp(),
                  supervisor_pid=os.getpid(), commands=[], upstream_model_commit=unisim.COMMIT,
                  default_global_startup_preserved=True, primitive_fixture_acceptance=False,
                  numerical_netlist_acceptance=False, physical_fit_verified=False,
                  bitstream_emitted=False, hardware_programmed=False, scope=__doc__)
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, negative=False):
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (label + '.log')).relative_to(ROOT)))
        report['commands'].append(step)
        save()
        started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                    step['pid'] = proc.pid
                    save()
                    try:
                        code = proc.wait(timeout=1800)
                    except BaseException:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        proc.wait()
                        raise
            step['returncode'] = code
            text = (ROOT / step['log']).read_text()
            if label.endswith('_test'):
                result = validate_result(text, code, negative)
            else:
                assert code == 0 and not re.search(r'(?im)\b(?:warning|error)\s*:|sorry:', text)
                result = text
            step['status'] = 'PASS'
            return result
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3)
            save()
    signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(SystemExit(128 + signum)))
    save()
    print(out / 'report.json', flush=True)
    try:
        assert run(['git', '-C', unisim.CACHE, 'rev-parse', 'HEAD'], 'model_commit').strip() == unisim.COMMIT
        assert run(['git', '-C', unisim.CACHE, 'status', '--porcelain', '--untracked-files=all'], 'model_clean') == ''
        report['tool_version'] = run(['iverilog', '-V'], 'version').splitlines()[0]
        report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
        binary = out / 'carry.vvp'
        run(['iverilog', '-g2012', '-Ttyp', '-s', TOP, '-s', 'glbl', '-o', binary,
             *[path for path in frozen if path.suffix == '.v'], bench], 'compile')
        report['execution_inputs'] = fingerprint([binary, bench, *frozen])
        report['stage'] = 'negative_test'
        run(['vvp', binary, '+NEGATIVE=1'], 'negative_test', True)
        report['stage'] = 'positive_test'
        report['result'] = run(['vvp', binary], 'positive_test')
        assert fingerprint(paths) == source
        assert fingerprint([binary, bench, *frozen]) == report['execution_inputs']
        report.update(status='PASS_PINNED_UNISIM_CARRY_TRUTH_WITH_EXPLICIT_YOSYS_FOUR_STATE_DIFFERENCES_ONLY',
                      stage='complete', primitive_fixture_acceptance=True)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([p for p in out.rglob('*') if p.is_file() and p.name != 'report.json'])
        save()


if __name__ == '__main__':
    main()
