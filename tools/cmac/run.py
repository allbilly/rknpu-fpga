#!/usr/bin/env python3
"""Consolidated raw-command CMAC tests and YPCB open-source build.

No external NVDLA checkout, scratch-source dependency, CPU execution fallback,
bitstream emission or programming. P&R is characterization, not signoff.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT,fingerprint,timestamp
from board_contract import validate_board_result
from run_openxc7 import (PART,NEXTPNR_REV,XRAY_REV,META_REV,SIGNOFF_GAPS,
                        normalized_xdc,package_pins,check_timing_report,pinned_checkout,digest)

def inputs():
    imports=json.loads((ROOT/'fpga/cmac/IMPORTS.json').read_text())
    spec=json.loads((ROOT/'fpga/cmac/sources.json').read_text())
    for item in imports['imports']:
        assert digest(ROOT/item['path'])==item['sha256'],item['path']
    paths=[ROOT/i['path'] for i in imports['imports']]
    paths += [ROOT/p for p in spec['synthesis']+spec['simulation_helpers']]
    paths += [ROOT/p for p in ('fpga/cmac/Makefile','fpga/cmac/sources.json','fpga/cmac/IMPORTS.json',
                              'tests/cmac/fixtures.json','tests/axil_host.svh','tests/memory_check.svh','fpga/ypcb.xdc',
                              'tools/cmac/run.py','tools/cmac/board_contract.py','tools/evidence.py','tools/run_openxc7.py')]
    return spec,fingerprint(paths)

def check_rom():
    base=ROOT/'tests/cmac/data/m2_n17_k65_finite'
    windows=[(0x10010000,448,0),(0x10020000,6208,448),
             (0x10040000,320,6656),(0x100e0000,448,6976)]
    def index(address):
        hits=[(address-start+offset)//2 for start,size,offset in windows
              if start<=address<start+size and address%2==0]
        assert len(hits)==1,address
        return hits[0]
    initial=[0xa55a]*4096
    for name,address in [('input',0x10010000),('weight',0x10020000)]:
        for i,value in enumerate((base/(name+'.hex')).read_text().split()):initial[index(address+2*i)]=int(value,16)
    commands=[int(x,16) for x in (base/'commands.hex').read_text().split()]
    assert len(commands)==49
    for i,word in enumerate(commands):
        for part in range(4):initial[index(0x100e0000+i*8+part*2)]=(word>>(16*part))&65535
    expected=initial.copy()
    for token in (base/'outputs.hex').read_text().split():
        value=int(token,16);expected[index(value>>17)]=(value>>1)&65535
    text=''.join(f'{check:04x}{value:04x}\n' for value,check in zip(initial,expected))
    assert (ROOT/'tests/cmac/data/board_rom.hex').read_text()==text,'stale packaged board ROM'

def main():
    if not __debug__:
        raise RuntimeError('CMAC verification requires Python assertions enabled; do not use -O')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('check','test','synth','pnr'))
    parser.add_argument('--tool',choices=('verilator','iverilog'),default='verilator')
    parser.add_argument('--suite',choices=('board','core','dma','memory'),default='board')
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--synth-report',type=Path)
    args=parser.parse_args()
    if not 1<=args.jobs<=4:parser.error('jobs must be 1..4')
    spec,source=inputs();check_rom()
    if args.action=='check':
        print('PASS local CMAC imports, source manifest and raw-fixture ROM consistency',source['sha256']);return
    out=(args.out or ROOT/'build/cmac-integrated'/f'{args.action}-{args.suite}-{args.tool}-{time.time_ns()}').resolve()
    if not out.is_relative_to(ROOT/'build') or out==ROOT/'build':parser.error('output must be a new directory below build/')
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',started_utc=timestamp(),source=source,action=args.action,suite=args.suite,
                seed='data 0x3588ca15; core/DMA protocol 0x3588ca16; board directed',commands=[],tests=[],
                scope='Consolidated local CMAC source tree. Synthetic numerical fixtures. No RK equivalence, physical board result or complete NPU/runtime claim.',
                bitstream_emitted=False,hardware_programmed=False)
    lock=threading.Lock();warning_baseline=None
    def save():
        with lock:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(argv,name,timeout=7200,lint=False):
        nonlocal warning_baseline
        step=dict(argv=list(map(str,argv)),status='RUNNING',log=str((out/(name+'.log')).relative_to(ROOT)))
        with lock:report['commands'].append(step)
        save();start=time.monotonic()
        try:
            with (ROOT/step['log']).open('w') as f:
                p=subprocess.run(step['argv'],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
            text=(ROOT/step['log']).read_text();step['returncode']=p.returncode
            assert p.returncode==0 and 'ERROR :' not in text,text[-5000:]
            if lint:
                locations=Counter(re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:',text,re.M))
                reset=ROOT/'fpga/cmac/ypcb_cmac_top.sv'
                reset_line=str(next(i for i,s in enumerate(reset.read_text().splitlines(),1) if 'reg reset_n;' in s))
                reviewed=('SYNCASYNCNET',str(reset),reset_line)
                for key in locations:
                    assert Path(key[1]).parent==ROOT/'rtl/vendor/nvdla' or (args.suite=='board' and key==reviewed),key
                if args.suite=='board':assert locations[reviewed]==1,locations
                if warning_baseline is None:
                    warning_baseline=locations
                    report['reviewed_warning_locations']=[list(k)+[v] for k,v in sorted(locations.items())]
                    report['reset_warning_reason']='Synchronized reset also gates synchronous BRAM enables; no RAM data reset. Off-edge assertion and three-edge release tested.'
                else:assert locations==warning_baseline,locations
            elif name=='compile':
                assert 'warning:' not in text.lower() and 'sorry:' not in text.lower(),text[-3000:]
            step['status']='PASS';return text
        except subprocess.TimeoutExpired:step['status']='TIMEOUT';raise
        except Exception:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    save()
    try:
        if args.action=='test':
            tool=args.tool;top=spec['tops'][args.suite];bench=ROOT/spec['benches'][args.suite]
            test_top=bench.stem
            sources=[ROOT/p for p in spec['simulation_helpers']+spec['synthesis']]
            if args.suite=='memory':sources=[ROOT/'rtl/cmac/rk_cmac_demo_memory.sv']
            defines=['-DDESIGNWARE_NOEXIST','-DASSERT_ON',*[f'-I{ROOT/p}' for p in spec['include_dirs']]]
            report['tool_version']=run([tool,'--version' if tool=='verilator' else '-V'],'version').splitlines()[0]
            if tool=='verilator':
                flags=['--timing','--assert','-Wall','-Wno-fatal','--timescale-override','1ns/1ps',*defines]
                run([tool,'--lint-only',*flags,'--top-module',top,*sources],'baseline_lint',lint=True)
                run([tool,'--lint-only',*flags,'--top-module',test_top,*sources,bench],'bench_lint',lint=True)
                binary=out/'obj/sim'
                report['cxx_version']=run(['c++','--version'],'cxx_version').splitlines()[0]
                run([tool,'--binary',*flags,'-j',args.jobs,'--top-module',test_top,'--Mdir',out/'obj','-o','sim',*sources,bench],'compile',lint=True)
                execute=[binary]
            else:
                binary=out/'sim.vvp'
                run([tool,'-g2012',*defines,'-s',test_top,'-o',binary,*sources,bench],'compile')
                report['vvp_version']=run(['vvp','-V'],'vvp_version').splitlines()[0];execute=['vvp',binary]
            report['runtime_binary']=fingerprint([binary])
            save()
            fixtures=json.loads((ROOT/'tests/cmac/fixtures.json').read_text())['cases']
            if args.suite=='board':jobs=[(None,m) for m in list(range(7 if tool=='verilator' else 8))+[8]]
            elif args.suite=='memory':jobs=[(None,0)]
            else:
                modes=([1,2,3,4,7,8,9,10]+([5,6,11] if tool=='iverilog' else [])) if args.suite=='core' else [7,8,12,15,16,17,18,3,21,1,2,4,9,19,10]+([5,6,11,13,14] if tool=='iverilog' else [])
                jobs=[(c,0) for c in fixtures]+[(fixtures[3],m) for m in modes]
            def test(case,mode):
                name=(case['name']+'_' if case else '')+'mode'+str(mode)
                argv=execute+[f'+MODE={mode}']
                if case:
                    argv += [f'+ROOT={ROOT/"tests/cmac/data"/case["name"]}',f'+ROWS={case["rows"]}',
                             f'+AI={case["ai"]}',f'+AO={case["ao"]}',f'+GROUPS={case["groups"]}']
                text=run(argv,name);lines=[s for s in text.splitlines() if s.startswith('PASS ')]
                assert len(lines)==1,text
                if args.suite=='board':
                    validate_board_result(lines[0],mode)
                elif args.suite=='memory':assert 'transactions=11144 rejected=3720 reset_pending_write=1' in lines[0],lines
                elif mode in ((0,9,10,19) if args.suite=='dma' else (0,9,10)):
                    assert f'good_jobs={2 if mode==10 else 1} faults=0 resets={int(mode in (9,19))}' in lines[0],lines
                    assert f'reads={case["pairs"]*2} writes={case["outputs"]} groups={case["groups"]} acks={case["outputs"]}' in lines[0],lines
                else:assert f'mode={mode} good_jobs=0 faults=1 resets=0' in lines[0],lines
                with lock:report['tests'].append(dict(name=name,status='PASS',result=lines[0]))
                save();print(lines[0],flush=True)
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                for future in as_completed([pool.submit(test,c,m) for c,m in jobs]):future.result()
            if fingerprint([binary])!=report['runtime_binary']:
                raise RuntimeError('compiled simulator changed during replay')
            report['status']='PASS_CONSOLIDATED_CMAC_NATIVE_'+args.suite.upper()
        elif args.action=='synth':
            report['yosys_version']=run(['yosys','-V'],'version').strip()
            sources=[ROOT/p for p in spec['synthesis']];design=out/'mapped.json'
            script='read_verilog -sv -DDESIGNWARE_NOEXIST '+ ' '.join(json.dumps(str(p)) for p in sources)
            script+='; hierarchy -check -top ypcb_cmac_top; proc; opt_clean; check -assert; synth_xilinx -family xc7 -top ypcb_cmac_top -flatten; check -assert; write_json '+json.dumps(str(design))
            run(['yosys','-Q','-T','-p',script],'mapping')
            module=json.loads(design.read_text())['modules']['ypcb_cmac_top']
            counts=Counter(c['type'] for c in module['cells'].values())
            assert not any(k.startswith('$') and k!='$scopeinfo' for k in counts),counts
            assert counts['RAMB18E1']+counts['RAMB36E1']>0 and counts['DSP48E1']>0,counts
            assert counts['IBUF']==2 and counts['OBUF']==3,counts
            report.update(status='PASS_CONSOLIDATED_CMAC_MAPPING_ONLY',cells=dict(counts),netlist=str(design.relative_to(ROOT)))
        else:
            assert args.synth_report and args.synth_report.is_file(),'pass --synth-report from a completed consolidated mapping'
            mapped=json.loads(args.synth_report.read_text())
            assert mapped['status']=='PASS_CONSOLIDATED_CMAC_MAPPING_ONLY' and mapped['source']==source
            design=ROOT/mapped['netlist']
            assert digest(design)==mapped['artifacts']['files'][mapped['netlist']]
            checkout=ROOT/'build/reference/nextpnr-xilinx';database=checkout/'xilinx/external/prjxray-db'
            report['tool_sources']=[pinned_checkout(checkout,NEXTPNR_REV),pinned_checkout(database,XRAY_REV),
                                    pinned_checkout(checkout/'xilinx/external/nextpnr-xilinx-meta',META_REV)]
            report['package_pins']=package_pins((database/'kintex7'/PART/'package_pins.csv').read_text())
            normalized,exceptions=normalized_xdc((ROOT/'fpga/ypcb.xdc').read_text())
            xdc=out/'ypcb.literal.xdc';xdc.write_text(normalized)
            nextpnr=ROOT/'build/openxc7/nextpnr-build/nextpnr-xilinx'
            chipdb=ROOT/'build/openxc7'/(PART+'.bin')
            report.update(signoff='NOT_ESTABLISHED',signoff_gaps=SIGNOFF_GAPS,part=PART,pnr_seed=3588,
                          external_exceptions_not_applied=exceptions,tool_inputs={str(p):digest(p) for p in (nextpnr,chipdb)})
            report['nextpnr_version']=run([nextpnr,'--version'],'version').strip()
            log=run([nextpnr,'--chipdb',chipdb,'--json',design,'--xdc',xdc,'--freq','50','--seed','3588',
                     '--verbose','--report',out/'pnr.json','--write',out/'routed.json'],'place_route')
            assert not any(s in log.lower() for s in ('ignored','not supported','not applied','matched nothing')),log[-3000:]
            report['estimated_clock_only']=check_timing_report(json.loads((out/'pnr.json').read_text()))
            assert all(digest(Path(p))==sha for p,sha in report['tool_inputs'].items())
            report['status']='PNR_CHARACTERIZED_NOT_SIGNOFF'
        assert inputs()[1]==source,'source changed during run'
        artifacts=[p for p in out.iterdir() if p.is_file() and p.name!='report.json']
        if args.action=='test':artifacts.append(binary)
        report['artifacts']=fingerprint(artifacts)
    except Exception as exc:report.update(status='FAIL',reason=str(exc));raise
    finally:report['finished_utc']=timestamp();save();print(out/'report.json',flush=True)
    print(report['status'],flush=True)

if __name__=='__main__':main()
