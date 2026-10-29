#!/usr/bin/env python3
"""Actually test exclusive Yosys stage endpoints; not full CMAC acceptance."""
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

TOP = 'cmac_dsp_stage_probe'
CELL = 'cmac_dsp_stage_probe_kernel'
FIXTURE = ROOT / 'tests/cmac/cmac_dsp_stage_probe.sv'


def probe_script(out, end_label, prefix='probe'):
    assert end_label in ('map_dsp', 'coarse')
    target = json.dumps(str(out / (prefix + '.json')))
    return '\n'.join([
        'read_verilog -sv ' + json.dumps(str(FIXTURE)) + ';',
        f'hierarchy -check -top {TOP};',
        f'select -assert-mod-count 1 {CELL};',
        f'setattr -mod -set keep_hierarchy 1 {CELL};',
        f'select -assert-count 2 */t:{CELL};',
        'proc; opt_clean; check -assert;',
        f'synth_xilinx -family xc7 -top {TOP} -flatten -noiopad -noclkbuf -run begin:{end_label};',
        'check -assert;',
        # Match synth_xilinx's standard finalization of declaration-only
        # library modules. Actual instantiated DSP types/ports remain intact.
        'blackbox =A:whitebox;', 'write_json ' + target + ';',
    ]) + '\n'


def probe_counts(design):
    modules = design['modules']; top = modules[TOP]
    assert set(top['ports']) == {'operands', 'products'}
    for name, direction in [('operands', 'input'), ('products', 'output')]:
        port = top['ports'][name]
        assert port['direction'] == direction and len(port['bits']) == 128
        assert all(type(b) is int for b in port['bits'])
    assert len(set(top['ports']['operands']['bits'])) == 128
    assert len(top['cells']) == 2
    assert all(c['type'] == CELL for c in top['cells'].values())
    kernel = modules[CELL]
    assert int(kernel['attributes']['keep_hierarchy'], 2) == 1
    counts = Counter(c['type'] for c in kernel['cells'].values())
    return {'kernel_instances': 2, 'per_kernel': dict(counts),
            'total_dsp48e1': counts['DSP48E1'] * 2,
            'total_unmapped_multipliers': counts['$mul'] * 2}


def validate_probe(log, counts, mapped):
    assert 'ERROR:' not in log and not re.search(r'(?im)^Warning:', log)
    assert 'Executing SHARE pass' not in log
    assert ('Executing XILINX_DSP pass' in log) == mapped
    assert counts['kernel_instances'] == 2
    assert counts['total_dsp48e1'] == (4 if mapped else 0)
    assert counts['total_unmapped_multipliers'] == (0 if mapped else 4)


def main():
    out = ROOT / f'build/rknpu-dsp-stage-probe/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    source_paths = [Path(__file__).resolve(), FIXTURE, ROOT / 'tools/evidence.py']
    before = fingerprint(source_paths)
    report = dict(status='RUNNING', stage='execution', started_utc=timestamp(), source=before,
        commands=[], supervisor_pid=os.getpid(), controls={}, numerical_acceptance=False,
        full_array_acceptance=False, physical_fit_verified=False, bitstream_emitted=False,
        scope='Actual two-kernel/four-independent-product XC7 synthesis-stage control. '
              'Exclusive endpoint behavior only, not a CMAC array numerical/resource or physical result.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                      start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=300)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code
            assert code == 0
            text = (ROOT / step['log']).read_text()
            assert not re.search(r'(?im)^(?:Warning|ERROR):', text)
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - started, 3); save()
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate); save()
    generated = []
    try:
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        for path in source_paths:
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes()); generated.append(target)
        for label, end_label, mapped in [('skipped_dsp_negative', 'map_dsp', False),
                                        ('executed_dsp_positive', 'coarse', True)]:
            script = out / (label + '.ys')
            script.write_text(probe_script(out, end_label, label))
            generated.append(script)
            inputs = fingerprint([FIXTURE, script])
            log = run(['yosys', '-Q', '-T', '-s', script], label)
            assert fingerprint([FIXTURE, script]) == inputs
            netlist = out / (label + '.json'); generated.append(netlist)
            counts = probe_counts(json.loads(netlist.read_text()))
            validate_probe(log, counts, mapped)
            report['controls'][label] = dict(end_label=end_label, counts=counts, compile_inputs=inputs)
            save()
        assert fingerprint(source_paths) == before
        report.update(status='PASS_ACTUAL_EXCLUSIVE_DSP_STAGE_ENDPOINT_CONTROLS_ONLY',
                      stage='complete', finished_utc=timestamp(),
                      artifacts=fingerprint([*generated, *out.glob('*.log')]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
                      artifacts=fingerprint([p for p in [*generated, *out.glob('*.log')] if p.is_file()]))
        raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
