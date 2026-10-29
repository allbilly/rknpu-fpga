#!/usr/bin/env python3
"""Native raw CMAC/EW shared-owner replay; no FPGA or inferred timing proof."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.tinystories.joined_warnings import validate, validate_verilator, INVENTORY
from tools.cmac.startup import qualification as q
from tools.tinystories.joined_hierarchy import hierarchy_json, EXPECTED as JOINED_EXPECTED


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def need(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vectors', type=Path, required=True)
    parser.add_argument('--arithmetic', type=Path, default=ROOT/'build/full512-regmem-preparation/1793013000')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--simulator', choices=('iverilog','verilator'), default='iverilog')
    args = parser.parse_args()
    parent, vector, out = args.arithmetic.resolve(), args.vectors.resolve(), args.out.resolve()
    p = json.loads((parent/'report.json').read_text())
    v = json.loads((vector/'report.json').read_text())
    need(p['status'] == 'PREPARED_REGISTERED_BRAM_FULL512_PIPELINE_SOURCE_ONLY' and
         (p['channels'],p['kernels'],p['parallel_products']) == (32,16,512), 'Wrong arithmetic source')
    need(v['status'] == 'STATIC_TRAINED_TILE_JOINED_TEST_VECTORS' and v['lines'] == 1408, 'Wrong trained vectors')
    sources = [parent/'source'/n for n in p['synthesis_sources'] if n.endswith(('.sv','.v'))]
    sources += [parent/'source/rtl/vendor/nvdla/compat'/n for n in ('nv_assert_never.v','nv_assert_no_x.v')]
    sources += [ROOT/'rtl'/n for n in ('rk_fp16_alu.sv','rk_ew_regs.sv','rk_ew_engine.sv','rk_ew_dma.sv',
        'rk_job_control.sv','host/rk_jtag_backend.sv','tinystories/rk_shared_bram_regport.sv',
        'tinystories/rk_cmac_success_rearm.sv','tinystories/rk_jtag_dual_bram.sv')]
    sources += [ROOT/'tests/tinystories/tb_jtag_dual_bram.sv']
    need(len(sources) == len(set(sources)), 'Duplicate source modules')
    need(all(sha(parent/'source'/n) == h for n,h in p['source']['files'].items()),
         'Changed frozen arithmetic source')
    inputs = {str(parent/'source'/n): h for n,h in p['source']['files'].items()}
    inputs.update({str(vector/n):h for n,h in v['files'].items()})
    if 'source_report_path' in v:
        source_report=Path(v['source_report_path'])
        need(sha(source_report)==v['source_report_sha256'],'Changed upstream trained fixture')
        inputs[str(source_report)]=v['source_report_sha256']
        first=json.loads(source_report.read_text())
        for name, record in first['files'].items():
            need(sha(source_report.parent/name)==record['sha256'],'Changed original trained input/program')
            inputs[str(source_report.parent/name)]=record['sha256']
    for path in sources+[parent/'report.json',vector/'report.json',Path(__file__).resolve(),INVENTORY,
                         ROOT/'tools/tinystories/joined_warnings.py', ROOT/'tools/cmac/startup/qualification.py', ROOT/'tools/tinystories/joined_hierarchy.py']:
        inputs[str(path)] = sha(path)
    def check():
        need(all(sha(n) == h for n,h in inputs.items()), 'Joined source/vector drift')
    check()
    need(out.is_relative_to(ROOT/'build') and not out.exists(), 'Fresh build directory required')
    out.mkdir(parents=True)
    report = dict(status='RUNNING', started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  inputs=inputs, products=512, simulator=args.simulator, commands=[], tests=[],
                  scope='Actual full512 CMAC/EW/backend/registered RAM raw-frame composition and rearm; not mailbox CDC/BSCANE2/FPGA/model generation',
                  hardware_accessed=False)
    def save():
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    def execute(name, argv, timeout=1200):
        check()
        entry = dict(name=name, argv=argv, status='RUNNING')
        report['commands'].append(entry)
        save()
        begin = time.monotonic()
        child = None
        try:
            with (out/(name+'.log')).open('w') as log:
                child = subprocess.Popen(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                entry['pid'] = child.pid
                save()
                rc = child.wait(timeout=timeout)
            entry['returncode'] = rc
            need(rc == 0, name+' failed')
            check()
            entry['status'] = 'PASS'
            return (out/(name+'.log')).read_text()
        except BaseException as error:
            entry.update(status='FAIL', error=repr(error))
            if child is not None and child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid,signal.SIGKILL);child.wait()
            raise
        finally:
            entry.update(seconds=time.monotonic()-begin, log_sha256=sha(out/(name+'.log')))
            save()
    save()
    try:
        expected = {'rk_cmac_fp16_array_dsp_prefix_pipe':1,'rk_cmac_fp16_cell_dsp_prefix_pipe':16,
                    'rk_cmac_fp16_lane_dsp_prefix':512,'rk_cmac_fp16_discarded_carry':512}
        report['compiler_version'] = execute('version', [args.simulator,'-V' if args.simulator=='iverilog' else '--version']).splitlines()[0]
        if args.simulator=='iverilog':
            report['runtime_version'] = execute('runtime_version', ['vvp','-V']).splitlines()[0]
            binary=out/'sim.vvp'
            text=execute('compile',['iverilog','-g2012','-Wall','-DDESIGNWARE_NOEXIST','-DASSERT_ON',
                '-I'+str(parent/'source/rtl/vendor/nvdla'),'-s','tb_jtag_dual_bram','-o',str(binary)]+list(map(str,sources)))
            report['reviewed_arithmetic_diagnostics']=validate(text,parent/'source')
            image=binary.read_text()
            hierarchy={n:len(re.findall(r'\.scope module, "[^"]*" "'+n+r'"',image)) for n in expected}
            launch=['vvp',str(binary)]
        else:
            flags=['--timing','--assert','-Wall','-Wno-fatal','--timescale-override','1ns/1ps',
                '-DDESIGNWARE_NOEXIST','-DASSERT_ON','-I'+str(parent/'source/rtl/vendor/nvdla'),
                '--top-module','tb_jtag_dual_bram']
            tree=out/'hierarchy.tree.json'
            text=execute('hierarchy',['verilator','--json-only',*flags,'--Mdir',str(out/'obj'),
                '--json-only-output',str(tree),'--json-only-meta-output',str(out/'hierarchy.meta.json')]+list(map(str,sources)))
            report['hierarchy_diagnostics']=validate_verilator(text,parent/'source',ROOT,compilation=False)
            q.EXPECTED_HIERARCHY=expected
            hierarchy=hierarchy_json(tree)
            need(all(hierarchy[n]==value for n,value in JOINED_EXPECTED.items()), "Changed reachable joined hierarchy")
            report["joined_hierarchy"]=dict(hierarchy)
            hierarchy={n:hierarchy[n] for n in expected}
            text=execute('compile',['verilator','--binary',*flags,'-j','1','--Mdir',str(out/'obj'),'-o','sim']+list(map(str,sources)))
            report['reviewed_arithmetic_diagnostics']=validate_verilator(text,parent/'source',ROOT,compilation=True)
            binary=out/'obj/sim';launch=[str(binary)]
        need(hierarchy == expected, 'Reduced/changed full512 hierarchy')
        report['hierarchy'] = hierarchy
        binary_sha = sha(binary)
        report['binary'] = dict(path=str(binary), sha256=binary_sha)
        for mode in (0,1,2,3,4):
            text = execute('mode'+str(mode), launch+['+DIRECTORY='+str(vector),'+MODE='+str(mode),
                '+LINES='+str(v['lines']),'+EW_LINES='+str(v['ew_delta_lines']),
                '+REPEAT_LINES='+str(v['repeat_delta_lines']),'+EW_AMOUNT='+str(v['ew_amount'])])
            expected_line = (f'PASS dual_raw_jobs mode={mode} cmac_jobs=2 ew_tasks=2 rearm=2 writes=96 checked_lines=4224'
                if mode in (0,4) else f'PASS dual_raw_jobs mode={mode} expected_fault rearm=0 writes=0')
            need([line for line in text.splitlines() if line.startswith('PASS ')] == [expected_line], 'Changed/missing exact joined result')
            need(sha(binary) == binary_sha, 'Executed image changed')
            report['tests'].append(dict(mode=mode, status='PASS', result=expected_line))
            print(expected_line, flush=True)
            save()
        report['status'] = 'PASS_TRAINED_TILE_DUAL_RAW_ENDPOINT_'+args.simulator.upper()+'_ONLY'
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
    print(json.dumps(dict(status=report['status'], report=str(out/'report.json'))))


if __name__ == '__main__':
    main()
