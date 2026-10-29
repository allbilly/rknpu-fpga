#!/usr/bin/env python3
"""Run the isolated AXI-Lite/raw-frame bridge in both native simulators."""
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.owned_process import run_owned
DUT=ROOT/'rtl/host/rk_axil_frame_mailbox.sv'
BENCH=ROOT/'tests/host/frame_mailbox/tb_axil_frame_mailbox.sv'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(condition,message):
    if not condition:raise RuntimeError(message)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator',choices=('both','iverilog','verilator'),default='both')
    parser.add_argument('--component',choices=('mailbox','owner','frontend','admission'),default='mailbox')
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    if args.component=='frontend':
        dut=ROOT/'rtl/host/rk_pcie_jtag_frame_frontend.sv'
        bench=ROOT/'tests/host/frame_frontend/tb_pcie_jtag_frame_frontend.sv'
        top='tb_pcie_jtag_frame_frontend'
        marker=r'^PASS_PCIE_JTAG_FRAME_FRONTEND checks=(\d+)$'
        # Baseline frontend contract: 1600 checks. Epoch integration and
        # explicit mailbox admission add 490 directed startup/loss/recovery
        # checks while preserving the healthy and owner-fault expectations.
        expected_counts={'iverilog':2090,'verilator':2090}
    elif args.component=='admission':
        dut=DUT
        bench=ROOT/'tests/host/frame_mailbox/tb_axil_frame_mailbox_admission.sv'
        top='tb_axil_frame_mailbox_admission'
        marker=r'^PASS frame mailbox admission checks=(\d+) four_state=(\d+)$'
        # Strict admission controls: Icarus includes X admission; Verilator is two-state.
        expected_counts={'iverilog':83,'verilator':71}
    elif args.component=='owner':
        dut=ROOT/'rtl/host/rk_raw_frame_owner_mux.sv'
        bench=ROOT/'tests/host/frame_owner/tb_raw_frame_owner_mux.sv'
        top='tb_raw_frame_owner_mux'
        marker=r'^PASS_RAW_FRAME_OWNER_MUX checks=(\d+)$'
        expected_counts={'iverilog':259,'verilator':259}
    else:
        dut,bench=DUT,BENCH
        top='tb_axil_frame_mailbox'
        marker=r'^PASS frame mailbox checks=(\d+)$'
        expected_counts={'iverilog':1151,'verilator':1142}
    dut_inputs=([DUT,ROOT/'rtl/host/rk_raw_frame_owner_mux.sv',ROOT/'rtl/host/rk_transport_epoch_guard.sv',dut]
                if args.component=='frontend' else [dut])
    out=(args.out if args.out is not None else ROOT/'build/host-frame-mailbox'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')).resolve()
    out.mkdir(parents=True,exist_ok=False)
    tools={name:shutil.which(name) for name in ('iverilog','vvp','verilator')}
    selected=['iverilog','verilator'] if args.simulator=='both' else [args.simulator]
    needed=['iverilog','vvp'] if selected==['iverilog'] else ['verilator'] if selected==['verilator'] else list(tools)
    owned_helper=ROOT/'tools/owned_process.py'
    before={str(p.relative_to(ROOT)):sha(p) for p in dut_inputs+[bench,Path(__file__).resolve(),owned_helper]}
    report=dict(status='RUNNING',component=args.component,scope='Single-clock raw-frame component only; no PCIe IP, CDC, NPU, FPGA or RK qualification',
        source_hashes_before=before,commands=[],simulators={},hardware_accessed=False,vivado_executed=False,
        stimulus='Deterministic DWORD patterns and channel delays; Icarus includes four-state controls',ram_limits_imposed=False)
    path=out/'report.json'
    def save():path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    save()
    def run(name,argv,cwd,limit):
        log=out/(name+'.log');started=time.monotonic()
        with log.open('xb') as stream:
            try:
                result=run_owned(argv,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,timeout=limit)
            except BaseException as error:
                cleanup=getattr(error,'owned_process_cleanup',{})
                row=dict(name=name,argv=argv,returncode=None,timed_out=False,status='EXCEPTION',timeout_seconds=limit,
                         seconds=time.monotonic()-started,log=str(log),log_sha256=sha(log),
                         pid=cleanup.get('pid'),pgid=cleanup.get('pgid'),
                         live_before_cleanup=cleanup.get('live_before_cleanup'),
                         live_after_cleanup=cleanup.get('live_after_cleanup'),exception=repr(error))
                report['commands'].append(row);save();raise
        rc=result.returncode;late=result.timed_out
        row=dict(name=name,argv=argv,returncode=rc,timed_out=late,
                 status='PASS' if rc==0 and not late and not result.live_before_cleanup and not result.live_after_cleanup else 'FAIL',
                 timeout_seconds=limit,
                 seconds=time.monotonic()-started,log=str(log),log_sha256=sha(log),pid=result.pid,pgid=result.pid,
                 live_before_cleanup=list(result.live_before_cleanup),live_after_cleanup=list(result.live_after_cleanup))
        report['commands'].append(row);save()
        require(rc==0 and not late and not result.live_before_cleanup and not result.live_after_cleanup,
                'Native component command failed or left descendants: '+name)
        text=log.read_text(errors='replace')
        require(not re.search(r'(?m)^%Warning-|^%Error|(?i:warning:|sorry:)',text),'Unexpected tool diagnostics: '+name)
        return text
    try:
        require(all(tools[name] for name in needed),'UNAVAILABLE: required native simulator not installed')
        for name in needed:
            flag='-V' if name in ('iverilog','vvp') else '--version'
            text=run(name+'_version',[tools[name],flag],out,30)
            report['simulators'][name]=dict(path=tools[name],binary_sha256=sha(Path(tools[name]).resolve()),version=text.splitlines()[0])
        for simulator in selected:
            directory=out/simulator;directory.mkdir()
            if simulator=='iverilog':
                image=directory/'sim.vvp'
                compile_argv=[tools[simulator],'-g2012','-Wall','-s',top,'-o',str(image),str(bench)]+[str(p) for p in dut_inputs]
                execute=[tools['vvp'],str(image)];expected=expected_counts[simulator]
            else:
                image=directory/'obj/sim'
                compile_argv=[tools[simulator],'--binary','--timing','--assert','-Wall','-j','2',
                    '--top-module',top,'--Mdir',str(directory/'obj'),'-o','sim',str(bench)]+[str(p) for p in dut_inputs]
                execute=[str(image)];expected=expected_counts[simulator]
            run(simulator+'_compile',compile_argv,directory,600)
            text=run(simulator+'_run',execute,directory,60)
            markers=re.findall(marker,text,re.M)
            if args.component=='admission':
                require(len(markers)==1 and markers[0][0]==str(expected_counts[simulator]) and
                        markers[0][1]==('1' if simulator=='iverilog' else '0'),
                        'Missing or changed admission marker/four-state scope: '+simulator)
                expected=expected_counts[simulator]
            else:
                require(markers==[str(expected)],'Missing or changed complete component marker: '+simulator)
            report['simulators'][simulator].update(checks=expected,image=str(image),image_sha256=sha(image),
                four_state_controls=simulator=='iverilog')
        after={str(p.relative_to(ROOT)):sha(p) for p in dut_inputs+[bench,Path(__file__).resolve(),owned_helper]}
        require(before==after,'Mailbox test inputs changed during execution')
        statuses={'mailbox':'PASS_AXIL_RAW_FRAME_MAILBOX_COMPONENT_ONLY',
                  'owner':'PASS_RAW_FRAME_OWNER_COMPONENT_ONLY',
                  'frontend':'PASS_PCIE_JTAG_FRAME_FRONTEND_INTEGRATION_ONLY',
                  'admission':'PASS_AXIL_RAW_FRAME_ADMISSION_COMPONENT_ONLY'}
        report.update(status=statuses[args.component],source_hashes_after=after)
    except BaseException as error:
        report.update(status='FAIL_AXIL_RAW_FRAME_MAILBOX_COMPONENT',error=repr(error));save();raise
    save();print(json.dumps(dict(status=report['status'],report=str(path),simulators=selected)))


if __name__=='__main__':main()
