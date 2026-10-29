#!/usr/bin/env python3
"""Actual unchanged FDCE startup/reset model control for the full mapped top."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from audit_dsp_prefix_compile_inventory import diagnostics

BENCH = ROOT / 'tests/cmac/tb_dsp_prefix_fdce_startup_control.sv'
TOP = BENCH.stem
EXPECTED = 'PASS actual prefix FDCE startup/reset control checks=129 init_variants=0/1/X; not array or FPGA acceptance'


def validate_result(text, code, negative=False):
    assert not re.search(r'(?im)warning:|%Warning-|sorry:', text)
    markers = [line for line in text.splitlines() if line.startswith('PASS ')]
    if negative:
        assert code != 0 and 'FDCE startup mismatch case=0' in text and not markers
        for line in text.splitlines():
            if re.search(r'%Error|\berror:|FATAL:', line, re.I):
                assert 'FDCE startup mismatch case=0' in line or 'Verilog $stop' in line
    else:
        assert code == 0 and markers == [EXPECTED]
        assert not re.search(r'%Error|\berror:|FATAL:', text, re.I)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-report', type=Path, required=True)
    parser.add_argument('--simulator', choices=('iverilog','verilator'), required=True)
    args = parser.parse_args()
    parent_path = args.compile_report.resolve()
    assert parent_path.is_relative_to(ROOT)
    parent = json.loads(parent_path.read_text())
    assert parent['status'] == 'FAIL' and parent['finished_utc']
    model = parent_path.parent / 'xilinx_functional_models.v'
    part = parent_path.parent / 'actual_partition.json'
    for path in (model, part):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == parent['source']['files'][str(path.relative_to(ROOT))]
    raw = json.loads(part.read_text())
    module = raw['modules']['rk_cmac_fp16_array_dsp_prefix']
    flops = [cell for cell in module['cells'].values() if cell['type'].startswith('FD')]
    assert len(flops) == 742 and all(cell['type']=='FDCE' and cell['parameters']=={'INIT':'x'} for cell in flops)
    assert model.read_text().splitlines()[691].strip() == 'initial Q <= INIT;'
    out = ROOT / f'build/rknpu-dsp-prefix-fdce-startup/{args.simulator}-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    frozen, bench = out / 'unchanged_model.v', out / BENCH.name
    frozen.write_bytes(model.read_bytes());bench.write_bytes(BENCH.read_bytes())
    tracked = [Path(__file__).resolve(), ROOT/'tools/evidence.py',
        ROOT/'tools/cmac/audit_dsp_prefix_compile_inventory.py', BENCH, parent_path, model, part, frozen, bench]
    before = fingerprint(tracked)
    for path in tracked:
        target = out / 'snapshot' / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(path.read_bytes())
    report = dict(status='RUNNING', started_utc=timestamp(), commands=[], source=before,
        simulator=args.simulator, supervisor_pid=os.getpid(), model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        compile_report=str(parent_path.relative_to(ROOT)), actual_array_fdce_count=742, actual_array_fdce_init='x',
        startup_scope='INIT=0/1 checked after delta settling; actual INIT=X retained in Icarus. Reset establishes binary Q.',
        fdce_startup_reset_fixture_acceptance=False, top_diagnostics_accepted=False,
        full_array_numerical_acceptance=False, physical_fit_verified=False, bitstream_emitted=False)
    def save():
        (out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    def run(argv,label,negative=None):
        step=dict(argv=list(map(str,argv)),log=str((out/(label+'.log')).relative_to(ROOT)),status='RUNNING')
        report['commands'].append(step);save();start=time.monotonic()
        try:
            with (ROOT/step['log']).open('w') as stream:
                def no_core():resource.setrlimit(resource.RLIMIT_CORE,(0,0))
                result=subprocess.run(step['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                    timeout=300,start_new_session=True,preexec_fn=no_core)
            step['returncode']=result.returncode;text=(ROOT/step['log']).read_text()
            if negative is not None:validate_result(text,result.returncode,negative)
            else:
                assert result.returncode==0
                if args.simulator=='verilator':
                    entries=diagnostics(text)
                    for entry in entries:
                        assert Path(entry['source']) in (frozen,bench)
                        if entry['kind']=='INITIALDLY':
                            assert Path(entry['source'])==frozen and entry['line']==692
                            assert entry['message']=="Non-blocking assignment '<=' in initial/final block"
                        else:assert entry['kind'] in ('SPECIFYIGN','GENUNNAMED','DECLFILENAME')
                    step['diagnostic_counts']=dict(Counter(entry['kind'] for entry in entries))
                else:assert not re.search(r'(?im)warning:|ERROR:|sorry:',text)
            step['status']='PASS';return text
        except BaseException:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    save()
    try:
        report['tool_version']=run([args.simulator,'--version' if args.simulator=='verilator' else '-V'],'version').splitlines()[0]
        if args.simulator=='verilator':
            obj=out/'obj'
            run(['verilator','--binary','--timing','--assert','-Wall','-Wno-fatal','--timescale-override','1ns/1ps',
                '-j','2','--top-module',TOP,'--Mdir',obj,'-o','sim',frozen,bench],'compile')
            binary=obj/'sim';command=[str(binary)]
        else:
            binary=out/'sim.vvp'
            run(['iverilog','-g2012','-s',TOP,'-o',binary,frozen,bench],'compile');command=['vvp',str(binary)]
        execution=fingerprint([binary]);report['execution_inputs']=execution
        run([*command,'+NEGATIVE=1'],'negative_test',True)
        run(command,'positive_test',False)
        assert fingerprint(tracked)==before and fingerprint([binary])==execution
        report.update(status='PASS_ISOLATED_ACTUAL_PREFIX_FDCE_STARTUP_RESET_FIXTURES_ONLY',
            fdce_startup_reset_fixture_acceptance=True,checks=129)
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['finished_utc']=timestamp()
        report['artifacts']=fingerprint([path for path in out.rglob('*') if path.is_file() and path!=out/'report.json'])
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
