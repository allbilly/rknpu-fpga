#!/usr/bin/env python3
"""Execute a pinned FDPE/RAMB36E1/default-GSR functional model control."""
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from unisim_board_models import CACHE, COMMIT, freeze_models

BENCH = ROOT / 'tests/cmac/tb_observed_board_unisim_models.sv'
MARKER = 'PASS OBSERVED_BOARD_UNISIM_MODEL_CONTROL default_gsr=100ns fdpe=init,preset,enable bram=write_first,read,unknown,retain; not full board or physical proof'


def validate_model_result(text, bench):
    # Icarus 13 emits this source-located finish diagnostic after the marker.
    # Accept exactly the observed final statement/time, not arbitrary extra
    # output. The model-control stimulus, fatal checks and time are unchanged.
    lines = BENCH.read_text().splitlines()
    finish = [i + 1 for i, line in enumerate(lines) if line.strip() == '$finish;']
    assert len(finish) == 1
    expected = [MARKER, f'{bench}:{finish[0]}: $finish called at 352000 (1ps)']
    assert text.splitlines() == expected, ('Unexpected model-control result', text)


def main():
    out = ROOT / f'build/rknpu-unisim-board-model-control/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    original, frozen = freeze_models(out / 'models', {'FDPE', 'RAMB36E1'})
    tracked = [BENCH, Path(__file__).resolve(), ROOT / 'tools/cmac/unisim_board_models.py', ROOT / 'tools/evidence.py', *original]
    report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), commands=[],
        upstream_commit=COMMIT, numerical_board_acceptance=False, physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Small unmodified pinned FDPE and RAMB36E1 functional-model control with default glbl startup, asynchronous preset/clock-enable, WRITE_FIRST, separate-address reads, unknown data and retention. Real incorrect read-golden negative. Not mapped C32/K16 or raw-board numerical/fault/reset, timing/DRC/electrical or FPGA acceptance.')

    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, negative=False):
        path = out / (label + '.log')
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str(path.relative_to(ROOT)))
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with path.open('w') as stream:
                result = subprocess.run(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
            step['returncode'] = result.returncode
            text = path.read_text()
            assert result.returncode == (1 if negative else 0), text
            assert not re.search(r'(?im)\bwarning:|\berror:|\bsorry:', text), text
            if negative:
                assert 'UNISIM BRAM read mismatch' in text and MARKER not in text
            step['status'] = 'PASS'; return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3); save()

    save()
    try:
        for path in set(tracked):
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes())
        report['iverilog_version'] = run(['iverilog', '-V'], 'iverilog_version').splitlines()[0]
        report['vvp_version'] = run(['vvp', '-V'], 'vvp_version').splitlines()[0]
        assert run(['git', '-C', CACHE, 'rev-parse', 'HEAD'], 'model_commit').strip() == COMMIT
        assert run(['git', '-C', CACHE, 'status', '--porcelain', '--untracked-files=all'], 'model_clean') == ''
        bench = out / BENCH.name; bench.write_bytes(BENCH.read_bytes())
        models = [p for p in frozen if p.suffix == '.v']
        inputs = [bench, *frozen]
        report['compile_inputs'] = fingerprint(inputs); save()
        executable = out / 'control.vvp'
        # Explicitly select the simulator's default typ corner. The inspected
        # RAMB36E1 lines 1329..1333 use identical 100:100:100 delay values;
        # this does not change model bytes or waive compile warnings. This
        # functional test has no SDF/XIL_TIMING or physical timing acceptance.
        run(['iverilog', '-g2012', '-Ttyp', '-s', 'tb_observed_board_unisim_models', '-s', 'glbl', '-o', executable, *models, bench], 'compile')
        assert fingerprint(inputs) == report['compile_inputs']
        report['compiled_executable'] = fingerprint([executable]); save()
        for label, extra in [('negative', ['+NEGATIVE']), ('actual', [])]:
            assert fingerprint(inputs) == report['compile_inputs'] and fingerprint([executable]) == report['compiled_executable']
            report.setdefault('execution_inputs', {})[label] = fingerprint([*inputs, executable]); save()
            text = run(['vvp', executable, *extra], label, negative=bool(extra))
            if not extra: validate_model_result(text, bench)
            assert fingerprint([*inputs, executable]) == report['execution_inputs'][label]
        assert fingerprint(tracked) == report['source'], 'Changed model-control sources'
        report.update(status='PASS_OBSERVED_BOARD_UNISIM_MODEL_CONTROL_ONLY',
            artifacts=fingerprint([*inputs, executable, *(ROOT / c['log'] for c in report['commands'])]))
    except BaseException as exc:
        report.update(status='FAIL', reason=str(exc) or repr(exc)); raise
    finally:
        report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
    print(report['status'])


if __name__ == '__main__': main()
