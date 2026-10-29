#!/usr/bin/env python3
"""Compare isolated actual lane DSP/LUT resources; not equivalence or fit."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from check_lane_dsp import SOURCES, TOP, AREA_INPUTS, AREA_OUTPUTS, area_script, validate_area


def main():
    out = ROOT / f'build/rknpu-lane-dsp-area/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    wrappers = out / 'area_wrappers.sv'
    parts = []
    for label in ('reference', 'actual'):
        parts.append('module cmac_lane_' + label + '_area(input [15:0] op_a,op_b, input [3:0] exp_sft, input pair_nz, output [31:0] lane_sum, output [7:0] res_tag);\n' +
            TOP + ' core(.op_a(op_a),.op_b(op_b),.exp_sft(exp_sft),.pair_nz(pair_nz),' +
            '.reference_lane(' + ('lane_sum' if label == 'reference' else '') + '),' +
            '.reference_tag(' + ('res_tag' if label == 'reference' else '') + '),' +
            '.actual_lane(' + ('lane_sum' if label == 'actual' else '') + '),' +
            '.actual_tag(' + ('res_tag' if label == 'actual' else '') + '),.difference(),.mismatch());\nendmodule\n')
    wrappers.write_text('\n'.join(parts))
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [*SOURCES, wrappers, ROOT / 'rtl/vendor/nvdla/LICENSE', Path(__file__).resolve(), *imported]
    report = dict(status='RUNNING', stage='xc7_area', started_utc=timestamp(), supervisor_pid=os.getpid(),
        source=fingerprint(tracked), python_version=sys.version, seed='none; deterministic XC7 synthesis', commands=[],
        inputs=AREA_INPUTS, outputs=AREA_OUTPUTS,
        numerical_equivalence_acceptance=False, mapped_numerical_acceptance=False,
        full_array_numerical_acceptance=False, raw_board_numerical_acceptance=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Actual isolated compensated donor lane and corrected DSP candidate, identical public widths. XC7 primitive counts only, independent of pending lane equivalence. Not full-array area, placement/LUT sites, timing/DRC/electrical, FPGA or RK acceptance.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=1800)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            assert code == 0 and 'ERROR:' not in text, text[-3000:]
            step['status'] = 'PASS'; return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - started, 3); save()
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate); save()
    generated = [wrappers]
    try:
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        for path in tracked:
            copy = out / 'snapshot' / path.relative_to(ROOT)
            copy.parent.mkdir(parents=True, exist_ok=True); copy.write_bytes(path.read_bytes()); generated.append(copy)
        for label in ('reference', 'actual'):
            top = 'cmac_lane_' + label + '_area'
            script, netlist = out / (label + '_xc7.ys'), out / (label + '_xc7.json')
            script.write_text(area_script([*SOURCES, wrappers], top, netlist))
            generated += [script, netlist]
            run(['yosys', '-Q', '-T', '-s', script], label + '_xc7_mapping')
            design = json.loads(netlist.read_text())
            counts = validate_area(design, top, 1 if label == 'actual' else 0)
            report.setdefault('mapped_cells', {})[label] = counts
            report.setdefault('mapped_lut_primitives', {})[label] = sum(v for k, v in counts.items() if k.startswith('LUT'))
        assert fingerprint(tracked) == report['source'], 'Changed area dependency'
        report.update(status='PASS_ISOLATED_LANE_DSP_XC7_AREA_ONLY', stage='complete', finished_utc=timestamp(),
            artifacts=fingerprint([*generated, *(out.glob('*.log'))]))
    except BaseException:
        report.update(status='FAIL', finished_utc=timestamp()); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
