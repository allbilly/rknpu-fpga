#!/usr/bin/env python3
"""Check an isolated fixed-FP16 specialization against original partial rows.

No array RTL is replaced. The formal gate proves the donor's mode and active
comparison after reset/setup, then checks arbitrary paired-nz operands with
those proven mode values propagated into the combinational datapath.
The simulation compares each row and tag, not just their compensated sum.
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

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--tool', choices=('verilator', 'iverilog'), default='verilator')
a = p.parse_args()
out = ROOT / f'build/rknpu-fixed-fp16-rows/{a.tool}-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
donor = ROOT / 'rtl/vendor/nvdla'
sources = [donor / 'NV_DW02_tree.v', donor / 'NV_NVDLA_CMAC_CORE_MAC_mul.v',
           ROOT / 'rtl/cmac/experimental/rk_cmac_fp16_rows.sv']
bench = ROOT / 'tests/cmac/tb_cmac_fp16_rows.sv'
miter = ROOT / 'tests/cmac/cmac_fp16_rows_miter.sv'
compat = [donor / 'compat/nv_assert_never.v', donor / 'compat/nv_assert_no_x.v']
tracked = sources + compat + [bench, miter, Path(__file__).resolve()]
tracked += [donor / n for n in ('nv_assert_never.vlib', 'nv_assert_no_x.vlib', 'assertion_header.h', 'assertion_task.h', 'LICENSE')]
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked),
              commands=[], seed='3588f016',
              contract='Fixed FP16 only, paired nz, operand valids always high. Compare both 32-bit partial rows and 8-bit tag after one configuration clock; no pre-configuration equivalence claim.',
              scope='Isolated donor specialization experiment. Not integrated into C32/K16, not mapped numerical, timing/fit, FPGA or RK evidence.')
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(path.read_bytes())
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
def run(argv, name, lint=False):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name+'.log')).relative_to(ROOT)))
    report['commands'].append(step); save(); start = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            with subprocess.Popen(step['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                try: code = proc.wait(timeout=7200)
                except BaseException:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait(); raise
        step['returncode'] = code
        text = (ROOT / step['log']).read_text()
        assert code == 0 and 'ERROR :' not in text, text[-6000:]
        if lint:
            warnings = Counter(re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:', text, re.M))
            assert all(Path(path).parent == donor or (Path(path) == bench and kind == 'BLKSEQ')
                       for kind, path, _ in warnings), warnings
            step['warning_locations'] = [list(k)+[v] for k,v in sorted(warnings.items())]
        elif name in ('compile', 'test'):
            assert 'warning' not in text.lower() and 'sorry:' not in text.lower(), text[-3000:]
        step['status'] = 'PASS'; return text
    except Exception:
        step['status'] = 'FAIL'; raise
    finally:
        step['seconds'] = round(time.monotonic()-start, 3); save()
save()
try:
    report['yosys_version'] = run(['yosys','-V'], 'yosys_version').strip()
    prefix = 'read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST ' + ' '.join(json.dumps(str(s)) for s in sources+[miter])
    prefix += '; prep -top cmac_fp16_rows_miter -flatten; async2sync; opt; check -assert'
    control = prefix + '; sat -seq 3 -set-init-zero -set-at 1 rst_n 0 -set-at 2 rst_n 1 -set-at 3 rst_n 1'
    control += ' -prove-skip 2 -prove active 1 -prove original.cfg_is_fp16_d1 15 -prove original.cfg_is_int8_d1 0'
    control += ' -verify -show-inputs -show-outputs'
    # These substitutions are permitted only after the preceding control
    # lemma proves exactly these values at an active comparison boundary.
    # No operand, mask, shift, partial row or comparison output is assumed.
    datapath = prefix + "; connect -set original.cfg_is_fp16_d1 4'b1111"
    datapath += "; connect -set original.cfg_is_int8_d1 1'b0; connect -set active 1'b1"
    # Boolean lowering lets opt_merge combine equivalent bit-level logic that
    # remains differently packaged in word-level donor/specialized cells. This
    # transforms both sides, adds no assumptions and retains the same mismatch.
    datapath += '; opt -full; check -assert; techmap; opt -full; check -assert'
    datapath += '; sat -prove mismatch 0 -verify -show-inputs -show-outputs'
    formal_control = out / 'configuration.ys'
    formal_datapath = out / 'datapath.ys'
    formal_control.write_text(control.replace('; ', ';\n')+'\n')
    formal_datapath.write_text(datapath.replace('; ', ';\n')+'\n')
    report['tool_version'] = run([a.tool, '--version' if a.tool=='verilator' else '-V'], 'version').splitlines()[0]
    defines = ['-DDESIGNWARE_NOEXIST','-DASSERT_ON',f'-I{donor}']
    if a.tool == 'verilator':
        report['cxx_version'] = run(['c++','--version'], 'cxx_version').splitlines()[0]
        binary = out / 'obj/sim'
        run(['verilator','--binary','--timing','--assert','-Wall','-Wno-fatal',
             '--timescale-override','1ns/1ps',*defines,'-j','2','--top-module',bench.stem,
             '--Mdir',out/'obj','-o','sim',*compat,*sources,bench], 'compile', lint=True)
        execute = [binary]
    else:
        binary = out / 'sim.vvp'
        run(['iverilog','-g2012',*defines,'-s',bench.stem,'-o',binary,*compat,*sources,bench], 'compile')
        report['runtime_version'] = run(['vvp','-V'], 'runtime_version').splitlines()[0]
        execute = ['vvp',binary]
    text = run(execute, 'test')
    expected = 'PASS fixed FP16 rows comparisons=2097152 resets=4 seed=3588f016; post-configuration only'
    assert [line for line in text.splitlines() if line.startswith('PASS ')] == [expected], text[-4000:]
    report['simulation_result'] = expected
    for script,name in ((formal_control,'formal_control'),(formal_datapath,'formal_datapath')):
        proof = run(['yosys','-Q','-T','-s',script], name)
        assert 'SAT proof finished - no model found: SUCCESS!' in proof, proof[-4000:]
    report['formal_result'] = 'PASS_COMPOSED_POST_CONFIGURATION_ROWS_AND_ACTIVE_COMPARE'
    assert fingerprint(tracked) == report['source'], 'Source changed while testing'
    report.update(status='PASS_FIXED_FP16_ROWS_EXPERIMENT_ONLY', result=expected,
                  artifacts=fingerprint([formal_control,formal_datapath,binary]+[ROOT/c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc)); raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'], report['result'])
